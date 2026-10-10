# Case Study | Enterprise Retail Warehouse & Inventory Intelligence

**Sector:** Multi-store retail and warehouse analytics  
**Scope:** Public source data, inventory/supplier simulation, Python/SQLite, original eight-page Power BI report  
**Evidence:** [Dashboard gallery](../README.md#power-bi-dashboard-gallery) · [Evidence map](PROJECT_EVIDENCE_MAP.md) · [Technical walkthrough](TECHNICAL_WALKTHROUGH.md)

## The business problem

Decision-makers evaluating retail stock need answers at different grains. A store-product snapshot says where modeled stock sits; daily store demand says when customers wanted products; supplier/DC cohorts summarize a simulated procurement process. Mixing these directly gives misleading totals.

This case study links these views while keeping **observed gross sales and customer returns (OBS)** separate from **modeled physical stock, fulfillment, purchase orders and supplier receipts (SIM)** and **exploratory opportunity signals (EXP)**. It does not claim to be a live WMS/ERP or a production supplier scorecard.

## Dataset and scope

[Retail Transactions and Stocks Data](../DATA_SOURCES.md), Mendeley Data, CC BY 4.0, provides two unmodified RAW files: **125,751 sales rows** and **284,755 inventory-interval rows**. Validated source entities include **40 stores**, **2,326 products** and a **63,556 Store × Product union**. The calendar covers **2025-06-01 through 2026-04-24**.

The enriched scenario adds **four synthetic distribution centers**, 30 supplier entities, geographic assignments, ABC classes and supplier/DC settings. These synthetic attributes are **modeling inputs**, not observed organizational infrastructure.

## What was designed and implemented

| Layer | Portfolio deliverable |
|:---|:---|
| RAW → source contracts | Typed ingestion, strict schema validation, preservation of negative inventory and open intervals |
| Observed demand & returns | Separate aggregation of positive sales and signed return inflow without netting |
| Entity/governed dimensions | Store × Product coverage, five analytical dimensions, OBS/SIM provenance |
| Historical analytical presentation | Preserved final V2 report CSVs, snapshots and daily service facts |
| Reconstructed executable scenario | Deterministic NEW_REPLAY_V1 store/DC inventory, supplier execution and policy simulation |
| Analytical SQL | SQLite fact/dimension constraints and KPI/data-quality views with Python reconciliation |
| Business intelligence | Native PBIP/PBIR/TMDL, eight pages, 112 visuals, 51 DAX measures and 18 relationship definitions |
| Verification | Historical data contracts, repeatable sample tests, file integrity and explicit model limitations |

## Historical dashboard results

**These results describe the retained historical final V2 simulation, not NEW_REPLAY_V1.** Snapshot: 2026-04-24. Evaluation window: 2026-02-02 to 2026-04-24.

| Indicator | Value | Interpretation |
|:---|---:|:---|
| Store × Product reporting pairs | 50,447 | Historical reporting universe |
| DC × Product pairs | 9,304 | Modeled DC inventory |
| Date × Store records | 12,706 | OBS demand/returns plus SIM service |
| Store closing on-hand | 68,734 units | Historical SIM physical stock |
| DC closing on-hand | 53,030 units | Historical SIM physical stock |
| Full-history returns | 7,547 units | Observed customer return inflow |
| Holdout demand | 30,000 units | Observed positive gross demand |
| Holdout fulfilled | 29,363 units | Historical SIM fulfilled demand |
| Holdout shortage | 637 units | Historical SIM unfulfilled demand |
| 84-day zero-positive-demand on-hand | 45,021 units | OBS demand window × historical SIM stock |

Modeled shortage is **not** directly measured out-of-stock sales loss. Zero demand is **not** automatically an approved transfer, liquidation or return decision.

## Business journey across eight pages

The [Report Page Guide](REPORT_PAGE_GUIDE.md) includes the authentic screenshot of **every** page, purpose and relevant filter/grain caution:

1. INDEX — navigation and report context
2. Executive Overview — network inventory and service summary at stated, different time scopes
3. Store Inventory Intelligence — store SKU holdings, in-transit and open requests
4. DC Inventory Intelligence — DC balances and frozen-simulation policy comparisons
5. Sales & Stockout Performance — OBS Date × Store demand against simulated service
6. Supplier Execution Simulation — cumulative SIM PO/GRN supplier/DC cohorts
7. Inventory Opportunities (Exploratory) — diagnostic 28/56/84-day zero-demand screens
8. Data Quality & Methodology — source integrity, definitions and limitations

## Distinct implementation vs presentation

The published original Power BI report uses **preserved historical V2 reference CSVs**. Its original simulation source code was not fully recoverable. The new Python/SQLite engine consequently reconstructs **another documented simulation** and gives different balances and service metrics: 63,556 store pairs rather than historical 50,447; different on-hand and shortage results. Both are intentionally available, with exact differences in the [methodology](methodology.md). The new engine is **not tuned to copy historical targets**.

Local engineering evidence recorded **55/55 project tests** and **47/47 fresh-clone public sample tests**. GitHub Actions now includes a runnable fictional-sample analytical check; the live result is visible on the [Actions page](https://github.com/khaledzidan203-stack/enterprise-retail-warehouse-inventory-intelligence/actions). Power BI Desktop opening and refresh are **not yet independently runtime verified**.

## Reviewer takeaway

This is a portfolio implementation of **source governance, multi-grain analytics, supply-chain simulation, semantic modeling and business reporting**. Its strength is both the complete native Power BI deliverable and the explicit separation of what is observed, simulated and unverified.

**Continue:** [Power BI gallery](../README.md#power-bi-dashboard-gallery) · [Technical walkthrough](TECHNICAL_WALKTHROUGH.md) · [Evidence map](PROJECT_EVIDENCE_MAP.md).
