# Analytical dictionary and executable SQL

## Inputs and lineage

`ingestion.py` is the authority for RAW headers and normalized types. Sales rows contain dated Store/Product transactions, signed quantities, return flags and commercial/entity attributes. Inventory rows contain inclusive start/end intervals, observed stock and entity attributes. Normalization preserves signed values and source row numbers. `observed_movements.py` groups positive non-return demand and positive return inflow at Date × Store × Product; zero transactions remain counted in source accounting but generate no demand. `inventory_entities.py` retains full entity coverage and profiles source anomalies without repairing them.

The four B4 fixtures are `store_geography.csv`, `product_supply_policy.csv`, `supplier_operational_profile.csv`, `distribution_centers.csv`. The simulation additionally requires `dc_inventory_policy_v2.csv`, `dc_opening_inventory_v2.csv`, and `store_replenishment_policy_v2.json`. The latter's review and mature replenishment settings are reused; unverified launch, calibration and replenishment sections are not claimed as reconstructed. All inputs have hashes in execution evidence.

## Nine CSV contracts

Identifiers and labels are text, dates are ISO `YYYY-MM-DD`, quantities/counts/flags are integers, and rates/coverage are decimal numbers serialized to eight places. All primary keys are required and unique. Blank CSV values mean null only where specified. Existing Power BI M/type definitions are retained. `execution.json.schemas` records the complete ordered header of each output.

| Dataset / file under generated `data` | Grain | Columns | Meaning |
|---|---|---:|---|
| `powerbi_model_v1/DimDate.csv` | Date | 9 | Inclusive governed sales calendar |
| `powerbi_model_v1/DimStore.csv` | Store | 6 | OBS key, supplied SIM geography/DC mapping |
| `powerbi_model_v1/DimProduct.csv` | Product No | 8 | OBS product/supplier/hierarchy, supplied SIM ABC |
| `powerbi_model_v1/DimSupplier.csv` | Supplier | 7 | Source supplier key, supplied operational profile |
| `powerbi_model_v1/DimDistributionCenter.csv` | DistributionCenter | 2 | Supplied synthetic DC key and flag |
| `analytics_v1/analytics_store_sku_asof_v1.csv` | Store × Product No at AsOf | 30 | OBS movement windows plus SIM store state |
| `analytics_v1/analytics_dc_sku_asof_v1.csv` | DC × Product No at AsOf | 21 | SIM DC state and supplied frozen thresholds |
| `analytics_v1/analytics_store_daily_service_v1.csv` | Date × Store | 10 | OBS demand/returns plus SIM service |
| `analytics_v1/analytics_supplier_dc_execution_v1.csv` | Supplier × DC | 11 | SIM full-history order-line cohort |

DimDate attributes: `Year`, `Quarter` (Q1–Q4), `MonthNumber`, English `MonthName`, `YearMonth`, `MonthStartDate`, ISO week number `ISOWeek`, `DevelopmentPhase`. The retained phase boundary is 2026-02-02: `TRAINING_HISTORY` before it, `V2_EVALUATION_REPEATED_HOLDOUT` afterwards. The label is inherited schema metadata; it does not imply independent evaluation of the new simulation.

DimStore attributes: `RegionCode`, `RegionName`, `SyntheticCityCode`, `DistributionCenter`, `IsSynthetic`. DimProduct: `Supplier`, `Product Description`, `Product Division`, `Product Category`, `Product Subcategory`, `Product Segment`, `ABCClass`. DimSupplier: `SupplierClass`, `ProductCount`, `BaseLeadTimeDays`, `OTIFTarget`, `FillRateTarget`, `IsSynthetic`. DimDistributionCenter: `IsSynthetic`. Attribute-level OBS/SIM provenance is preserved by the existing B4 dimension contracts; flags alone do not change an observed source key into a simulated key.

Store snapshot fields:

- `StateDate`, `AsOfDate`, `Store`, `Product No`, `DistributionCenter`, `ABCClass`: temporal/entity context.
- `EndOnHandQty`, `EndInTransitQty`, `EndOpenRequestQty`: simulated stock, dispatched-but-unreceived transfer stock, unallocated store requests.
- `ActiveAssortmentFlag`: has had positive gross demand by AsOf in this scenario.
- `FirstPositiveDemandDate`, `LastPositiveDemandDate`, `FullHistoryGrossDemandQty`, `DaysSinceLastPositiveDemand`, `NeverObservedPositiveDemandFlag`: OBS activity summary; dates and elapsed days are null for never-sold pairs.
- `FullHistoryCustomerReturnQty`: positive full-history OBS return inflow.
- `TrailingGrossUnits28/56/84`: inclusive window gross demand; `CoverageDays28/56/84 = EndOnHandQty × window / TrailingGrossUnits`; null on zero demand.
- `ZeroVelocityFlag28/56/84`: 1 when the corresponding demand window is zero, including pairs with no stock.
- `InventoryProvenance`, `DemandProvenance`, `ReturnProvenance`, `DecisionStatus`, `PolicyApprovalStatus`: separate simulation, source movement and unapproved exploratory interpretation.

DC snapshot fields: `StateDate`, `AsOfDate`, `DistributionCenter`, `Product No`, `ABCClass`, `Supplier`; `EndOnHandQty`, `EndOnOrderQty`, `EndStoreBacklogQty`; `NetInventoryPosition = on-hand + on-order − backlog`; supplied `ReorderPointQty`, `TargetStockQty` and explicitly repeated `ReorderPointQty_FrozenPolicy`, `TargetStockQty_FrozenPolicy`; `NetPositionRecomputedQty`, `NetPositionMinusFrozenTargetQty`, `NetPositionMinusFrozenROPQty`, strict greater/less-than flags `AboveFrozenSimulationTargetFlag`, `BelowFrozenSimulationROPFlag`; `Provenance`, `PolicyStatus`. Negative net position is legitimate even though physical stock cannot be negative.

Daily fields: `Date`, `Store`, `DemandQty`, `FulfilledQty`, `ShortageQty`, `ReturnInflowQty`, `UnitServiceRate`, `DevelopmentPhase`, `DemandProvenance`, `ReturnProvenance`. Demand equals fulfillment plus shortage. Returns-only keys have zero demand and null service rate; returns never reduce gross demand.

Supplier fields: `Supplier`, `DistributionCenter`, `DistinctPOHeaders`, `POLines`, `OrderedQty`, `ReceivedQty`, `CancelledQty`, `OpenQty`, `ReceivedToOrderedRatio`, `Provenance`, `MeasurementBoundary`. Ordered = received + cancelled + open for every line and cohort. Open means unresolved at AsOf. Receipt ratio is null on zero ordered quantity; it is not an independently measured OTIF metric.

## KPI definitions and SQL

Service rate is **sum fulfilled / sum demand**, not average of daily percentages. Stock is the sum of closing physical quantities. Zero-sales inventory sums closing stock for zero-demand flagged pairs. Count of zero-demand pairs includes zero-stock pairs; no hidden positive-stock filter is applied. All quantities are units, not monetary opportunity estimates. Supplier receipt ratio uses aggregate quantities in a defined order cohort.

`src/sql/analytics.sql` is executed for every run by `sql_model.py`. SQLite stores deliberate analytical projections of all nine tables rather than copying every presentation attribute. `sql_model.PROJECTIONS` lists the exact mapped fields; SQL uses `ProductNo` for CSV `Product No`. PKs, required keys, FKs, nonnegative physical quantities and reconciliation equations are enforced by the database. SQL and Python are checked row by row and by KPI aggregates.

Views: `ServiceKPI` (full history), `HoldoutKPI` (2026-02-02 through 2026-04-24), `InventoryKPI` (Store/DC/zero-demand inventory), and `DQFailures` (equation and window-flag exceptions). Execute with Python's bundled SQLite, for example:

```powershell
python -c "import sqlite3; c=sqlite3.connect('file:build/public/analytics.sqlite?mode=ro',uri=True); print(c.execute('SELECT * FROM ServiceKPI').fetchall()); print(c.execute('SELECT * FROM DQFailures').fetchall()); c.close()"
```

Physical conservation evidence is persisted separately: `store_controls.csv`, `dc_controls.csv`, `purchase_lines.csv`, and `events.csv`. The validator ties these to final facts, observed demand/returns, daily outcomes and SQL. These are audit evidence for a run, not production inputs to the next run.
