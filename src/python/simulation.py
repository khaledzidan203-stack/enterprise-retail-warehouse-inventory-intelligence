"""NEW_REPLAY_V1: explicit development scenario, not recovered historical V2.

No integrated/analytics input is read. See docs/methodology.md for differences.
All physical units must be integral. Event ordering and tie-breaking are fixed.
"""
from __future__ import annotations
import csv
import hashlib
import json
import math
from bisect import bisect_left
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

VERSION = "NEW_REPLAY_V1"
STORE_COLUMNS = "StateDate,Store,Product No,DistributionCenter,ABCClass,EndOnHandQty,EndInTransitQty,EndOpenRequestQty,ActiveAssortmentFlag,FirstPositiveDemandDate,LastPositiveDemandDate,FullHistoryGrossDemandQty,DaysSinceLastPositiveDemand,NeverObservedPositiveDemandFlag,AsOfDate,FullHistoryCustomerReturnQty,TrailingGrossUnits28,CoverageDays28,ZeroVelocityFlag28,TrailingGrossUnits56,CoverageDays56,ZeroVelocityFlag56,TrailingGrossUnits84,CoverageDays84,ZeroVelocityFlag84,InventoryProvenance,DemandProvenance,ReturnProvenance,DecisionStatus,PolicyApprovalStatus".split(",")
DC_COLUMNS = "StateDate,DistributionCenter,Product No,ABCClass,Supplier,EndOnHandQty,EndOnOrderQty,EndStoreBacklogQty,NetInventoryPosition,ReorderPointQty,TargetStockQty,ReorderPointQty_FrozenPolicy,TargetStockQty_FrozenPolicy,NetPositionRecomputedQty,NetPositionMinusFrozenTargetQty,NetPositionMinusFrozenROPQty,AboveFrozenSimulationTargetFlag,BelowFrozenSimulationROPFlag,AsOfDate,Provenance,PolicyStatus".split(",")
DAILY_COLUMNS = "Date,Store,DemandQty,FulfilledQty,ShortageQty,ReturnInflowQty,UnitServiceRate,DevelopmentPhase,DemandProvenance,ReturnProvenance".split(",")
SUPPLIER_COLUMNS = "Supplier,DistributionCenter,DistinctPOHeaders,POLines,OrderedQty,ReceivedQty,CancelledQty,OpenQty,ReceivedToOrderedRatio,Provenance,MeasurementBoundary".split(",")

def integer(value):
    x = Decimal(str(value))
    if not x.is_finite() or x != x.to_integral_value():
        raise ValueError(f"Physical simulation requires integral finite units: {value}")
    return int(x)

def reference(path, keys, required):
    with Path(path).open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames or len(reader.fieldnames) != len(set(reader.fieldnames)) or not set(keys + required) <= set(reader.fieldnames):
            raise ValueError(f"Invalid input schema: {path.name}")
        result = {}
        for row in reader:
            if None in row or any(row[k] is None or not row[k].strip() for k in keys + required):
                raise ValueError(f"Blank/ragged input row: {path.name}")
            key = tuple(row[k] for k in keys)
            if key in result:
                raise ValueError(f"Duplicate input key: {path.name}: {key}")
            result[key] = row
    if not result:
        raise ValueError(f"Empty input: {path.name}")
    return result

def fraction(seed, identity):
    return int.from_bytes(hashlib.sha256(f"{seed}:{identity}".encode()).digest()[:8], "big") / 2**64

def rolling_quantile(history, today, lookback, window, quantile):
    # Nearest-rank empirical quantile, including zero calendar-day observations.
    start = max(0, today - lookback + 1)
    sums = [0] * (today - start + 1)
    for day, quantity in reversed(history):
        if day < start - window + 1:
            break
        for end in range(max(start, day), min(today, day + window - 1) + 1):
            sums[end - start] += quantity
    sums.sort()
    return sums[max(0, math.ceil(quantile * len(sums)) - 1)]

def replay(contracts, movements, dimensions, daily, reference_dir, policy_file, seed=20261007):
    start, end = daily.calendar.start, daily.calendar.end
    days = (end - start).days + 1
    cfg = json.loads(Path(policy_file).read_text(encoding="utf-8-sig"))
    review = cfg["review"]
    lookback, cadence, transfer_lead = (integer(review[k]) for k in ("demand_lookback_days", "recalibration_days", "dc_to_store_lead_time_days"))
    if min(lookback, cadence, transfer_lead) < 1:
        raise ValueError("Review/transfer intervals must be positive")
    mature = cfg["mature_replenishment"]
    quantiles = mature["abc_service_quantiles"]
    if any(not 0 < float(q) <= 1 for q in quantiles.values()):
        raise ValueError("Invalid empirical service quantile")
    windows = [integer(mature[k]["demand_window_days"]) for k in ("reorder_point", "target_stock")]
    minima = [integer(mature[k]["minimum_units"]) for k in ("reorder_point", "target_stock")]
    if min(windows) < 1 or min(minima) < 0:
        raise ValueError("Invalid store policy window/minimum")
    tables = {t.name: list(t.records()) for t in dimensions.tables}
    stores = {r["Store"]: r for r in tables["DimStore"]}
    products = {r["Product No"]: r for r in tables["DimProduct"]}
    for p in products.values():
        if p["ABCClass"] not in quantiles:
            raise ValueError("Missing ABC quantile")
    policy = reference(Path(reference_dir)/"dc_inventory_policy_v2.csv", ["DistributionCenter", "Product No"],
        ["Supplier", "ReorderPointQty", "TargetStockQty", "CasePack", "MOQ", "BaseLeadTimeDays", "ReviewCycleDays", "OTIFTarget", "FillRateTarget"])
    opening = reference(Path(reference_dir)/"dc_opening_inventory_v2.csv", ["DistributionCenter", "Product No"], ["OpeningInventoryQty", "AsOfDate"])
    if set(policy) != set(opening):
        raise ValueError("DC opening/policy key mismatch")
    dc_names = {r["DistributionCenter"] for r in tables["DimDistributionCenter"]}
    for (dc, sku), p in policy.items():
        if dc not in dc_names or sku not in products or p["Supplier"] != products[sku]["Supplier"]:
            raise ValueError("DC policy dimension mismatch")
        for name in ("ReorderPointQty", "TargetStockQty", "CasePack", "MOQ", "BaseLeadTimeDays", "ReviewCycleDays"):
            p[name] = integer(p[name])
        if min(p[k] for k in ("CasePack", "MOQ", "BaseLeadTimeDays", "ReviewCycleDays")) < 1 or p["ReorderPointQty"] < 0 or p["TargetStockQty"] < p["ReorderPointQty"]:
            raise ValueError("Invalid DC policy quantity/lead time")
        for name in ("OTIFTarget", "FillRateTarget"):
            p[name] = float(p[name])
            if not 0 <= p[name] <= 1:
                raise ValueError("Invalid supplier probability")
    pairs = sorted(p.key for p in contracts.universe)
    location = {key: (stores[key[0]]["DistributionCenter"], key[1]) for key in pairs}
    if not set(location.values()) <= set(policy):
        raise ValueError("Store products missing DC opening/policy slots")
    stock = {k: 0 for k in pairs}
    selected = set()
    negative_opening = 0
    for interval in contracts.intervals:
        row = interval.as_dict()
        if row["start_date"] <= start <= row["end_date"]:
            key = row["store"], row["product_no"]
            if key in selected:
                raise ValueError("Ambiguous overlapping opening inventory intervals; no automatic choice")
            selected.add(key)
            amount = integer(row["quantity_on_hand"])
            negative_opening += amount < 0
            stock[key] = max(0, amount)  # Explicit NEW scenario assumption; RAW remains untouched.
    store_opening = stock.copy()
    dc_stock = {}
    for key, row in opening.items():
        if date.fromisoformat(row["AsOfDate"]) != start:
            raise ValueError("DC opening fixture must match source start date")
        dc_stock[key] = integer(row["OpeningInventoryQty"])
        if dc_stock[key] < 0:
            raise ValueError("Negative supplied DC opening")
    dc_initial = dc_stock.copy()
    transit, backlog, onorder = defaultdict(int), defaultdict(int), defaultdict(int)
    received_store, shipped_store, returned, fulfilled = (defaultdict(int) for _ in range(4))
    requested, received_dc, shipped_dc, ordered_dc, cancelled_dc = (defaultdict(int) for _ in range(5))
    history = defaultdict(list)
    demand_by_day, returns_by_day = defaultdict(list), defaultdict(list)
    for r in movements.demand:
        demand_by_day[(r.date-start).days].append(((r.store, r.product_no), integer(r.quantity)))
    for r in movements.returns:
        returns_by_day[(r.date-start).days].append(((r.store, r.product_no), integer(r.quantity)))
    arrivals, receipts = defaultdict(list), defaultdict(list)
    active, thresholds = set(), {}
    last_store, last_dc = {k: start for k in pairs}, {k: start for k in policy}
    events, lines = [], []
    service = defaultdict(lambda: [0, 0])
    def event(day, kind, key, amount, reference_id="", provenance="SIM"):
        events.append(((start+timedelta(days=day)).isoformat(), kind, key[0], key[1], amount, reference_id, provenance))
    for day in range(days):
        current = start + timedelta(days=day)
        # 1. Supplier receipts/cancellations, then 2. transfer arrivals.
        for line_id, attempt in sorted(receipts.pop(day, [])):
            line = lines[line_id]
            key = line["DistributionCenter"], line["Product No"]
            p = policy[key]
            remaining = line["OpenQty"]
            qty = remaining if fraction(seed, f"{line_id}:fill:{attempt}") <= p["FillRateTarget"] else math.floor(remaining*p["FillRateTarget"])
            line["ReceivedQty"] += qty
            line["OpenQty"] -= qty
            onorder[key] -= qty
            dc_stock[key] += qty
            received_dc[key] += qty
            last_dc[key] = current
            event(day, "SUPPLIER_RECEIPT", key, qty, line["POLineID"])
            if line["OpenQty"] and attempt == 1:
                receipts[day+2].append((line_id, 2))
            elif line["OpenQty"]:
                cancelled = line["OpenQty"]
                line["CancelledQty"] += cancelled
                line["OpenQty"] = 0
                onorder[key] -= cancelled
                cancelled_dc[key] += cancelled
                event(day, "SUPPLIER_CANCEL", key, cancelled, line["POLineID"])
        for key, qty in sorted(arrivals.pop(day, [])):
            stock[key] += qty
            transit[key] -= qty
            received_store[key] += qty
            last_store[key] = current
            event(day, "STORE_ARRIVAL", key, qty)
        # 3. Observed return inflow assumed sellable before 4. outbound demand.
        for key, qty in sorted(returns_by_day.get(day, [])):
            stock[key] += qty
            returned[key] += qty
            last_store[key] = current
            event(day, "CUSTOMER_RETURN", key, qty, provenance="OBS")
        for key, qty in sorted(demand_by_day.get(day, [])):
            got = min(stock[key], qty)
            stock[key] -= got
            fulfilled[key] += got
            service[(current, key[0])][0] += got
            service[(current, key[0])][1] += qty-got
            history[key].append((day, qty))
            active.add(key)
            last_store[key] = current
            event(day, "GROSS_DEMAND", key, qty, provenance="OBS")
            event(day, "STORE_FULFILL", key, got)
        # 5. Past/now-observed demand calibration; no oracle launch calendar.
        for key in sorted(active):
            if key not in thresholds or day % cadence == 0:
                q = float(quantiles[products[key[1]]["ABCClass"]])
                rop, target = [max(minimum, rolling_quantile(history[key], day, lookback, window, q)) for window, minimum in zip(windows, minima)]
                thresholds[key] = rop, max(rop, target)
            rop, target = thresholds[key]
            position = stock[key]+transit[key]
            if position <= rop:
                qty = max(0, target-position-backlog[key])
                backlog[key] += qty
                requested[key] += qty
                if qty:
                    event(day, "STORE_REQUEST", key, qty)
                    last_store[key] = current
            # Explicit lexicographic FIFO-by-key allocation, not historical proportional allocation.
            slot = location[key]
            qty = min(backlog[key], dc_stock[slot])
            if qty:
                dc_stock[slot] -= qty
                backlog[key] -= qty
                transit[key] += qty
                shipped_store[key] += qty
                shipped_dc[slot] += qty
                arrivals[day+transfer_lead].append((key, qty))
                last_store[key] = last_dc[slot] = current
                event(day, "TRANSFER_SHIP", key, qty, slot[0])
        dc_backlog = defaultdict(int)
        for key, qty in backlog.items():
            dc_backlog[location[key]] += qty
        # 6. Frozen supplied DC policy on fixed review cadence, orders received later.
        headers = {}
        for key, p in sorted(policy.items()):
            if day % p["ReviewCycleDays"]:
                continue
            position = dc_stock[key]+onorder[key]-dc_backlog[key]
            if position > p["ReorderPointQty"]:
                continue
            need = max(0, p["TargetStockQty"]-position)
            if not need:
                continue
            qty = math.ceil(max(need, p["MOQ"])/p["CasePack"])*p["CasePack"]
            group = p["Supplier"], key[0]
            po = headers.setdefault(group, f"PO-{day:04d}-{len(headers)+1:04d}")
            line_id = len(lines)
            line = dict(POLineID=f"POL-{line_id+1:08d}", PONumber=po, PODate=current.isoformat(),
                        Supplier=p["Supplier"], DistributionCenter=key[0], **{"Product No": key[1]},
                        OrderedQty=qty, ReceivedQty=0, CancelledQty=0, OpenQty=qty)
            lines.append(line)
            delay = 0 if fraction(seed, f"{line_id}:ontime") <= p["OTIFTarget"] else 2
            receipts[day+p["BaseLeadTimeDays"]+delay].append((line_id, 1))
            onorder[key] += qty
            ordered_dc[key] += qty
            last_dc[key] = current
            event(day, "SUPPLIER_ORDER", key, qty, line["POLineID"])
        if any(v < 0 for balances in (stock, dc_stock, transit, onorder, backlog) for v in balances.values()):
            raise AssertionError("Negative simulated physical/pipeline balance")
    store_rows, store_controls = [], []
    for key in pairs:
        hist = history[key]
        first = start+timedelta(days=hist[0][0]) if hist else None
        last = start+timedelta(days=hist[-1][0]) if hist else None
        row = dict(zip(STORE_COLUMNS[:16], [last_store[key], *key, location[key][0], products[key[1]]["ABCClass"], stock[key], transit[key], backlog[key], int(key in active), first, last, sum(q for _,q in hist), (end-last).days if last else None, int(not hist), end, returned[key]]))
        for window in (28,56,84):
            gross = sum(q for t,q in hist if t >= days-window)
            row.update({f"TrailingGrossUnits{window}":gross, f"CoverageDays{window}":stock[key]*window/gross if gross else None, f"ZeroVelocityFlag{window}":int(gross==0)})
        row.update(InventoryProvenance=f"SIM_{VERSION}", DemandProvenance="OBSERVED_RAW", ReturnProvenance="OBSERVED_RAW", DecisionStatus="EXPLORATORY", PolicyApprovalStatus="NOT_APPROVED")
        store_rows.append(row)
        if store_opening[key]+received_store[key]+returned[key]-fulfilled[key] != stock[key] or shipped_store[key]-received_store[key] != transit[key] or requested[key]-shipped_store[key] != backlog[key]:
            raise AssertionError(f"Store conservation failed: {key}")
        store_controls.append(dict(Store=key[0], Product=key[1], Opening=store_opening[key], Receipts=received_store[key], Returns=returned[key], Fulfilled=fulfilled[key], Closing=stock[key], Shipped=shipped_store[key], InTransit=transit[key], Requested=requested[key], Backlog=backlog[key]))
    dc_rows, dc_controls = [], []
    for key,p in sorted(policy.items()):
        net = dc_stock[key]+onorder[key]-dc_backlog[key]
        rop,target = p["ReorderPointQty"],p["TargetStockQty"]
        dc_rows.append(dict(zip(DC_COLUMNS,[last_dc[key],*key,products[key[1]]["ABCClass"],p["Supplier"],dc_stock[key],onorder[key],dc_backlog[key],net,rop,target,rop,target,net,net-target,net-rop,int(net>target),int(net<rop),end,f"SIM_{VERSION}","FROZEN_INPUT_NOT_APPROVED_POLICY"])))
        if dc_initial[key]+received_dc[key]-shipped_dc[key] != dc_stock[key] or ordered_dc[key]-received_dc[key]-cancelled_dc[key] != onorder[key]:
            raise AssertionError(f"DC conservation failed: {key}")
        dc_controls.append(dict(DistributionCenter=key[0], Product=key[1], Opening=dc_initial[key], Receipts=received_dc[key], Shipped=shipped_dc[key], Closing=dc_stock[key], Ordered=ordered_dc[key], Cancelled=cancelled_dc[key], Open=onorder[key]))
    daily_rows = []
    for r in daily.daily:
        got,short = service[r.key]
        if got+short != r.demand_qty:
            raise AssertionError("Daily demand conservation failed")
        daily_rows.append(dict(zip(DAILY_COLUMNS,[r.date,r.store,r.demand_qty,got,short,r.return_inflow_qty,got/r.demand_qty if r.demand_qty else None,"TRAINING_HISTORY" if r.date<date(2026,2,2) else "V2_EVALUATION_REPEATED_HOLDOUT",f"OBSERVED_DEMAND_SIM_{VERSION}_FULFILLMENT","OBSERVED_RAW"])))
    cohorts = {(s["Supplier"],dc): [] for s in tables["DimSupplier"] for dc in sorted(dc_names)}
    for line in lines:
        if line["OrderedQty"] != line["ReceivedQty"]+line["CancelledQty"]+line["OpenQty"]:
            raise AssertionError("PO line equation failed")
        cohorts[(line["Supplier"],line["DistributionCenter"])].append(line)
    supplier_rows=[]
    for key,group in sorted(cohorts.items()):
        totals=[sum(x[c] for x in group) for c in ("OrderedQty","ReceivedQty","CancelledQty","OpenQty")]
        supplier_rows.append(dict(zip(SUPPLIER_COLUMNS,[*key,len({x['PONumber'] for x in group}),len(group),*totals,totals[1]/totals[0] if totals[0] else None,f"SIM_{VERSION}",f"FULL_HISTORY_THROUGH_{end}"])))
    return dict(store=store_rows, dc=dc_rows, daily=daily_rows, supplier=supplier_rows,
                store_controls=store_controls, dc_controls=dc_controls, purchase_lines=lines, events=events,
                assumptions=dict(version=VERSION, seed=seed, opening_interval_rows=len(selected), negative_openings_projected_to_zero=negative_opening,
                    missing_store_openings_assumed_zero=len(pairs)-len(selected), no_oracle_prestaging=True, allocation="LEXICOGRAPHIC_STORE_PRODUCT", supplier_second_attempt_delay_days=2))
