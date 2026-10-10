"""CP7-B5: calendar and OBS Date x Store flows; Python 3.10+, no file writes.

Calendar bounds are inclusive min/max RAW sales transaction dates (including
zero movements), not inventory's 9999-12-31 sentinel or simulation output dates.
English Gregorian month labels and ISO week numbers are locale independent.
DevelopmentPhase is governance metadata, not OBS: the documented training end
2026-02-01 / evaluation start 2026-02-02 is an explicit configurable rule.
Evidence: historical CP5A model contract and integrated V2 source_period.
Neither downstream file is read by production. The holdout is reused development
evidence, not independent certification. No fulfillment/shortage/rate is emitted.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

if __package__:
    from . import ingestion, observed_movements, inventory_entities, reference_dimensions
else:
    import ingestion
    import observed_movements
    import inventory_entities
    import reference_dimensions

EVALUATION_START = date(2026, 2, 2)
MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December")
DATE_COLUMNS = ("Date", "Year", "Quarter", "MonthNumber", "MonthName", "YearMonth", "MonthStartDate", "ISOWeek", "DevelopmentPhase")


class DailyModelError(ValueError):
    pass


@dataclass(frozen=True)
class SourceCalendar:
    start: date
    end: date
    source_rows: int


def source_calendar(rows) -> SourceCalendar:
    """Consume normalized B1 sales rows; retain zero-quantity date coverage."""
    start = end = None
    count = 0
    for row in rows:
        if row["provenance"] != "OBS":
            raise DailyModelError("Calendar bounds require OBS RAW sales")
        current = row["transaction_date"]
        start = current if start is None else min(start, current)
        end = current if end is None else max(end, current)
        count += 1
    if count == 0:
        raise DailyModelError("Cannot derive calendar bounds from empty RAW sales")
    return SourceCalendar(start, end, count)


@dataclass(frozen=True)
class DailyRow:
    date: date
    store: str
    demand_qty: Decimal
    return_inflow_qty: Decimal
    demand_provenance: str = "OBS"
    return_provenance: str = "OBS"

    @property
    def key(self):
        return self.date, self.store


@dataclass(frozen=True)
class DailyModel:
    dates: reference_dimensions.Dimension
    daily: tuple[DailyRow, ...]
    calendar: SourceCalendar
    universe: tuple[inventory_entities.Pair, ...]
    zero_nonreturn_rows: int
    zero_return_rows: int

    def summary(self):
        return {
            "stage": "CP7-B5", "date_rows": len(self.dates.rows),
            "start": self.calendar.start.isoformat(), "end": self.calendar.end.isoformat(),
            "source_rows": self.calendar.source_rows, "daily_rows": len(self.daily),
            "demand_units": str(sum((r.demand_qty for r in self.daily), Decimal(0))),
            "return_units": str(sum((r.return_inflow_qty for r in self.daily), Decimal(0))),
            "returns_only_daily_rows": sum(r.demand_qty == 0 and r.return_inflow_qty > 0 for r in self.daily),
            "zero_nonreturn_source_rows": self.zero_nonreturn_rows,
            "zero_return_source_rows": self.zero_return_rows,
            "source_universe_pairs": len(self.universe),
            "scope": "OBS demand/returns only; calendar attributes derived; DevelopmentPhase is governance metadata",
        }


def assemble_daily_model(movements, dimensions, calendar: SourceCalendar,
                         evaluation_start: date = EVALUATION_START) -> DailyModel:
    """Reuse B2 and B4 outputs; fail on unmapped/out-of-range input, never drop."""
    if calendar.end < calendar.start or calendar.source_rows < 1:
        raise DailyModelError("Invalid RAW calendar contract")
    tables = {t.name: t for t in dimensions.tables}
    if len(tables) != len(dimensions.tables):
        raise DailyModelError("Duplicate dimension names")
    def keys(name, column):
        if name not in tables or column not in tables[name].columns:
            raise DailyModelError(f"Missing {name}.{column}")
        table = tables[name]
        index = table.columns.index(column)
        values = [r[index] for r in table.rows]
        if len(set(values)) != len(values):
            raise DailyModelError(f"Duplicate keys in {name}")
        return set(values)
    stores, products = keys("DimStore", "Store"), keys("DimProduct", "Product No")
    pairs = {p.key for p in dimensions.universe}
    if len(pairs) != len(dimensions.universe):
        raise DailyModelError("Duplicate universe pairs")
    totals = defaultdict(lambda: [Decimal(0), Decimal(0)])
    contributing = 0
    for column, records in enumerate((movements.demand, movements.returns)):
        seen = set()
        for row in records:
            if row.key in seen:
                raise DailyModelError("Duplicate B2 movement grain")
            seen.add(row.key)
            if row.provenance != "OBS" or row.quantity <= 0 or row.source_row_count < 1:
                raise DailyModelError("Invalid OBS movement contract")
            if row.store not in stores or row.product_no not in products or (row.store, row.product_no) not in pairs:
                raise DailyModelError(f"Unmatched movement entity: {row.key}")
            if not calendar.start <= row.date <= calendar.end:
                raise DailyModelError(f"Movement outside RAW date range: {row.key}")
            totals[(row.date, row.store)][column] += row.quantity
            contributing += row.source_row_count
    if (movements.source_rows != calendar.source_rows or movements.zero_nonreturn_rows < 0
            or movements.zero_return_rows < 0 or contributing + movements.zero_nonreturn_rows
            + movements.zero_return_rows != calendar.source_rows):
        raise DailyModelError("RAW/B2 contributing-row coverage mismatch")
    dates = []
    # Integer offsets avoid overflow after a date.max final row.
    for offset in range((calendar.end - calendar.start).days + 1):
        current = calendar.start + timedelta(days=offset)
        dates.append((current, current.year, f"Q{(current.month - 1) // 3 + 1}",
                      current.month, MONTHS[current.month - 1], f"{current.year:04d}-{current.month:02d}",
                      current.replace(day=1), current.isocalendar().week,
                      "TRAINING_HISTORY" if current < evaluation_start else "V2_EVALUATION_REPEATED_HOLDOUT"))
    dimension = reference_dimensions.Dimension("DimDate", DATE_COLUMNS, tuple(dates),
        ("DERIVED_FROM_OBS_RANGE",) * 8 + ("GOVERNANCE",),
        ("RAW sales transaction range; Gregorian calendar/ISO week",) * 8 +
        (f"Documented development split, evaluation starts {evaluation_start.isoformat()}",))
    daily = tuple(DailyRow(*key, *values) for key, values in sorted(totals.items()))
    return DailyModel(dimension, daily, calendar, dimensions.universe,
                      movements.zero_nonreturn_rows, movements.zero_return_rows)


def build_daily_model(root: Path | None = None, *, movements=None, dimensions=None,
                      calendar: SourceCalendar | None = None, evaluation_start=EVALUATION_START):
    """Portable orchestration; supply matching upstream objects to avoid rebuilds."""
    root = ingestion.project_root() if root is None else Path(root)
    source = ingestion.source_path(root, "sales")
    before = ingestion.file_hash(source)
    if movements is None:
        movements = observed_movements.build_movements(root)
    if dimensions is None:
        contracts = inventory_entities.build_contracts(root, movements=movements)
        dimensions = reference_dimensions.build_dimensions(root, contracts=contracts)
    if calendar is None:
        calendar = source_calendar(ingestion.iter_sales(root))
    result = assemble_daily_model(movements, dimensions, calendar, evaluation_start)
    if before != ingestion.file_hash(source):
        raise DailyModelError("RAW sales changed during model construction")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=ingestion.project_root())
    args = parser.parse_args()
    try:
        result = build_daily_model(args.project_root)
    except (OSError, ValueError) as exc:
        parser.exit(2, f"Observed daily model failed: {exc}\n")
    print(json.dumps(result.summary(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
