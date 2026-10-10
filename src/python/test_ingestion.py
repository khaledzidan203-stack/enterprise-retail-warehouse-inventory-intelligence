"""CP7-B1 tests. Run: python -B -m unittest discover -s src/python -v

Fixtures stay in memory. Baselines are read-only oracles, never pipeline inputs.
"""

import csv
import io
import unittest
from collections import defaultdict
from datetime import date
from decimal import Decimal

import ingestion as ing


def fixture(kind="sales", **changes):
    mapping = ing.SALES_COLUMNS if kind == "sales" else ing.INVENTORY_COLUMNS
    row = {k: "Sample" for k in mapping}
    for k, normalized in mapping.items():
        if normalized in ing.DATE_FIELDS:
            row[k] = "2026-04-24"
        if normalized in ing.DECIMAL_FIELDS:
            row[k] = "1.0000"
    if kind == "sales":
        row.update({"Is Return": "0", "Reason of Return": "", "Number of Transactions": "1"})
    row.update(changes)
    return row


def parse(rows, kind="sales", header=None):
    header = list(rows[0]) if header is None else header
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(header)
    writer.writerows([[row.get(k, "") for k in header] for row in rows])
    stream.seek(0)
    return list(ing.read_rows(stream, kind, "fixture.csv"))


class SchemaTests(unittest.TestCase):
    def test_types_identifiers_blanks_and_no_dedup(self):
        original = fixture(Store=" 0007 ", **{"Qty Sold": "0.0000", "Sales Amount": "0.1000", "Product Description": "quoted,\ntext"})
        rows = parse([original, original])
        self.assertEqual([r["source_record_number"] for r in rows], [2, 3])
        self.assertEqual(rows[0]["store"], "0007")
        self.assertIsNone(rows[0]["reason_of_return"])
        self.assertEqual(rows[0]["sales_amount"], Decimal("0.1000"))
        self.assertEqual(rows[0]["transaction_date"], date(2026, 4, 24))
        self.assertEqual(rows[0]["product_description"], "quoted,\ntext")
        self.assertEqual(rows[0]["provenance"], "OBS")

    def test_signed_return_and_fractional_quantity_preserved(self):
        row = parse([fixture(**{"Is Return": "1", "Qty Sold": "-1.25"})])[0]
        self.assertTrue(row["is_return"])
        self.assertEqual(row["quantity_sold"], Decimal("-1.25"))

    def test_inventory_sentinel_and_negative_preserved(self):
        row = parse([fixture("inventory", **{"End Date": "9999-12-31", "Qty on hand": "-3"})], "inventory")[0]
        self.assertEqual(row["end_date"], date.max)
        self.assertTrue(row["is_open_ended"])
        self.assertEqual(row["quantity_on_hand"], Decimal(-3))

    def test_header_contract(self):
        row = fixture()
        self.assertEqual(parse([row]), parse([row], header=list(reversed(row))))
        for header in [list(row)[:-1], list(row) + ["Unexpected"], list(row) + ["Store"]]:
            with self.subTest(header=header), self.assertRaises(ing.SchemaError):
                parse([row], header=header)

    def test_invalid_fields_fail_with_context(self):
        cases = [("Store", ""), ("Qty Sold", ""), ("Qty Sold", "NaN"), ("Qty Sold", "Infinity"),
                 ("Qty Sold", "1,000"), ("Qty Sold", "1e3"), ("Qty Sold", "1_000"),
                 ("Transaction Date", "2026-02-30"), ("Transaction Date", "20260424"),
                 ("Transaction Date", "9999-12-31"), ("Is Return", "2"),
                 ("Number of Transactions", "1.5"), ("Number of Transactions", "-1")]
        for field, value in cases:
            with self.subTest(field=field, value=value), self.assertRaisesRegex(ing.SchemaError, "fixture.csv: record 2"):
                parse([fixture(**{field: value})])

    def test_reversed_interval_rejected(self):
        with self.assertRaisesRegex(ing.SchemaError, "End Date precedes"):
            parse([fixture("inventory", **{"End Date": "2026-04-23"})], "inventory")

    def test_empty_truncated_and_malformed_csv_rejected(self):
        header = ",".join(ing.SALES_COLUMNS)
        for content in ["", header + "\n", header + "\nx,y\n", header + '\n"unterminated']:
            with self.subTest(content=content), self.assertRaises(ing.SchemaError):
                list(ing.read_rows(io.StringIO(content), "sales", "fixture.csv"))

    def test_unknown_kind(self):
        with self.assertRaises(ValueError):
            list(ing.read_rows(io.StringIO(""), "unknown", "fixture.csv"))
        with self.assertRaises(ValueError):
            ing.normalize_row({}, "unknown", "fixture.csv", 2)

    def test_utf8_bom_and_invalid_encoding(self):
        row = fixture(**{"Product Description": "\u0645\u0646\u062a\u062c"})
        content = io.StringIO(newline="")
        writer = csv.DictWriter(content, fieldnames=list(row))
        writer.writeheader()
        writer.writerow(row)
        stream = io.TextIOWrapper(io.BytesIO(content.getvalue().encode("utf-8-sig")), encoding="utf-8-sig", newline="")
        self.assertEqual(list(ing.read_rows(stream, "sales", "fixture.csv"))[0]["product_description"], "\u0645\u0646\u062a\u062c")
        stream = io.TextIOWrapper(io.BytesIO(b"\xff"), encoding="utf-8-sig", newline="")
        with self.assertRaisesRegex(ing.SchemaError, "invalid CSV/UTF-8"):
            list(ing.read_rows(stream, "sales", "fixture.csv"))


class ReferenceTests(unittest.TestCase):
    """Test full normalized rows against RAW and movement contracts in memory."""

    def test_raw_roundtrip_every_field_and_row(self):
        for kind, expected_count in [("sales", 125751), ("inventory", 284755)]:
            mapping = ing.SALES_COLUMNS if kind == "sales" else ing.INVENTORY_COLUMNS
            count = 0
            with ing.source_path(ing.project_root(), kind).open(encoding="utf-8-sig", newline="") as stream:
                original = csv.DictReader(stream)
                normalized = ing.iter_source(ing.project_root(), kind)
                for count, raw in enumerate(original, 1):
                    row = next(normalized)
                    self.assertEqual(row["source_record_number"], count + 1)
                    for field, name in mapping.items():
                        value = row[name]
                        if isinstance(value, date):
                            self.assertEqual(value.isoformat(), raw[field])
                        elif isinstance(value, bool):
                            self.assertEqual(str(int(value)), raw[field])
                        elif isinstance(value, (Decimal, int)):
                            self.assertEqual(Decimal(value), Decimal(raw[field]))
                        else:
                            self.assertEqual(value, raw[field].strip() or None)
                self.assertIsNone(next(normalized, None))
            self.assertEqual(count, expected_count)

    def test_observed_movements_match_governed_rows(self):
        demand, returns = defaultdict(Decimal), defaultdict(Decimal)
        holdout_demand = holdout_returns = Decimal(0)
        zero_rows = 0
        for row in ing.iter_sales():
            key = (row["transaction_date"].isoformat(), row["store"], row["product_no"])
            quantity = row["quantity_sold"]
            holdout = date(2026, 2, 2) <= row["transaction_date"] <= date(2026, 4, 24)
            zero_rows += quantity == 0
            if row["is_return"]:
                returns[key] += abs(quantity)
                if holdout:
                    holdout_returns += abs(quantity)
            elif quantity > 0:
                demand[key] += quantity
                if holdout:
                    holdout_demand += quantity
        for filename, quantity_field, actual in [
            ("fact_store_demand_service_v2.csv", "DemandQty", demand),
            ("fact_store_customer_return_inflow_v2.csv", "ReturnInflowQty", returns),
        ]:
            expected = {}
            with (ing.project_root() / "data" / "integrated_v2" / filename).open(encoding="utf-8-sig", newline="") as stream:
                for row in csv.DictReader(stream):
                    key = (row["Date"], row["Store"], row["Product No"])
                    self.assertNotIn(key, expected)
                    expected[key] = Decimal(row[quantity_field])
            self.assertEqual(dict(actual), expected)
        self.assertEqual((len(demand), len(returns)), (118256, 7491))
        self.assertEqual(sum(demand.values()), 124542)
        self.assertEqual(sum(returns.values()), 7547)
        self.assertEqual((holdout_demand, holdout_returns, zero_rows), (30000, 1738, 2))


if __name__ == "__main__":
    unittest.main()
