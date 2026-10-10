"""CP7-B2: observed Date x Store x Product movements, standard library only.

Python 3.10+. Run: python -B src/python/observed_movements.py [--project-root PATH]
Or call build_movements(root) / aggregate_movements(ingestion.iter_sales(root)).
Returns immutable, key-sorted demand and return tuples in memory; writes no files.
Production reads only RAW sales via ingestion. Reference files are test-only.

Recovered rule: positive non-return quantities are gross observed demand;
negative return quantities become positive observed inflow, never netted off
demand. Zero quantities create no movement key and are counted explicitly.
New fail-closed boundary: positive returns / negative non-return quantities are
rejected with source context rather than silently taking absolute values or
discarding corrections. This matches current RAW conventions; future correction
semantics need a separately reviewed contract. Repeated RAW rows are additive.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Iterable, Mapping

if __package__:
    from . import ingestion
else:
    import ingestion


class MovementError(ValueError):
    """A normalized row violates the observed movement business contract."""


@dataclass(frozen=True)
class Movement:
    date: date
    store: str
    product_no: str
    quantity: Decimal
    source_row_count: int
    provenance: str = "OBS"

    @property
    def key(self) -> tuple[date, str, str]:
        return self.date, self.store, self.product_no


@dataclass(frozen=True)
class MovementResult:
    demand: tuple[Movement, ...]
    returns: tuple[Movement, ...]
    source_rows: int
    zero_nonreturn_rows: int
    zero_return_rows: int

    def summary(self) -> dict:
        return {
            "stage": "CP7-B2", "provenance": "OBS",
            "grain": ["date", "store", "product_no"],
            "source_rows": self.source_rows,
            "zero_nonreturn_rows": self.zero_nonreturn_rows,
            "zero_return_rows": self.zero_return_rows,
            "demand_keys": len(self.demand),
            "demand_units": str(sum((r.quantity for r in self.demand), Decimal(0))),
            "return_keys": len(self.returns),
            "return_units": str(sum((r.quantity for r in self.returns), Decimal(0))),
        }


def aggregate_movements(rows: Iterable[Mapping]) -> MovementResult:
    """Consume normalized ingestion rows fully; no parsing/validation duplication.

    Input contract is ingestion.iter_sales(). This function adds only movement
    provenance/sign checks, retains duplicate rows and never mutates its input.
    No partial result is returned if ingestion or transformation fails.
    """
    demand: dict[tuple, tuple[Decimal, int]] = {}
    returns: dict[tuple, tuple[Decimal, int]] = {}
    source_rows = zero_nonreturn = zero_return = 0
    for row in rows:
        source_rows += 1
        context = f"{row['source_file']}: record {row['source_record_number']}"
        if row["provenance"] != "OBS":
            raise MovementError(f"{context}: expected OBS provenance")
        quantity = row["quantity_sold"]
        is_return = row["is_return"]
        if (is_return and quantity > 0) or (not is_return and quantity < 0):
            raise MovementError(f"{context}: quantity sign contradicts RAW return convention")
        if quantity == 0:
            if is_return:
                zero_return += 1
            else:
                zero_nonreturn += 1
            continue
        key = (row["transaction_date"], row["store"], row["product_no"])
        target = returns if is_return else demand
        units = -quantity if is_return else quantity
        previous, count = target.get(key, (Decimal(0), 0))
        target[key] = previous + units, count + 1

    def ordered(values: dict) -> tuple[Movement, ...]:
        return tuple(Movement(*key, units, count) for key, (units, count) in sorted(values.items()))

    return MovementResult(ordered(demand), ordered(returns), source_rows, zero_nonreturn, zero_return)


def build_movements(root: Path | None = None) -> MovementResult:
    """Portable orchestration entry point; only RAW sales is needed.

    Before/after hashes detect ordinary concurrent edits, not transactional locks.
    No inventory or reference dataset is needed for this stage.
    """
    root = ingestion.project_root() if root is None else Path(root)
    source = ingestion.source_path(root, "sales")
    before = ingestion.file_hash(source)
    result = aggregate_movements(ingestion.iter_sales(root))
    if ingestion.file_hash(source) != before:
        raise MovementError("RAW sales changed during transformation; retry with stable input")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=ingestion.project_root())
    args = parser.parse_args()
    try:
        result = build_movements(args.project_root)
    except (OSError, ingestion.SchemaError, MovementError) as exc:
        parser.exit(2, f"Observed movement transformation failed: {exc}\n")
    print(json.dumps(result.summary(), sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
