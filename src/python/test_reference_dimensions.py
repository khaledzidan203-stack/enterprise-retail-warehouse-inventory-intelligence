"""CP7-B4 tests; downstream CSVs are read-only test oracles only.

python -B -m unittest discover -s src/python -p test_reference_dimensions.py -v
"""

import copy
import csv
import io
import unittest
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import ingestion
import inventory_entities as entity
import reference_dimensions as dimensions


def fixture():
    values = {"supplier": "V1", "product_description": "Description", "product_division": "Division",
              "product_category": "Category", "product_subcategory": "Subcategory", "product_segment": "Segment"}
    product = entity.Entity("P1", tuple(entity.Attribute(k, (entity.AttributeValue(v, "raw.csv", 1, 2),)) for k, v in values.items()))
    contracts = entity.InventoryContracts(
        (entity.Pair("S1", "P1", 0, 1, Decimal(0), Decimal(0)),),
        (product,), (entity.Entity("S1", ()),), (), (), (), ())
    rows = {
        "store_geography.csv": [("S1", "R1", "Region", "C1", "DC1", "1")],
        "product_supply_policy.csv": [("P1", "V1", "Division", "B", "2", "4", "1")],
        "supplier_operational_profile.csv": [("V1", "Strategic", "1", "7", "0.97", "0.98", "1")],
        "distribution_centers.csv": [("DC1", "Center", "R1", "Region", "1")],
    }
    return contracts, {k: [dict(zip(dimensions.SCHEMAS[k], r)) for r in v] for k, v in rows.items()}


class ContractTests(unittest.TestCase):
    def test_projection_provenance_and_universe_preserved(self):
        contracts, refs = fixture()
        before = copy.deepcopy(refs)
        result = dimensions.assemble_dimensions(contracts, refs)
        self.assertIs(result.universe, contracts.universe)
        self.assertEqual(result.universe[0].sales_rows, 0)  # Inventory-only retained.
        product = next(t for t in result.tables if t.name == "DimProduct")
        self.assertEqual(product.rows[0][-1], "B")
        self.assertEqual(product.provenance, ("OBS",) * 7 + ("SIM",))
        for table in result.tables:
            self.assertEqual(len(table.columns), len(table.provenance))
            self.assertEqual(len(table.columns), len(table.attribute_sources))
            self.assertEqual(len({r[0] for r in table.rows}), len(table.rows))
        self.assertEqual(refs, before)

    def test_duplicate_reference_keys_rejected_in_all_inputs(self):
        contracts, refs = fixture()
        for filename in refs:
            bad = copy.deepcopy(refs)
            bad[filename].append(dict(bad[filename][0]))
            with self.subTest(filename=filename), self.assertRaisesRegex(dimensions.ReferenceError, "duplicate key"):
                dimensions.assemble_dimensions(contracts, bad)

    def test_missing_extra_and_orphan_mappings(self):
        contracts, refs = fixture()
        for filename, column, value in [
            ("store_geography.csv", "Store", "S2"),
            ("product_supply_policy.csv", "Product No", "P2"),
            ("supplier_operational_profile.csv", "Supplier", "V2"),
            ("store_geography.csv", "DistributionCenter", "missing"),
        ]:
            bad = copy.deepcopy(refs)
            bad[filename][0][column] = value
            with self.subTest(column=column), self.assertRaises(dimensions.ReferenceError):
                dimensions.assemble_dimensions(contracts, bad)
        extra = copy.deepcopy(refs)
        extra["store_geography.csv"].append(dict(extra["store_geography.csv"][0], Store="S2"))
        with self.assertRaises(dimensions.UnresolvedRule):
            dimensions.assemble_dimensions(contracts, extra)

    def test_obs_conflicts_and_policy_disagreements_are_unresolved(self):
        contracts, refs = fixture()
        product = contracts.products[0]
        attr = product.attributes[0]
        conflict = replace(attr, observations=attr.observations + (entity.AttributeValue("V2", "other.csv", 1, 2),))
        ambiguous = replace(contracts, products=(replace(product, attributes=(conflict,) + product.attributes[1:]),))
        with self.assertRaisesRegex(dimensions.UnresolvedRule, "conflicting OBS"):
            dimensions.assemble_dimensions(ambiguous, refs)
        for column in ("Supplier", "Product Division"):
            bad = copy.deepcopy(refs)
            bad["product_supply_policy.csv"][0][column] = "Different"
            with self.assertRaisesRegex(dimensions.UnresolvedRule, "disagrees"):
                dimensions.assemble_dimensions(contracts, bad)
        bad = copy.deepcopy(refs)
        bad["supplier_operational_profile.csv"][0]["ProductCount"] = "2"
        with self.assertRaisesRegex(dimensions.UnresolvedRule, "not recomputed"):
            dimensions.assemble_dimensions(contracts, bad)

    def test_schema_types_flags_and_empty_inputs(self):
        contracts, refs = fixture()
        cases = [("supplier_operational_profile.csv", "OTIFTarget", "NaN"),
                 ("supplier_operational_profile.csv", "FillRateTarget", "1.1"),
                 ("supplier_operational_profile.csv", "BaseLeadTimeDays", "1.5"),
                 ("product_supply_policy.csv", "MOQ", "0"),
                 ("store_geography.csv", "IsSynthetic", "0"),
                 ("store_geography.csv", "Store", " S1"),
                 ("store_geography.csv", "RegionName", "")]
        for filename, column, value in cases:
            bad = copy.deepcopy(refs)
            bad[filename][0][column] = value
            with self.subTest(column=column, value=value), self.assertRaises(dimensions.ReferenceError):
                dimensions.assemble_dimensions(contracts, bad)
        for variant in ("empty", "missing", "extra"):
            bad = copy.deepcopy(refs)
            if variant == "empty":
                bad["store_geography.csv"] = []
            elif variant == "missing":
                del bad["store_geography.csv"][0]["RegionName"]
            else:
                bad["store_geography.csv"][0]["Unknown"] = "x"
            with self.assertRaises(dimensions.ReferenceError):
                dimensions.assemble_dimensions(contracts, bad)

    def test_b3_entity_and_pair_integrity(self):
        contracts, refs = fixture()
        for bad in [replace(contracts, products=contracts.products * 2),
                    replace(contracts, universe=contracts.universe * 2),
                    replace(contracts, universe=()),
                    replace(contracts, stores=(replace(contracts.stores[0], provenance="SIM"),))]:
            with self.assertRaises(dimensions.ReferenceError):
                dimensions.assemble_dimensions(bad, refs)

    def test_assembly_reads_no_files_and_orchestration_reuses_b3(self):
        contracts, refs = fixture()
        with patch.object(Path, "open", side_effect=AssertionError("unexpected file read")):
            dimensions.assemble_dimensions(contracts, refs)
        with patch.object(entity, "build_contracts", side_effect=AssertionError("must reuse B3")), \
             patch.object(dimensions, "read_references", return_value=refs):
            self.assertIs(dimensions.build_dimensions(contracts=contracts).universe, contracts.universe)

    def test_reference_reader_rejects_duplicate_headers_and_ragged_rows(self):
        columns = dimensions.SCHEMAS["store_geography.csv"]
        for content in [",".join(columns + ("Store",)) + "\n", ",".join(columns) + "\nS1,R1\n"]:
            with patch.object(ingestion, "file_hash", return_value="unchanged"), \
                 patch.object(Path, "open", return_value=io.StringIO(content)), \
                 self.assertRaises(dimensions.ReferenceError):
                dimensions.read_references(Path("unused"))


class ReferenceTests(unittest.TestCase):
    def test_all_generated_rows_attributes_and_determinism(self):
        root = ingestion.project_root()
        contracts = entity.build_contracts(root)
        refs = dimensions.read_references(root)
        result = dimensions.assemble_dimensions(contracts, refs)
        self.assertIs(result.universe, contracts.universe)
        self.assertEqual(len(result.universe), 63556)
        expected_counts = {"DimStore": 40, "DimProduct": 2326, "DimSupplier": 30, "DimDistributionCenter": 4}
        cells = 0
        for table in result.tables:
            with self.subTest(table=table.name):
                with (root / "data/powerbi_model_v1" / (table.name + ".csv")).open(encoding="utf-8-sig", newline="") as stream:
                    reader = csv.DictReader(stream)
                    self.assertEqual(tuple(reader.fieldnames), table.columns)
                    expected = {}
                    for raw in reader:
                        row = tuple(int(raw[c]) if c in dimensions.INTEGER_COLUMNS else
                                    Decimal(raw[c]) if c in dimensions.RATE_COLUMNS else raw[c] for c in table.columns)
                        self.assertNotIn(row[0], expected)
                        expected[row[0]] = row
                actual = {row[0]: row for row in table.rows}
                self.assertEqual(len(actual), len(table.rows))
                self.assertEqual(actual, expected)
                self.assertEqual(len(actual), expected_counts[table.name])
                self.assertEqual(list(actual), sorted(actual))
                cells += len(actual) * len(table.columns)
        self.assertEqual(cells, 19066)
        # Reuse the same B3 output, not repeat ingestion/interval transformations.
        shuffled = {k: list(reversed(v)) for k, v in reversed(list(refs.items()))}
        self.assertEqual(result, dimensions.assemble_dimensions(contracts, shuffled))
        self.assertEqual(result, dimensions.build_dimensions(root, contracts=contracts))


if __name__ == "__main__":
    unittest.main()
