# CP6A — Dashboard Architecture & Design Contract (PROPOSED)

Project: Enterprise Retail Inventory Intelligence (existing PBIP).

## Build order

CP6A Design contract (this checkpoint) → CP6B INDEX page + donor validation → CP6C Executive Overview → CP6D Store/DC Inventory → CP6E Service/Supplier → CP6F Opportunities/Methodology → CP6G full report visual/runtime QA → Phase 7 final cleanup, archive and release.

## Eight pages

- INDEX — NAVIGATION — Enterprise Retail Inventory Intelligence | Report navigation
- Executive Overview — MIXED_SCOPE_SUMMARY — Historical physical network snapshot + separately labeled development holdout service
- Store Inventory Intelligence — ASOF_STORE_SNAPSHOT — Historical Store × SKU inventory position and physical inflow
- DC Inventory Intelligence — ASOF_DC_SNAPSHOT — Frozen simulation replenishment positions; NOT corporate Overstock thresholds
- Sales & Stockout Performance — DATE_STORE_SERVICE — Date × Store positive observed demand and simulated units fulfilled / short
- Supplier Execution Simulation — CUMULATIVE_SUPPLIER_DC — Cumulative synthetic PO / GRN experience; not observed supplier scorecards
- Inventory Opportunities (Exploratory) — EXPLORATORY_NOT_APPROVED_POLICY — Zero-velocity Store-SKU screens only; NO actionable transfer / return / markdown recommendation
- Data Quality & Methodology — GOVERNANCE_DISCLOSURE — Sources, simulated vs observed metrics, as-of timing and analytical limitations

## Non-negotiable metric behavior

- DATE slicer filters FactStoreDailyService only. The Store/DC as-of snapshots are fixed at 2026-04-24.
- Date × Store daily service has NO Product-grain metrics. Avoid product slicers on the Service page.
- Supplier × DC cumulative facts are synthetic and do not have a Date grain. No Date slicer on that page.
- Inventory Opportunities are diagnostic zero-velocity screens; not approved Overstock or Transfer decisions.
- Historical raw positive outbound Sales/returns are observed; all Store/DC/Supplier movements are simulated.
- Frozen V2 launch pre-stage uses the first positive future Sale as activation proxy; ORACLE hindsight. Never claim prospective performance or unbiased test.
- Same-day returns are replayed into Store inventory; sellability and disposition are business assumptions, not source-proven.
- No financial inventory valuation, GMROI, expired-lot, supplier return, markdown, transfer action, live ERP or certified supplier metrics.

## PBIR native build strategy

Use a native Power BI donor from the same visual family, clone one target page at a time, validate query and formatting bindings, review in Desktop, screenshot, save and Git diff. INDEX has no slicers; each analytical page gets exactly one Home navigation control. Native page background (not a full-canvas blocking visual).

## Approval gate

These are DESIGN PROPOSALS, not generated PBIR pages. CP6A does not change Report/pages or TMDL. Final visual and DAX runtime validation must occur in Power BI Desktop.
