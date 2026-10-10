"""CP7-B1: source-row preserving ingestion, not inventory simulation.

Run with Python 3.10+: python -B src/python/ingestion.py [--project-root PATH]
Uses only the standard library; prints deterministic diagnostics to stdout.
No files are written. iter_sales/iter_inventory expose normalized typed rows.

Recovered evidence: current RAW headers; signed customer returns; zero-unit
movements; negative observed stock; 9999-12-31 interval ends. Existing governed
contracts select positive non-return demand and positive return inflow later.
New explicit ingestion choices: snake_case names, surrounding text whitespace
trimmed, empty return reason -> None, exact header set (order independent),
strict ISO dates and finite Decimal values. No deduplication, aggregation,
AsOf clipping, imputation, inventory repair, or dimension assignment occurs.
No raw row-level business key is assumed: source record ordinal preserves
identity, including repeated source rows. Output order is source order.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Iterator, TextIO


SALES_FILE = "retail_sales_ml_apl.csv"
INVENTORY_FILE = "retail_inventory_ml_apl.csv"
# Mapping values define the normalization contract; no inferred header aliases.
SALES_COLUMNS = {
    "Transaction Date": "transaction_date", "Sales Type": "sales_type",
    "Is Return": "is_return", "Reason of Return": "reason_of_return",
    "Supplier": "supplier", "Product No": "product_no",
    "Product Description": "product_description", "Product Division": "product_division",
    "Product Category": "product_category", "Product Subcategory": "product_subcategory",
    "Product Segment": "product_segment", "Store": "store", "Sales Channel": "sales_channel",
    "Qty Sold": "quantity_sold", "Sales Amount": "sales_amount", "Cogs": "cogs",
    "Number of Transactions": "transaction_count",
}
INVENTORY_COLUMNS = {
    "Start Date": "start_date", "End Date": "end_date", "Stock Status": "stock_status",
    "Supplier": "supplier", "Product No": "product_no",
    "Product Description": "product_description", "Product Division": "product_division",
    "Product Category": "product_category", "Product Subcategory": "product_subcategory",
    "Product Segment": "product_segment", "Store": "store", "Store Type": "store_type",
    "Sales Channel": "sales_channel", "Qty on hand": "quantity_on_hand",
    "Stocks Selling Amount": "stocks_selling_amount", "Cost of Stocks": "cost_of_stocks",
    "Stock Unit Selling Price": "stock_unit_selling_price",
    "Stock Unit Cost Price": "stock_unit_cost_price",
}
DECIMAL_FIELDS = {
    "quantity_sold", "sales_amount", "cogs", "quantity_on_hand",
    "stocks_selling_amount", "cost_of_stocks", "stock_unit_selling_price",
    "stock_unit_cost_price",
}
DATE_FIELDS = {"transaction_date", "start_date", "end_date"}
DECIMAL_PATTERN = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)\Z")
DATE_PATTERN = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}\Z")


class SchemaError(ValueError):
    """A malformed input with filename, logical record and field context."""


def normalize_row(values: dict[str, str], kind: str, source: str, record: int) -> dict:
    """Normalize a schema-checked source record without changing its grain."""
    if kind not in {"sales", "inventory"}:
        raise ValueError(f"unsupported input kind: {kind}")
    mapping = SALES_COLUMNS if kind == "sales" else INVENTORY_COLUMNS
    row = {"source_file": source, "source_record_number": record, "provenance": "OBS"}
    for original, normalized in mapping.items():
        value = values[original].strip()
        try:
            if not value:
                if normalized == "reason_of_return":
                    row[normalized] = None
                    continue
                raise ValueError("required value is blank")
            if normalized in DATE_FIELDS:
                if not DATE_PATTERN.fullmatch(value):
                    raise ValueError("expected YYYY-MM-DD")
                parsed = date.fromisoformat(value)
                if parsed == date.max and normalized != "end_date":
                    raise ValueError("open-ended sentinel only allowed in End Date")
                row[normalized] = parsed
            elif normalized in DECIMAL_FIELDS or normalized == "transaction_count":
                if not DECIMAL_PATTERN.fullmatch(value):
                    raise ValueError("expected a finite decimal without separators or exponent")
                number = Decimal(value)
                if not number.is_finite():
                    raise ValueError("nonfinite number")
                if normalized == "transaction_count":
                    if number < 0 or number != number.to_integral_value():
                        raise ValueError("expected nonnegative integer count")
                    row[normalized] = int(number)
                else:
                    row[normalized] = number
            elif normalized == "is_return":
                if value not in {"0", "1"}:
                    raise ValueError("expected return flag 0 or 1")
                row[normalized] = value == "1"
            else:
                row[normalized] = value
        except (ValueError, InvalidOperation) as exc:
            raise SchemaError(f"{source}: record {record}, {original}: {exc}") from exc
    if kind == "inventory":
        if row["end_date"] < row["start_date"]:
            raise SchemaError(f"{source}: record {record}: End Date precedes Start Date")
        row["is_open_ended"] = row["end_date"] == date.max
    # Preserve quantities exactly; report sign anomalies instead of repairing
    # or asserting a business rule not proven by original source code.
    return row


def read_rows(stream: TextIO, kind: str, source: str) -> Iterator[dict]:
    """Validate UTF-8 CSV content; record numbers count CSV records, not lines."""
    if kind not in {"sales", "inventory"}:
        raise ValueError(f"unsupported input kind: {kind}")
    mapping = SALES_COLUMNS if kind == "sales" else INVENTORY_COLUMNS
    reader = csv.reader(stream, strict=True)
    record = 1
    try:
        header = next(reader, None)
        if header is None:
            raise SchemaError(f"{source}: empty file")
        if len(header) != len(set(header)):
            raise SchemaError(f"{source}: duplicate CSV header")
        missing, unexpected = set(mapping) - set(header), set(header) - set(mapping)
        if missing or unexpected:
            raise SchemaError(f"{source}: schema mismatch; missing={sorted(missing)}, unexpected={sorted(unexpected)}")
        count = 0
        for record, values in enumerate(reader, 2):
            if len(values) != len(header):
                raise SchemaError(f"{source}: record {record}: expected {len(header)} fields, got {len(values)}")
            count += 1
            yield normalize_row(dict(zip(header, values)), kind, source, record)
        if not count:
            raise SchemaError(f"{source}: header without data rows")
    except (csv.Error, UnicodeError) as exc:
        raise SchemaError(f"{source}: near record {record}: invalid CSV/UTF-8: {exc}") from exc


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def source_path(root: Path, kind: str) -> Path:
    if kind not in {"sales", "inventory"}:
        raise ValueError(f"unsupported input kind: {kind}")
    return Path(root) / "data" / "raw" / (SALES_FILE if kind == "sales" else INVENTORY_FILE)


def iter_source(root: Path, kind: str) -> Iterator[dict]:
    path = source_path(root, kind)
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        yield from read_rows(stream, kind, f"data/raw/{path.name}")


def iter_sales(root: Path | None = None) -> Iterator[dict]:
    return iter_source(project_root() if root is None else root, "sales")


def iter_inventory(root: Path | None = None) -> Iterator[dict]:
    return iter_source(project_root() if root is None else root, "inventory")


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def summary(root: Path) -> dict:
    """Validate both sources completely before returning a diagnostic summary.

    Hash before/after reading detects ordinary concurrent input changes. This
    is not a transactional file lock. No generated dataset is persisted.
    """
    result = {
        "stage": "CP7-B1", "normalization_contract": 1,
        "diagnostic_scope": "Column sums are ingestion integrity checks, not AsOf inventory, valuation or business KPIs.",
        "sources": {},
    }
    for kind in ("sales", "inventory"):
        path = source_path(root, kind)
        before = file_hash(path)
        info = {"source_file": f"data/raw/{path.name}", "sha256": before, "rows": 0}
        totals: dict[str, Decimal] = {}
        minimum = maximum = None
        counters: dict[str, int] = {}
        for row in iter_source(root, kind):
            info["rows"] += 1
            current = row["transaction_date" if kind == "sales" else "start_date"]
            minimum = current if minimum is None else min(minimum, current)
            maximum = current if maximum is None else max(maximum, current)
            for field in sorted(DECIMAL_FIELDS & row.keys()):
                totals[field] = totals.get(field, Decimal(0)) + row[field]
            if kind == "sales":
                flags = {
                    "return_rows": row["is_return"],
                    "zero_quantity_rows": row["quantity_sold"] == 0,
                    "missing_return_reason_rows": row["reason_of_return"] is None,
                    "return_positive_quantity_rows": row["is_return"] and row["quantity_sold"] > 0,
                    "nonreturn_negative_quantity_rows": not row["is_return"] and row["quantity_sold"] < 0,
                }
            else:
                flags = {"negative_on_hand_rows": row["quantity_on_hand"] < 0, "open_ended_rows": row["is_open_ended"]}
            for name, flag in flags.items():
                counters[name] = counters.get(name, 0) + int(flag)
        if file_hash(path) != before:
            raise SchemaError(f"{path.name}: source changed while reading; retry on stable inputs")
        info.update(date_min=minimum.isoformat(), date_max=maximum.isoformat(),
                    numeric_column_sums_for_integrity={k: str(v) for k, v in sorted(totals.items())}, counters=counters)
        result["sources"][kind] = info
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=project_root())
    args = parser.parse_args()
    try:
        result = summary(args.project_root)
    except (OSError, SchemaError) as exc:
        parser.exit(2, f"Ingestion failed: {exc}\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
