# Methodology and reconciliation

## Evidence boundary

Recovered contracts are B1 RAW parsing, B2 signed sales/return aggregation, B3 full source entities and inventory intervals, B4 governed dimensions, and B5 calendar/observed daily analytics. Existing integrated and analytical CSVs are read only by validation. No historical output is loaded by production to initialize or tune the new simulation.

Supplied geography, ABC classes, supplier targets, DC slots, DC opening stock and frozen policy are **inputs**, not facts inferable from sales alone. The frozen DC fixture may encode information calibrated later than the beginning of the replay. Applying it throughout history is a development assumption with hindsight risk. No production validation or causal policy benefit is claimed.

The old simulation's exact store initialization, launch prestaging, allocation, supplier random-event schedule and sampling semantics cannot be established from the surviving source. `NEW_REPLAY_V1` is newly implemented and independently checked. It deliberately retains the complete 63,556 Store × Product source union; the historical 50,447-pair subset is not a proven eligibility policy.

## Exact replay rules

1. The inclusive RAW sales range governs time. For the private data it is 2025-06-01 through 2026-04-24. Inventory sentinel 9999-12-31 remains unchanged in B3.
2. A store's opening scenario balance uses its unique source interval covering the first day, inclusively. Missing intervals map to zero; negative source quantities map to zero **only in SIM physical state**. Overlapping covering intervals fail. Original source values remain untouched. This private run has 2,030 covering intervals, 61,526 missing openings and five negative covering quantities. None is presented as recovered historical opening inventory.
3. Supplied DC openings must have the first source date. DC slots and policy keys must agree, map to dimensions, and contain finite integral quantities and valid probabilities.
4. Each day processes supplier receipts/cancellations, store transfer arrivals, customer returns, sales demand, store replenishment/shipments, then DC purchase orders. Stock can never become negative. A return is observed positive inflow; its immediate sellability is a SIM assumption. Demand exceeding available stock is SIM shortage; it is not deferred customer demand or measured lost revenue.
5. A pair becomes active on its first observed positive sale. There is no oracle launch calendar, future-demand prestaging or invented demand for inventory-only pairs. Returns-only keys remain represented in daily data.
6. Store ROP and target use nearest-rank empirical quantiles of trailing 2-day and 4-day demand sums, with zeros on missing calendar dates. The frozen store policy supplies 84-day lookback, seven-day recalibration, ABC quantiles and minima. Windows include the current observed day and can start before the lookback boundary; missing prehistory contributes zero. Reviews occur after demand. A new active pair is calibrated immediately, then on fixed review days counted from day zero.
7. Position for store reorder is on-hand plus in-transit. Outstanding requests reduce the new request quantity. A request moves stock from its mapped DC if available; fixed **lexicographic Store × Product priority** resolves competition. This is a new priority rule, not recovered proportional allocation. Transfer lead time comes from the frozen policy. Outstanding requests and goods in transit remain visible at the horizon.
8. DC review cadence, ROP, target, case pack, MOQ and supplier are supplied. Net position is on-hand + on-order − outstanding store requests. Orders round up to case packs after MOQ. PO headers group supplier/DC/day; lines follow deterministic sorted slots.
9. Supplier draws use SHA-256 of seed and deterministic line identity. The configured OTIF target is used as an on-time probability proxy, not measured OTIF. A late first receipt is two days later. At each attempt, a draw below the fill target fills the remainder; otherwise floor(remainder × fill target) arrives. One retry follows two days later; any residual then cancels. Orders pending beyond AsOf stay open. These delay, fill and cancellation rules are explicit new assumptions, not a recovered service distribution.
10. Closing snapshots cover every source Store × Product and every supplied DC policy slot. StateDate means last tracked demand/return/receipt/request/shipment/order activity (or opening date), while AsOfDate is the common horizon. A zero-demand pair has blank first/last-sale dates and blank days-since-sale. Full-history supplier cohorts include all suppliers × DCs, including zero-order cohorts.

All physical units are integers; fractional inputs fail instead of rounding physical stock. OBS quantities retain B1 Decimal precision. Ratios/coverage are exported to eight decimal places; quantities reconcile exactly and computed ratios use tolerance 1e-8. Null ratios stay blank when their denominator is zero. The 28/56/84-day demand windows include both `AsOf - window + 1` and `AsOf`. ZeroVelocityFlag means zero positive gross demand, irrespective of current stock.

OBS identifies original sales/returns and source attributes. SIM identifies replayed state and supplied assumptions. EXP is represented by `DecisionStatus=EXPLORATORY` and `PolicyApprovalStatus=NOT_APPROVED`. In the public example, observed-style movements are explicitly labeled `SYNTHETIC_EXAMPLE_SOURCE`; all sample entities and quantities are fictional. `execution.json` records data origin, input hashes, seed and assumptions.

## Original final-baseline reconciliation (previously executed)

Final V2 simulation references are projected into the historical `analytics_v1` CSV filenames. Those names denote the presentation schema, not a claim that this run uses the older `data/integrated` V1 simulation. No V1/V2 files are merged.

| Metric | Historical final V2 | NEW_REPLAY_V1 | Difference |
|---|---:|---:|---:|
| Store × Product rows | 50,447 | 63,556 | +13,109 |
| DC × Product rows | 9,304 | 9,304 | 0 |
| Daily Store rows | 12,706 | 12,706 | 0 |
| Supplier × DC rows | 120 | 120 | 0 |
| Store closing stock | 68,734 | 62,099 | −6,635 |
| DC closing stock | 53,030 | 50,045 | −2,985 |
| Full-history OBS returns | 7,547 | 7,547 | 0 |
| Holdout OBS demand | 30,000 | 30,000 | 0 |
| Holdout SIM fulfillment | 29,363 | 20,323 | −9,040 |
| Holdout SIM shortage | 637 | 9,677 | +9,040 |
| Holdout OBS returns | 1,738 | 1,738 | 0 |
| 84-day zero-demand stock | 45,021 | 40,140 | −4,881 |
| 84-day zero-demand pairs | 31,776 | 44,885 | +13,109 |

All five dimensions match every key and attribute. Daily dates/stores, observed demand and observed returns have zero mismatches. For common store keys, observed demand/returns, first/last activity and all three trailing gross-demand windows match. Store closing stock differs at 3,938 common keys; DC closing stock at 7,740 keys; daily fulfillment/shortage at 11,085 keys. No historical key is missing; 13,109 inventory-only store/product keys are additional. Provenance and policy labels intentionally expose the new scenario, and also appear as differences. Supplier quantities and timing differ; the historical matching totals are not an objective function.

The full private result is `build/private_final/historical_reconciliation.json`; every discrepant key/attribute is in `build/private_final/evidence/historical_differences.csv`. These development build files are excluded as unnecessary build outputs. The original reference CSVs are now published with verified source attribution; the included tests and comparator can validate the historical claims without downloading confidential inputs. No full analytical run was repeated for publication.

## Validation scope

The unified runner executes all 44 previous tests in private mode and the new pipeline tests, checks nine CSV schemas/grains/FKs, calendars, per-key store/DC conservation, physical nonnegativity, return integration, supplier line and cohort equations, ratio/null rules, all trailing windows, SQLite row-level agreement, and repeat-run hashes. B1–B5 source roundtrip and reference tests are explicitly omitted in public mode because their private oracles are unavailable. Simulation tests also exercise negative opening stock and complete supplier failure/cancellation.

The historical comparator emits every exception and exits 2 on differences. `ANALYTICAL_PIPELINE_PASS` verifies the new scenario; `PARTIAL_REPRODUCIBILITY` is the overall status while historical simulation equivalence and Power BI runtime remain unresolved; source data attribution and permission to publish this original project were resolved before release. `FULL_REPRODUCIBILITY_PASS` is not asserted. `NOT_VERIFIED` is distinct from success.
