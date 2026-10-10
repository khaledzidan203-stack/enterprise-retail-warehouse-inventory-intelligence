"""CP7-B3: observed inventory intervals and entity contracts (Python 3.10+).

Run: python -B src/python/inventory_entities.py [--project-root PATH]
build_contracts(root, movements=None) supports orchestration with CP7-B2 results.
RAW is read only through ingestion; no downstream reference is a dependency.
Sales is revisited for attributes and zero-only entities absent from movements.
All outputs remain in memory. No stock simulation or opening balance is derived.

Intervals retain every normalized ingestion field and source record identity.
The source files retain original lexical values; CP7-B1 text normalization is
not reversed. Negative observed stock and open ends are source characteristics.
Overlap is tested at Store x Product, without assuming stock-status partitions:
max(start) < min(end) is interior overlap; equality is boundary contact under
closed-date interpretation. Boundary inclusion and partition semantics remain
unresolved. Conflicting attributes are review candidates, not auto-corrections
or proof of erroneous master data (they may be temporal/multivalued).
"""

from __future__ import annotations

import argparse
import heapq
import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Iterable, Mapping

if __package__:
    from . import ingestion, observed_movements
else:
    import ingestion
    import observed_movements

PRODUCT_ATTRIBUTES = ("supplier", "product_description", "product_division",
                      "product_category", "product_subcategory", "product_segment")
STORE_ATTRIBUTES = ("store_type", "sales_channel")


class ContractError(ValueError):
    """An input violates the normalized-source or movement linkage contract."""


@dataclass(frozen=True)
class Pair:
    store: str
    product_no: str
    sales_rows: int
    inventory_rows: int
    demand_units: Decimal
    return_units: Decimal
    provenance: str = "OBS"

    @property
    def key(self) -> tuple[str, str]:
        return self.store, self.product_no

    @property
    def sources(self) -> tuple[str, ...]:
        return tuple(k for k, n in (("RAW_SALES", self.sales_rows), ("RAW_INVENTORY", self.inventory_rows)) if n)


@dataclass(frozen=True)
class AttributeValue:
    value: str
    source: str
    row_count: int
    first_source_record: int


@dataclass(frozen=True)
class Attribute:
    name: str
    observations: tuple[AttributeValue, ...]

    @property
    def values(self) -> tuple[str, ...]:
        return tuple(sorted({x.value for x in self.observations}))

    @property
    def requires_review(self) -> bool:
        return len(self.values) > 1


@dataclass(frozen=True)
class Entity:
    key: str
    attributes: tuple[Attribute, ...]
    provenance: str = "OBS"


@dataclass(frozen=True)
class Interval:
    fields: tuple[tuple[str, object], ...]

    def as_dict(self) -> dict:
        return dict(self.fields)

    @property
    def reference(self) -> tuple[str, int]:
        row = self.as_dict()
        return row["source_file"], row["source_record_number"]


@dataclass(frozen=True)
class Overlap:
    store: str
    product_no: str
    left: tuple[str, int]
    right: tuple[str, int]
    intersection_start: date
    intersection_end: date
    kind: str
    same_descriptors: bool
    different_quantities: bool


@dataclass(frozen=True)
class InventoryContracts:
    universe: tuple[Pair, ...]
    products: tuple[Entity, ...]
    stores: tuple[Entity, ...]
    intervals: tuple[Interval, ...]
    overlaps: tuple[Overlap, ...]
    negative_stock_records: tuple[tuple[str, int], ...]
    open_ended_records: tuple[tuple[str, int], ...]

    def summary(self) -> dict:
        return {
            "stage": "CP7-B3", "provenance": "OBS",
            "store_product_pairs": len(self.universe),
            "sales_pairs": sum(p.sales_rows > 0 for p in self.universe),
            "inventory_pairs": sum(p.inventory_rows > 0 for p in self.universe),
            "sales_only_pairs": sum(p.sales_rows > 0 and p.inventory_rows == 0 for p in self.universe),
            "inventory_only_pairs": sum(p.inventory_rows > 0 and p.sales_rows == 0 for p in self.universe),
            "both_source_pairs": sum(p.sales_rows > 0 and p.inventory_rows > 0 for p in self.universe),
            "sales_rows": sum(p.sales_rows for p in self.universe),
            "inventory_rows": len(self.intervals),
            "products": len(self.products), "stores": len(self.stores),
            "negative_stock_records": len(self.negative_stock_records),
            "open_ended_records": len(self.open_ended_records),
            "interior_overlap_pairs": sum(o.kind == "INTERIOR_OVERLAP" for o in self.overlaps),
            "boundary_contact_pairs": sum(o.kind == "BOUNDARY_CONTACT" for o in self.overlaps),
            "overlap_pairs_with_same_descriptors": sum(o.same_descriptors for o in self.overlaps),
            "overlap_pairs_with_different_quantities": sum(o.different_quantities for o in self.overlaps),
            "product_attribute_review_fields": sum(a.requires_review for e in self.products for a in e.attributes),
            "store_attribute_review_fields": sum(a.requires_review for e in self.stores for a in e.attributes),
            "classification": {
                "negative_stock_and_open_ends": "SOURCE_CHARACTERISTIC_PRESERVED",
                "overlaps_and_multiple_attributes": "REVIEW_REQUIRED_NOT_AUTOMATIC_ERROR",
                "invalid_schema": "REJECTED_BY_INGESTION",
            },
            "unresolved": ["interval end inclusion", "valid inventory partition/grain",
                           "attribute conflict resolution if encountered", "simulation entity eligibility",
                           "negative-stock treatment for future simulation", "opening balance derivation"],
        }


def profile_sources(sales: Iterable[Mapping], inventory: Iterable[Mapping],
                    movements: observed_movements.MovementResult) -> InventoryContracts:
    """Profile normalized streams; CP7-B2 movements enrich, never restrict, union.

    Caller must supply movements from the same RAW snapshot. Linkage verifies
    provenance, keys and contributing-row counts, but is not a replay of B2
    quantity logic. build_contracts additionally checks RAW hashes for changes.
    """
    counts = defaultdict(lambda: [0, 0])
    product_attrs = defaultdict(dict)
    store_attrs = defaultdict(dict)
    grouped = defaultdict(list)
    intervals, negatives, open_ends = [], [], []

    def capture(target, key, names, row):
        for name in names:
            if name not in row:
                continue  # Store Type is not in sales; no missing-value imputation.
            variants = target[key].setdefault(name, {})
            identity = (row[name], row["source_file"])
            count, first = variants.get(identity, (0, row["source_record_number"]))
            variants[identity] = (count + 1, min(first, row["source_record_number"]))

    sales_count = 0
    for index, stream in enumerate((sales, inventory)):
        for original in stream:
            row = dict(original)
            if row["provenance"] != "OBS":
                raise ContractError("Entity sources must have OBS provenance")
            key = row["store"], row["product_no"]
            counts[key][index] += 1
            capture(product_attrs, key[1], PRODUCT_ATTRIBUTES, row)
            capture(store_attrs, key[0], STORE_ATTRIBUTES, row)
            if index == 0:
                sales_count += 1
                continue
            interval = Interval(tuple(sorted(row.items())))
            intervals.append(interval)
            grouped[key].append(row)
            if row["quantity_on_hand"] < 0:
                negatives.append(interval.reference)
            if row["is_open_ended"]:
                open_ends.append(interval.reference)

    totals = defaultdict(lambda: [Decimal(0), Decimal(0)])
    contributing = defaultdict(int)
    for index, rows in enumerate((movements.demand, movements.returns)):
        seen = set()
        for row in rows:
            key = row.store, row.product_no
            if row.provenance != "OBS" or row.quantity <= 0 or row.source_row_count < 1:
                raise ContractError("Invalid observed movement provenance/quantity/count")
            if row.key in seen:
                raise ContractError("Duplicate movement grain")
            seen.add(row.key)
            if key not in counts or counts[key][0] == 0:
                raise ContractError("Movement entity is absent from RAW sales")
            totals[key][index] += row.quantity
            contributing[key] += row.source_row_count
    zero_rows = movements.zero_nonreturn_rows + movements.zero_return_rows
    if (movements.source_rows != sales_count or zero_rows < 0
            or sum(contributing.values()) + zero_rows != sales_count
            or any(n > counts[k][0] for k, n in contributing.items())):
        raise ContractError("Movement/source contributing-row reconciliation failed")

    overlaps = []
    for key, rows in sorted(grouped.items()):
        rows.sort(key=lambda r: (r["start_date"], r["end_date"], r["source_file"], r["source_record_number"]))
        active, endings = {}, []
        for serial, row in enumerate(rows):
            while endings and endings[0][0] < row["start_date"]:
                _, expired = heapq.heappop(endings)
                del active[expired]
            for previous in active.values():
                start = max(previous["start_date"], row["start_date"])
                end = min(previous["end_date"], row["end_date"])
                references = sorted((
                    (previous["source_file"], previous["source_record_number"]),
                    (row["source_file"], row["source_record_number"])))
                overlaps.append(Overlap(*key, *references, start, end,
                    "INTERIOR_OVERLAP" if start < end else "BOUNDARY_CONTACT",
                    all(previous[c] == row[c] for c in ("stock_status", "store_type", "sales_channel")),
                    previous["quantity_on_hand"] != row["quantity_on_hand"]))
            active[serial] = row
            heapq.heappush(endings, (row["end_date"], serial))

    def entities(attributes):
        return tuple(Entity(key, tuple(Attribute(name, tuple(
            AttributeValue(value, source, count, first)
            for (value, source), (count, first) in sorted(variants.items())))
            for name, variants in sorted(fields.items()))) for key, fields in sorted(attributes.items()))

    return InventoryContracts(
        tuple(Pair(*key, *value, *totals[key]) for key, value in sorted(counts.items())),
        entities(product_attrs), entities(store_attrs),
        tuple(sorted(intervals, key=lambda x: x.reference)),
        tuple(sorted(overlaps, key=lambda x: (x.store, x.product_no, x.left, x.right))),
        tuple(sorted(negatives)), tuple(sorted(open_ends)))


def build_contracts(root: Path | None = None,
                    movements: observed_movements.MovementResult | None = None) -> InventoryContracts:
    root = ingestion.project_root() if root is None else Path(root)
    paths = [ingestion.source_path(root, k) for k in ("sales", "inventory")]
    before = [ingestion.file_hash(p) for p in paths]
    if movements is None:
        movements = observed_movements.build_movements(root)
    result = profile_sources(ingestion.iter_sales(root), ingestion.iter_inventory(root), movements)
    if before != [ingestion.file_hash(p) for p in paths]:
        raise ContractError("RAW inputs changed during profiling; use a stable snapshot")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=ingestion.project_root())
    args = parser.parse_args()
    try:
        result = build_contracts(args.project_root)
    except (OSError, ingestion.SchemaError, observed_movements.MovementError, ContractError) as exc:
        parser.exit(2, f"Inventory/entity profiling failed: {exc}\n")
    print(json.dumps(result.summary(), sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
