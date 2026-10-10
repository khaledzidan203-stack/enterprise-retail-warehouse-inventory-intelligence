"""CP7-B2 tests; fixtures/output stay in memory; reference CSVs are read-only.

python -B -m unittest discover -s src/python -p test_observed_movements.py -v
"""

import csv
import unittest
from datetime import date
from decimal import Decimal
from unittest.mock import patch

import ingestion
import observed_movements as movement


def normalized(quantity="1", returned=False, day="2026-04-24", store="001", product="P01"):
    # Build a RAW fixture and delegate all parsing/types to the actual ingestion.
    raw = {field: "Sample" for field in ingestion.SALES_COLUMNS}
    raw.update({"Transaction Date": day, "Is Return": str(int(returned)),
                "Reason of Return": "", "Qty Sold": quantity, "Sales Amount": "0",
                "Cogs": "0", "Number of Transactions": "1", "Store": store, "Product No": product})
    return ingestion.normalize_row(raw, "sales", "fixture.csv", 2)


class MovementTests(unittest.TestCase):
    def test_duplicates_aggregate_without_netting_returns(self):
        sale = normalized("1.25")
        returned = normalized("-0.50", True)
        result = movement.aggregate_movements([sale, sale.copy(), returned, returned.copy()])
        self.assertEqual(len(result.demand), 1)
        self.assertEqual(len(result.returns), 1)
        self.assertEqual(result.demand[0].quantity, Decimal("2.50"))
        self.assertEqual(result.returns[0].quantity, Decimal("1.00"))
        self.assertEqual(result.demand[0].source_row_count, 2)
        self.assertEqual(result.returns[0].source_row_count, 2)
        self.assertEqual(result.demand[0].key, result.returns[0].key)
        self.assertEqual(result.source_rows, 4)
        self.assertEqual(sale["quantity_sold"], Decimal("1.25"))
        self.assertEqual(returned["quantity_sold"], Decimal("-0.50"))

    def test_zero_movements_are_explicitly_excluded(self):
        result = movement.aggregate_movements([normalized("0"), normalized("-0.0000", True)])
        self.assertEqual((result.demand, result.returns), ((), ()))
        self.assertEqual((result.source_rows, result.zero_nonreturn_rows, result.zero_return_rows), (2, 1, 1))

    def test_signed_return_contract_rejects_ambiguous_corrections(self):
        for row in [normalized("1", True), normalized("-1", False)]:
            with self.subTest(row=row), self.assertRaisesRegex(movement.MovementError, "fixture.csv: record 2.*sign"):
                movement.aggregate_movements([row])

    def test_provenance_preserved_and_simulation_rejected(self):
        result = movement.aggregate_movements([normalized(), normalized("-2", True)])
        self.assertEqual([x.provenance for x in result.demand + result.returns], ["OBS", "OBS"])
        bad = normalized()
        bad["provenance"] = "SIM"
        with self.assertRaisesRegex(movement.MovementError, "OBS provenance"):
            movement.aggregate_movements([bad])

    def test_grain_and_stable_order(self):
        rows = [normalized(store="002"), normalized(day="2026-04-23"),
                normalized(product="P02"), normalized(), normalized()]
        result = movement.aggregate_movements(iter(rows))
        self.assertEqual(result, movement.aggregate_movements(reversed(rows)))
        self.assertEqual(len(result.demand), 4)
        self.assertEqual([r.key for r in result.demand], sorted(r.key for r in result.demand))
        self.assertEqual(len({r.key for r in result.demand}), len(result.demand))

    def test_empty_input_and_late_ingestion_error(self):
        self.assertEqual(movement.aggregate_movements([]).source_rows, 0)
        def broken():
            yield normalized()
            raise ingestion.SchemaError("late input error")
        with self.assertRaisesRegex(ingestion.SchemaError, "late input error"):
            movement.aggregate_movements(broken())

    def test_entry_point_reuses_ingestion_and_detects_changed_source(self):
        root = ingestion.project_root()
        with patch.object(ingestion, "iter_sales", return_value=iter([normalized()])) as reader, \
             patch.object(ingestion, "file_hash", side_effect=["before", "after"]):
            with self.assertRaisesRegex(movement.MovementError, "changed"):
                movement.build_movements(root)
            reader.assert_called_once_with(root)


class ReferenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = movement.build_movements()

    def test_every_reference_key_and_quantity(self):
        for filename, field, generated, count, units in [
            ("fact_store_demand_service_v2.csv", "DemandQty", self.result.demand, 118256, 124542),
            ("fact_store_customer_return_inflow_v2.csv", "ReturnInflowQty", self.result.returns, 7491, 7547),
        ]:
            with self.subTest(filename=filename):
                expected = {}
                with (ingestion.project_root() / "data/integrated_v2" / filename).open(encoding="utf-8-sig", newline="") as stream:
                    for row in csv.DictReader(stream):
                        key = (date.fromisoformat(row["Date"]), row["Store"], row["Product No"])
                        self.assertNotIn(key, expected)
                        expected[key] = Decimal(row[field])
                actual = {row.key: row.quantity for row in generated}
                self.assertEqual(len(actual), len(generated))
                self.assertEqual(actual, expected)
                self.assertEqual((len(actual), sum(actual.values())), (count, units))
                self.assertTrue(all(row.provenance == "OBS" and row.quantity > 0 for row in generated))

    def test_holdout_and_complete_source_accounting(self):
        start, end = date(2026, 2, 2), date(2026, 4, 24)
        self.assertEqual(sum(r.quantity for r in self.result.demand if start <= r.date <= end), 30000)
        self.assertEqual(sum(r.quantity for r in self.result.returns if start <= r.date <= end), 1738)
        contributing = sum(r.source_row_count for r in self.result.demand + self.result.returns)
        self.assertEqual(self.result.source_rows, 125751)
        self.assertEqual((self.result.zero_nonreturn_rows, self.result.zero_return_rows), (2, 0))
        self.assertEqual(contributing + self.result.zero_nonreturn_rows + self.result.zero_return_rows, self.result.source_rows)

    def test_deterministic_full_rerun(self):
        self.assertEqual(self.result, movement.build_movements())


if __name__ == "__main__":
    unittest.main()
