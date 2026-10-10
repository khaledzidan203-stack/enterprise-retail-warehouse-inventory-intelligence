# Project Evidence Map | Every Major Claim Linked to Source

A portfolio should distinguish **included source artifacts**, **locally executed tests**, **live CI** and **owner-attested manual Power BI Desktop runtime acceptance**. This index maps major claims to the exact files.

[Case study](CASE_STUDY.md) · [Technical walkthrough](TECHNICAL_WALKTHROUGH.md) · [Validation record](FINAL_RELEASE_VALIDATION.md)

| Claim | Repository evidence | Status / limitation |
|:---|:---|:---|
| Licensed open RAW source | [DATA_SOURCES.md](../DATA_SOURCES.md), [data/raw](../data/raw/) | Two original hash-matched Mendeley files under CC BY 4.0; code license separate |
| 125,751 sales and 284,755 inventory records | [ingestion.py](../src/python/ingestion.py), [tests](../src/python/test_ingestion.py) | Validated RAW; signed returns and open stock intervals preserved |
| OBS demand/return logic | [observed_movements.py](../src/python/observed_movements.py), [tests](../src/python/test_observed_movements.py) | Full-history 124,542 positive demand units; 7,547 positive return units |
| Source Store × Product universe | [inventory_entities.py](../src/python/inventory_entities.py) | 63,556 union including inventory-only pairs; not historical 50,447 SIM coverage |
| Five enriched dimensions | [reference_dimensions.py](../src/python/reference_dimensions.py) | 40 stores, 2,326 products, 30 supplier entities, four synthetic DCs |
| Date + daily OBS fact | [observed_daily_model.py](../src/python/observed_daily_model.py) | 328 dates, 12,706 Date × Store keys |
| Supplied simulation inputs | [data/synthetic](../data/synthetic/), [config](../config/) | Assumptions and frozen policies, not independently observed corporate processes |
| Preserved historical V2 simulation | [data/integrated_v2](../data/integrated_v2/), [analytics inputs](../data/analytics_v1/) | Original final report evidence, not re-created by NEW_REPLAY_V1 |
| NEW_REPLAY_V1 source | [simulation.py](../src/python/simulation.py), [pipeline.py](../src/python/pipeline.py) | Repeatable alternative simulator; historical numeric parity **not** achieved |
| SQL / dimensional constraints | [analytics.sql](../src/sql/analytics.sql), [sql_model.py](../src/python/sql_model.py) | Executable SQLite PK/FK/CHECK and KPI/DQ views |
| 8 native Power BI pages and 112 visuals | [PBIP](../powerbi/Enterprise%20Retail%20Inventory%20Intelligence.pbip), [report folder](../powerbi/), [runtime record](FINAL_RELEASE_VALIDATION.md) | Static structure confirmed; 2026-10-10 Desktop navigation and visual operation owner-attested PASS |
| 51 DAX measures / 18 relationships | [SemanticModel TMDL](../powerbi/) | Preserved model definitions, static checks |
| Eight authentic historical screenshots | [Dashboard folder](../DASHBORD_SCREEN_SHOTS/), [Page Guide](REPORT_PAGE_GUIDE.md) | Real saved historical views, **not** new replay/sample |
| One configurable CSV root | [configure_powerbi.py](../configure_powerbi.py), [setup](powerbi_setup.md), [runtime record](FINAL_RELEASE_VALIDATION.md) | Nine historical source hashes and local configuration passed in shared PowerShell output; Desktop refresh owner-attested PASS |
| Tests | [test modules](../src/python/), [validate.py](../validate.py) | Previously 55/55 project and 47/47 isolated clone test passes |
| Live GitHub pipeline | [Workflow](../.github/workflows/ci.yml), [Actions runs](https://github.com/khaledzidan203-stack/enterprise-retail-warehouse-inventory-intelligence/actions) | Integrity + executable fictional sample; inspect live run result |
| Rights and scope | [release_rights.md](release_rights.md), [DATA_SOURCES.md](../DATA_SOURCES.md) | RAW source attribution documented; do not assume a software LICENSE |

## Critical semantic boundaries

**OBS:** Original positive customer demand and signed customer returns; no independently observed fulfillment/stockout events.  
**SIM:** Historical and new-replay physical stock, fulfillment, supplier/DC execution and policy-derived quantities.  
**EXP:** Zero-demand stock flags; NOT_APPROVED business actions.

**Grain:** Date × Store daily service is not Product-grain. Store/DC inventory is a fixed AsOf snapshot. Supplier × DC is cumulative, not time-series demand.

**Equations:** Demand = Fulfilled + Shortage; Supplier ordered = received + cancelled + open. Stock conservation is within the specified simulated event rules; original negative on-hand RAW values remain unchanged upstream.

## Historical SIM ≠ NEW_REPLAY_V1

| Metric | Historical V2 | Reconstructed V1 |
|:---|---:|---:|
| Store × Product rows | 50,447 | 63,556 |
| Store ending on-hand | 68,734 | 62,099 |
| DC ending on-hand | 53,030 | 50,045 |
| Holdout SIM fulfilled | 29,363 | 20,323 |
| Holdout SIM shortage | 637 | 9,677 |

Full 13-metric reconciliation and reasons: [Methodology](methodology.md). The reconstructed source does **not** copy old analytical CSVs as production inputs.

## Reviewer route

Start with the [eight-page gallery](../README.md#power-bi-dashboard-gallery), inspect the native [PBIP](../powerbi/Enterprise%20Retail%20Inventory%20Intelligence.pbip), run [Python/SQLite sample](TECHNICAL_WALKTHROUGH.md#run-python--sqlite-on-reproducible-fictional-data), then verify current [GitHub Actions](https://github.com/khaledzidan203-stack/enterprise-retail-warehouse-inventory-intelligence/actions). Automation does not execute Power BI Desktop; the separate **owner-attested manual acceptance** is recorded in [Final Release Validation](FINAL_RELEASE_VALIDATION.md) and is not independent runtime certification.
