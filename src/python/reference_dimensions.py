"""CP7-B4: governed Store/Product/Supplier/DC dimensions, Python 3.10+.

build_dimensions(root, contracts=None) reuses B3 contracts. assemble_dimensions
accepts existing contracts and the four supplied reference tables for orchestration.
No RAW parser, reference regeneration, eligibility filter, or downstream read.
All results stay in memory. CLI prints diagnostics only; no files are written.

Recovered projection: Store geography and Supplier profile are supplied columns;
Product uses six unambiguous OBS attributes from B3 plus supplied SIM ABCClass;
DC uses supplied key/IsSynthetic. DC descriptive fields and CasePack/MOQ are
validated but outside this dimension projection, not fabricated or discarded
from their original files. IsSynthetic flags describe supplied enrichment, not
every attribute: explicit column provenance distinguishes OBS keys from SIM data.
Original synthetic-generation/ABC assignment rules remain unrecovered; this stage
consumes governed inputs, not an inferred replacement for their generators.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path

if __package__:
    from . import ingestion, inventory_entities
else:
    import ingestion
    import inventory_entities

SCHEMAS = {
    "store_geography.csv": ("Store", "RegionCode", "RegionName", "SyntheticCityCode", "DistributionCenter", "IsSynthetic"),
    "product_supply_policy.csv": ("Product No", "Supplier", "Product Division", "ABCClass", "CasePack", "MOQ", "IsSyntheticPolicy"),
    "supplier_operational_profile.csv": ("Supplier", "SupplierClass", "ProductCount", "BaseLeadTimeDays", "OTIFTarget", "FillRateTarget", "IsSynthetic"),
    "distribution_centers.csv": ("DistributionCenter", "DistributionCenterName", "RegionCode", "RegionName", "IsSynthetic"),
}
INTEGER_COLUMNS = {"CasePack", "MOQ", "ProductCount", "BaseLeadTimeDays", "IsSynthetic", "IsSyntheticPolicy"}
RATE_COLUMNS = {"OTIFTarget", "FillRateTarget"}
PRODUCT_COLUMNS = ("Product No", "Supplier", "Product Description", "Product Division",
                   "Product Category", "Product Subcategory", "Product Segment", "ABCClass")
OBS_PRODUCT = {column: ingestion.INVENTORY_COLUMNS[column] for column in PRODUCT_COLUMNS[1:-1]}


class ReferenceError(ValueError):
    """Governed input schema/key/mapping inconsistency; never silently repaired."""


class UnresolvedRule(ReferenceError):
    """Selecting an attribute or changing entity coverage needs a reviewed rule."""


@dataclass(frozen=True)
class Dimension:
    name: str
    columns: tuple[str, ...]
    rows: tuple[tuple, ...]
    provenance: tuple[str, ...]
    attribute_sources: tuple[str, ...]

    def records(self):
        return (dict(zip(self.columns, row)) for row in self.rows)


@dataclass(frozen=True)
class Dimensions:
    tables: tuple[Dimension, ...]
    universe: tuple[inventory_entities.Pair, ...]

    def summary(self) -> dict:
        return {
            "stage": "CP7-B4", "source_universe_pairs": len(self.universe),
            "dimensions": {t.name: {"rows": len(t.rows), "attribute_provenance": dict(zip(t.columns, t.provenance))} for t in self.tables},
            "scope": "Supplied governed references, not regenerated synthetic policies or simulation eligibility",
            "unrecovered_rules": ["original synthetic reference generation", "original ABC assignment method", "simulation eligibility policy"],
        }


def read_references(root: Path) -> dict[str, list[dict]]:
    """Read the four governed inputs; common validation occurs in assembly."""
    result = {}
    for filename, columns in SCHEMAS.items():
        path = Path(root) / "data" / "synthetic" / filename
        before = ingestion.file_hash(path)
        try:
            with path.open(encoding="utf-8-sig", newline="") as stream:
                reader = csv.reader(stream, strict=True)
                header = next(reader, None)
                if header is None or len(set(header)) != len(header) or set(header) != set(columns):
                    raise ReferenceError(f"{filename}: missing, unexpected or duplicate headers")
                rows = []
                for record, values in enumerate(reader, 2):
                    if len(values) != len(header):
                        raise ReferenceError(f"{filename}: record {record}: wrong field count")
                    rows.append(dict(zip(header, values)))
                result[filename] = rows
        except (UnicodeError, csv.Error) as exc:
            raise ReferenceError(f"{filename}: invalid UTF-8/CSV: {exc}") from exc
        if ingestion.file_hash(path) != before:
            raise ReferenceError(f"{filename}: source changed during reading")
    return result


def validated_tables(inputs: dict) -> dict:
    if set(inputs) != set(SCHEMAS):
        raise ReferenceError("Expected exactly the four governed reference tables")
    tables = {}
    for filename, columns in SCHEMAS.items():
        index = {}
        for record, raw in enumerate(inputs[filename], 2):
            if set(raw) != set(columns):
                raise ReferenceError(f"{filename}: record {record}: schema mismatch")
            row = {}
            for column in columns:
                value = raw[column]
                if not isinstance(value, str) or not value or value != value.strip():
                    raise ReferenceError(f"{filename}: record {record}: {column}: blank/nontext or surrounding whitespace")
                if column in INTEGER_COLUMNS:
                    if not re.fullmatch(r"[0-9]+", value):
                        raise ReferenceError(f"{filename}: {column}: expected nonnegative integer")
                    value = int(value)
                    if column in {"IsSynthetic", "IsSyntheticPolicy"} and value != 1:
                        raise ReferenceError(f"{filename}: {column}: expected supplied SIM flag 1")
                    if column in {"CasePack", "MOQ"} and value == 0:
                        raise ReferenceError(f"{filename}: {column}: expected positive units")
                elif column in RATE_COLUMNS:
                    try:
                        if not re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", value):
                            raise InvalidOperation
                        value = Decimal(value)
                        if not value.is_finite() or not 0 <= value <= 1:
                            raise InvalidOperation
                    except InvalidOperation as exc:
                        raise ReferenceError(f"{filename}: {column}: expected finite rate in [0,1]") from exc
                row[column] = value
            key = row[columns[0]]
            if key in index:
                raise ReferenceError(f"{filename}: duplicate key {key}")
            index[key] = row
        if not index:
            raise ReferenceError(f"{filename}: no data rows")
        tables[filename] = index
    return tables


def observed_entities(items, label):
    entities = {}
    for item in items:
        if not item.key or item.key in entities or item.provenance != "OBS":
            raise ReferenceError(f"{label}: duplicate/blank entity key or non-OBS provenance")
        entities[item.key] = item
    return entities


def same_keys(actual, expected, label):
    missing, extra = set(expected) - set(actual), set(actual) - set(expected)
    if missing or extra:
        raise UnresolvedRule(f"{label}: missing={sorted(missing)}, extra={sorted(extra)}; no implicit eligibility filter")


def assemble_dimensions(contracts: inventory_entities.InventoryContracts, inputs: dict) -> Dimensions:
    """Strict joins and projection; no first-match selection or source mutation."""
    tables = validated_tables(inputs)
    geo, policy, profiles, centers = (tables[name] for name in SCHEMAS)
    stores = observed_entities(contracts.stores, "B3 stores")
    products = observed_entities(contracts.products, "B3 products")
    same_keys(geo, stores, "Store geography coverage")
    same_keys(policy, products, "Product policy coverage")
    seen_pairs = set()
    for pair in contracts.universe:
        if pair.key in seen_pairs or pair.store not in stores or pair.product_no not in products or pair.provenance != "OBS":
            raise ReferenceError("B3 universe: duplicate/orphan pair or non-OBS provenance")
        seen_pairs.add(pair.key)
    if {p.store for p in contracts.universe} != set(stores) or {p.product_no for p in contracts.universe} != set(products):
        raise ReferenceError("B3 universe/entity coverage is inconsistent")
    product_rows = []
    supplier_counts = Counter()
    for key, item in sorted(products.items()):
        fields = {a.name: a for a in item.attributes}
        if len(fields) != len(item.attributes):
            raise UnresolvedRule(f"Product {key}: duplicate attribute definitions")
        values = {}
        for column, normalized in OBS_PRODUCT.items():
            attribute = fields.get(normalized)
            if attribute is None or len(attribute.values) != 1 or not attribute.values[0]:
                raise UnresolvedRule(f"Product {key}: {column}: missing/conflicting OBS values")
            values[column] = attribute.values[0]
        for column in ("Supplier", "Product Division"):
            if policy[key][column] != values[column]:
                raise UnresolvedRule(f"Product {key}: {column} disagrees between OBS and supplied policy")
        supplier_counts[values["Supplier"]] += 1
        product_rows.append((key, *(values[c] for c in PRODUCT_COLUMNS[1:-1]), policy[key]["ABCClass"]))
    same_keys(profiles, supplier_counts, "Supplier profile coverage")
    for key, profile in profiles.items():
        if profile["ProductCount"] != supplier_counts[key]:
            raise UnresolvedRule(f"Supplier {key}: supplied ProductCount differs from observed product mapping; not recomputed")
    for key, row in geo.items():
        if row["DistributionCenter"] not in centers:
            raise ReferenceError(f"Store {key}: missing DistributionCenter {row['DistributionCenter']}")

    def supplied(name, index, columns, observed_key=False):
        return Dimension(name, columns, tuple(tuple(row[c] for c in columns) for _, row in sorted(index.items())),
                         tuple("OBS" if i == 0 and observed_key else "SIM" for i in range(len(columns))),
                         tuple("B3 observed entity key, validated against supplied reference" if i == 0 and observed_key
                               else "data/synthetic/" + {"DimStore": "store_geography.csv", "DimSupplier": "supplier_operational_profile.csv", "DimDistributionCenter": "distribution_centers.csv"}[name]
                               for i in range(len(columns))))

    product = Dimension("DimProduct", PRODUCT_COLUMNS, tuple(product_rows),
                        ("OBS",) * 7 + ("SIM",),
                        ("B3 observed product entity",) * 7 + ("data/synthetic/product_supply_policy.csv",))
    return Dimensions((supplied("DimStore", geo, SCHEMAS["store_geography.csv"], True), product,
                       supplied("DimSupplier", profiles, SCHEMAS["supplier_operational_profile.csv"], True),
                       supplied("DimDistributionCenter", centers, ("DistributionCenter", "IsSynthetic"))),
                      contracts.universe)


def build_dimensions(root: Path | None = None,
                     contracts: inventory_entities.InventoryContracts | None = None) -> Dimensions:
    root = ingestion.project_root() if root is None else Path(root)
    if contracts is None:
        contracts = inventory_entities.build_contracts(root)
    return assemble_dimensions(contracts, read_references(root))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=ingestion.project_root())
    args = parser.parse_args()
    try:
        result = build_dimensions(args.project_root)
    except (OSError, ValueError) as exc:
        parser.exit(2, f"Reference dimensions failed: {exc}\n")
    print(json.dumps(result.summary(), sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
