"""CP7-B5: python -B -m unittest discover -s src/python -p test_observed_daily_model.py -v

Reference CSVs are test-only. No files/fixtures are written.
"""

import csv
import unittest
from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch

import ingestion
import inventory_entities as entities
import observed_movements as movements
import reference_dimensions as dimensions
import observed_daily_model as daily


def fixture():
    universe = (entities.Pair("S1", "P1", 2, 0, Decimal(2), Decimal(1)),)
    dims = dimensions.Dimensions((
        dimensions.Dimension("DimStore", ("Store",), (("S1",),), ("OBS",), ("fixture",)),
        dimensions.Dimension("DimProduct", ("Product No",), (("P1",),), ("OBS",), ("fixture",))), universe)
    move = movements.MovementResult(
        (movements.Movement(date(2026, 2, 1), "S1", "P1", Decimal(2), 1),),
        (movements.Movement(date(2026, 2, 2), "S1", "P1", Decimal(1), 1),), 3, 1, 0)
    return move, dims, daily.SourceCalendar(date(2026, 1, 31), date(2026, 2, 2), 3)


class DailyTests(unittest.TestCase):
    def test_return_only_and_empty_calendar_day(self):
        m, d, c = fixture()
        result = daily.assemble_daily_model(m, d, c)
        self.assertEqual(len(result.dates.rows), 3)
        self.assertEqual(len(result.daily), 2)
        self.assertEqual(result.daily[1].demand_qty, 0)
        self.assertEqual(result.daily[1].return_inflow_qty, 1)
        self.assertTrue(all(r.demand_provenance == r.return_provenance == "OBS" for r in result.daily))
        self.assertEqual(result.dates.rows[1][-1], "TRAINING_HISTORY")
        self.assertEqual(result.dates.rows[2][-1], "V2_EVALUATION_REPEATED_HOLDOUT")
        self.assertIs(result.universe, d.universe)
        self.assertFalse(hasattr(result.daily[0], "fulfilled_qty"))

    def test_calendar_leap_year_iso_week_and_zero_source_dates(self):
        rows = [{"transaction_date": x, "provenance": "OBS", "quantity_sold": Decimal(0)}
                for x in (date(2024, 2, 28), date(2024, 3, 1))]
        c = daily.source_calendar(iter(rows))
        m, d, _ = fixture()
        empty = movements.MovementResult((), (), 2, 2, 0)
        result = daily.assemble_daily_model(empty, d, c)
        self.assertEqual([r[0] for r in result.dates.rows], [date(2024, 2, 28), date(2024, 2, 29), date(2024, 3, 1)])
        self.assertEqual(result.daily, ())
        end = daily.assemble_daily_model(empty, d, daily.SourceCalendar(date(2020, 12, 31), date(2021, 1, 1), 2))
        self.assertEqual([r[7] for r in end.dates.rows], [53, 53])
        with self.assertRaises(daily.DailyModelError):
            daily.source_calendar([])

    def test_aggregate_skus_without_netting_and_deterministic_order(self):
        m, d, c = fixture()
        d = replace(d, tables=(d.tables[0], replace(d.tables[1], rows=(("P1",), ("P2",)))),
                    universe=d.universe + (entities.Pair("S1", "P2", 1, 0, Decimal(3), Decimal(0)),))
        extra = movements.Movement(date(2026, 2, 1), "S1", "P2", Decimal("3.25"), 1)
        m = replace(m, demand=m.demand + (extra,), source_rows=4)
        c = replace(c, source_rows=4)
        a = daily.assemble_daily_model(m, d, c)
        self.assertEqual(a.daily[0].demand_qty, Decimal("5.25"))
        self.assertEqual(a, daily.assemble_daily_model(replace(m, demand=tuple(reversed(m.demand))), d, c))

    def test_unmapped_out_of_range_duplicate_and_nonobs_fail(self):
        m, d, c = fixture()
        for bad in (replace(m.demand[0], store="UNKNOWN"), replace(m.demand[0], date=date(2026, 2, 3)),
                    replace(m.demand[0], provenance="SIM")):
            with self.assertRaises(daily.DailyModelError):
                daily.assemble_daily_model(replace(m, demand=(bad,)), d, c)
        with self.assertRaises(daily.DailyModelError):
            daily.assemble_daily_model(replace(m, demand=m.demand * 2), d, c)
        with self.assertRaises(daily.DailyModelError):
            daily.assemble_daily_model(m, d, replace(c, source_rows=4))

    def test_orchestration_reuses_supplied_outputs(self):
        m, d, c = fixture()
        with patch.object(movements, "build_movements", side_effect=AssertionError("rebuild")), \
             patch.object(dimensions, "build_dimensions", side_effect=AssertionError("rebuild")), \
             patch.object(ingestion, "iter_sales", side_effect=AssertionError("reread")), \
             patch.object(ingestion, "file_hash", return_value="stable"):
            self.assertEqual(daily.build_daily_model(movements=m, dimensions=d, calendar=c), daily.assemble_daily_model(m, d, c))


class ReferenceTests(unittest.TestCase):
    def test_calendar_every_attribute_daily_observed_fields_and_source_coverage(self):
        root = ingestion.project_root()
        m = movements.build_movements(root)
        contracts = entities.build_contracts(root, movements=m)
        d = dimensions.build_dimensions(root, contracts=contracts)
        calendar = daily.source_calendar(ingestion.iter_sales(root))
        result = daily.build_daily_model(root, movements=m, dimensions=d, calendar=calendar)
        with (root / "data/powerbi_model_v1/DimDate.csv").open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            self.assertEqual(tuple(reader.fieldnames), daily.DATE_COLUMNS)
            expected = {}
            for row in reader:
                values = tuple(date.fromisoformat(row[k]) if k in {"Date", "MonthStartDate"} else
                               int(row[k]) if k in {"Year", "MonthNumber", "ISOWeek"} else row[k] for k in daily.DATE_COLUMNS)
                self.assertNotIn(values[0], expected)
                expected[values[0]] = values
        self.assertEqual({r[0]: r for r in result.dates.rows}, expected)
        self.assertEqual(len(result.dates.rows), 328)
        with (root / "data/analytics_v1/analytics_store_daily_service_v1.csv").open(encoding="utf-8-sig", newline="") as stream:
            observed = {}
            for row in csv.DictReader(stream):
                key = date.fromisoformat(row["Date"]), row["Store"]
                self.assertNotIn(key, observed)
                observed[key] = (Decimal(row["DemandQty"]), Decimal(row["ReturnInflowQty"]))
        actual = {r.key: (r.demand_qty, r.return_inflow_qty) for r in result.daily}
        self.assertEqual(len(actual), len(result.daily))
        self.assertEqual(actual, observed)
        self.assertEqual(len(actual), 12706)
        self.assertEqual(sum(r.demand_qty for r in result.daily), 124542)
        self.assertEqual(sum(r.return_inflow_qty for r in result.daily), 7547)
        self.assertEqual(sum(r.demand_qty == 0 for r in result.daily), 28)
        holdout = [r for r in result.daily if date(2026, 2, 2) <= r.date <= date(2026, 4, 24)]
        self.assertEqual((sum(r.demand_qty for r in holdout), sum(r.return_inflow_qty for r in holdout)), (30000, 1738))
        # Independent RAW checks include zero transactions and each observed day.
        with ingestion.source_path(root, "sales").open(encoding="utf-8-sig", newline="") as stream:
            raw = list(csv.DictReader(stream))
        dates = {date.fromisoformat(r["Transaction Date"]) for r in raw}
        self.assertEqual((calendar.start, calendar.end, calendar.source_rows), (min(dates), max(dates), len(raw)))
        self.assertTrue(dates <= set(expected))
        active_keys = {(date.fromisoformat(r["Transaction Date"]), r["Store"]) for r in raw if Decimal(r["Qty Sold"]) != 0}
        self.assertEqual(set(actual), active_keys)
        self.assertEqual(len(result.universe), 63556)
        self.assertEqual(result, daily.build_daily_model(root, movements=m, dimensions=d, calendar=calendar))
        print("B5 reconciliation: 328 dates x 9 attributes and 12,706 daily keys; zero mismatches. Returns-only rows: 28.")


if __name__ == "__main__":
    unittest.main()
