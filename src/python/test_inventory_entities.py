"""CP7-B3 tests. All fixtures/results stay in memory; references are test-only.

python -B -m unittest discover -s src/python -p test_inventory_entities.py -v
"""

import csv
import gc
import hashlib
import unittest
from collections import Counter
from dataclasses import replace
from datetime import date
from decimal import Decimal
from unittest.mock import patch

import ingestion
import inventory_entities as entity
import observed_movements as movement


def normalized(kind, record=2, **changes):
    mapping = ingestion.SALES_COLUMNS if kind == "sales" else ingestion.INVENTORY_COLUMNS
    raw = {k: "Sample" for k in mapping}
    for k, v in mapping.items():
        if v in ingestion.DATE_FIELDS:
            raw[k] = "2026-04-24"
        if v in ingestion.DECIMAL_FIELDS:
            raw[k] = "1.0000"
    raw.update({"Store": "S1", "Product No": "P1"})
    if kind == "sales":
        raw.update({"Is Return": "0", "Reason of Return": "", "Number of Transactions": "1"})
    raw.update(changes)
    return ingestion.normalize_row(raw, kind, f"{kind}.csv", record)


def profile(sales=(), inventory=()):
    return entity.profile_sources(iter(sales), iter(inventory), movement.aggregate_movements(sales))


def fingerprint(result):
    digest = hashlib.sha256()
    for name in result.__dataclass_fields__:
        digest.update(name.encode())
        for row in getattr(result, name):
            digest.update(repr(row).encode("utf-8"))
            digest.update(b"\n")
    return digest.hexdigest()


class ContractTests(unittest.TestCase):
    def test_union_includes_zero_only_sales_and_inventory_only(self):
        sales = [normalized("sales", **{"Qty Sold": "0"})]
        inventory = [normalized("inventory", **{"Product No": "P2"})]
        result = profile(sales, inventory)
        self.assertEqual([p.key for p in result.universe], [("S1", "P1"), ("S1", "P2")])
        self.assertEqual([p.sources for p in result.universe], [("RAW_SALES",), ("RAW_INVENTORY",)])
        self.assertTrue(all(p.provenance == "OBS" and p.demand_units == 0 for p in result.universe))

    def test_original_intervals_and_repeated_rows_preserved(self):
        a = normalized("inventory", **{"End Date": "9999-12-31", "Qty on hand": "-2.50"})
        b = dict(a, source_record_number=3)
        result = profile(inventory=[a, b])
        self.assertEqual([i.as_dict() for i in result.intervals], [a, b])
        self.assertEqual(len(result.universe), 1)
        self.assertEqual(result.universe[0].inventory_rows, 2)
        self.assertEqual(len(result.negative_stock_records), 2)
        self.assertEqual(len(result.open_ended_records), 2)
        self.assertEqual(result.intervals[0].as_dict()["end_date"], date.max)
        self.assertEqual(len(result.overlaps), 1)
        self.assertFalse(result.overlaps[0].different_quantities)

    def test_boundaries_adjacency_points_and_nested_intervals(self):
        def interval(n, start, end):
            return normalized("inventory", n, **{"Start Date": start, "End Date": end})
        rows = [interval(2, "2026-01-01", "2026-01-10"),
                interval(3, "2026-01-02", "2026-01-03"),
                interval(4, "2026-01-04", "2026-01-05"),
                interval(5, "2026-01-10", "2026-01-10"),
                interval(6, "2026-01-11", "2026-01-12")]
        result = profile(inventory=rows)
        self.assertEqual([(o.left[1], o.right[1], o.kind) for o in result.overlaps],
                         [(2, 3, "INTERIOR_OVERLAP"), (2, 4, "INTERIOR_OVERLAP"), (2, 5, "BOUNDARY_CONTACT")])
        self.assertEqual(result, profile(inventory=list(reversed(rows))))

    def test_conflicts_preserve_all_values_and_source_evidence(self):
        sales = [normalized("sales", Supplier="A")]
        inventory = [normalized("inventory", Supplier="B", **{"Store Type": "One"}),
                     normalized("inventory", 3, Supplier="B", **{"Store Type": "Two", "Qty on hand": "2"})]
        result = profile(sales, inventory)
        supplier = next(a for a in result.products[0].attributes if a.name == "supplier")
        store_type = next(a for a in result.stores[0].attributes if a.name == "store_type")
        self.assertEqual(supplier.values, ("A", "B"))
        self.assertTrue(supplier.requires_review and store_type.requires_review)
        self.assertEqual([(v.source, v.row_count) for v in supplier.observations], [("sales.csv", 1), ("inventory.csv", 2)])
        self.assertFalse(result.overlaps[0].same_descriptors)
        self.assertTrue(result.overlaps[0].different_quantities)
        self.assertEqual(result.summary()["classification"]["overlaps_and_multiple_attributes"], "REVIEW_REQUIRED_NOT_AUTOMATIC_ERROR")

    def test_movement_linkage_and_provenance_exceptions(self):
        sales = [normalized("sales")]
        good = movement.aggregate_movements(sales)
        with self.assertRaises(entity.ContractError):
            entity.profile_sources([], [], good)
        with self.assertRaises(entity.ContractError):
            entity.profile_sources(sales, [], replace(good, source_rows=2))
        with self.assertRaises(entity.ContractError):
            entity.profile_sources(sales, [], replace(good, demand=good.demand * 2))
        bad = dict(sales[0], provenance="SIM")
        with self.assertRaises(entity.ContractError):
            entity.profile_sources([bad], [], good)

    def test_empty_and_delegated_interval_validation(self):
        self.assertEqual(profile().universe, ())
        with self.assertRaises(ingestion.SchemaError):
            normalized("inventory", **{"Start Date": "2026-04-24", "End Date": "2026-04-23"})

    def test_orchestration_reuses_supplied_movements_and_ingestion(self):
        sales, inventory = [normalized("sales")], [normalized("inventory")]
        existing = movement.aggregate_movements(sales)
        with patch.object(ingestion, "iter_sales", return_value=iter(sales)) as sr, \
             patch.object(ingestion, "iter_inventory", return_value=iter(inventory)) as ir, \
             patch.object(ingestion, "file_hash", return_value="stable"), \
             patch.object(movement, "build_movements", side_effect=AssertionError("must reuse supplied output")):
            result = entity.build_contracts(movements=existing)
            self.assertEqual(result.universe[0].demand_units, 1)
            sr.assert_called_once()
            ir.assert_called_once()


class SourceReferenceTests(unittest.TestCase):
    def test_full_source_reconciliation_dimensions_and_determinism(self):
        result = entity.build_contracts()
        root = ingestion.project_root()
        counts = [Counter(), Counter()]
        for index, name in enumerate((ingestion.SALES_FILE, ingestion.INVENTORY_FILE)):
            with (root / "data/raw" / name).open(encoding="utf-8-sig", newline="") as stream:
                for row in csv.DictReader(stream):
                    counts[index][(row["Store"], row["Product No"])] += 1
        pairs = {p.key: p for p in result.universe}
        self.assertEqual(len(pairs), len(result.universe))
        self.assertEqual(set(pairs), counts[0].keys() | counts[1].keys())
        for key, pair in pairs.items():
            self.assertEqual((pair.sales_rows, pair.inventory_rows), (counts[0][key], counts[1][key]))
            self.assertEqual(pair.provenance, "OBS")
        # Every source interval survives unchanged relative to the B1 interface.
        iterator = iter(result.intervals)
        for row in ingestion.iter_inventory():
            self.assertEqual(next(iterator).as_dict(), row)
        self.assertIsNone(next(iterator, None))
        summary = result.summary()
        self.assertEqual((summary["store_product_pairs"], summary["sales_only_pairs"], summary["inventory_only_pairs"]), (63556, 2588, 13109))
        self.assertEqual((summary["inventory_rows"], summary["negative_stock_records"], summary["open_ended_records"]), (284755, 1380, 22701))
        self.assertEqual((summary["interior_overlap_pairs"], summary["boundary_contact_pairs"]), (0, 0))
        self.assertEqual(sum(p.demand_units for p in result.universe), 124542)
        self.assertEqual(sum(p.return_units for p in result.universe), 7547)

        for filename, column, entities in [("DimProduct.csv", "Product No", result.products),
                                           ("DimStore.csv", "Store", result.stores)]:
            with (root / "data/powerbi_model_v1" / filename).open(encoding="utf-8-sig", newline="") as stream:
                rows = list(csv.DictReader(stream))
            baseline = {r[column]: r for r in rows}
            self.assertEqual(len(baseline), len(rows))
            self.assertEqual({e.key for e in entities}, set(baseline))
            # Compare only attributes actually observable in RAW and present
            # in the governed dimension. Never invent ABC/region/DC mappings.
            comparable = {v: k for k, v in ingestion.INVENTORY_COLUMNS.items() if k in rows[0]}
            checked = set()
            for item in entities:
                self.assertEqual(item.provenance, "OBS")
                for attribute in item.attributes:
                    self.assertFalse(attribute.requires_review)
                    if attribute.name in comparable:
                        checked.add(attribute.name)
                        self.assertEqual(attribute.values, (baseline[item.key][comparable[attribute.name]],))
            self.assertEqual(checked, set(entity.PRODUCT_ATTRIBUTES) if column == "Product No" else set())

        # Hash all output objects, release the first large result, then rebuild.
        expected_hash = fingerprint(result)
        del result, pairs, entities
        gc.collect()
        second = entity.build_contracts()
        self.assertEqual(fingerprint(second), expected_hash)


if __name__ == "__main__":
    unittest.main()
