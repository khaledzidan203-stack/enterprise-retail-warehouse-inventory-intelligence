# Power BI portability and verification

The original `powerbi/Enterprise Retail Inventory Intelligence.pbip`, both Report/SemanticModel folders and all eight screenshots are included. The source license and RAW publisher hashes were verified before publication (see `DATA_SOURCES.md`). No private dashboard-generation script is included.

## Configure one path

The new named Power Query parameter `DataRoot` is defined in the semantic model's `definition/expressions.tmdl`. It is a required text parameter with an initially empty value, so refresh needs explicit configuration. All nine CSV imports now use `DataRoot & "/<schema-folder>/<file>.csv"`; existing column order, M conversions and DAX remain unchanged.

With Power BI Desktop closed, run `python configure_powerbi.py` from the repository. It verifies the nine original CSV hashes and configures DataRoot to the absolute **historical `<checkout>/data` folder**. It does not execute a pipeline or modify CSVs. Manual alternative: change just the quoted DataRoot value in expressions.tmdl to that folder, using forward slashes and no trailing slash. Do not point the original report at `build/` unless deliberately reviewing the separately labeled new simulation. `python configure_powerbi.py --check` verifies the historical inputs without editing the model.

Open the PBIP in a compatible Power BI Desktop. Refresh all tables, check all eight pages and navigation, inspect date and entity slicers, and compare service/stock/supplier measures with the included historical CSVs; generated SQLite views describe NEW_REPLAY_V1 and are not an equivalent historical oracle. A sample run has fictional entities and different numerical results. Historical narrative labels/screenshots are retained and do not certify or describe that sample. Dynamic filters tied to historical entities may need owner review after sample refresh; no visual redesign was performed.

Microsoft documents [TMDL editing and refresh behavior](https://learn.microsoft.com/en-us/power-bi/transform-model/desktop-tmdl-view) and [Power Query parameters](https://learn.microsoft.com/en-us/power-query/power-query-query-parameters). Editing model metadata alone is not a successful data refresh.

## Precisely scoped changes

Desktop was checked and not running before edits. Eleven original files were copied byte-for-byte into ignored `build/powerbi_original`: the nine CSV-import tables, `model.tmdl`, and one Executive Overview visual. A twelfth file, `expressions.tmdl`, was created. No table expression other than the nine `File.Contents` arguments changed. `model.tmdl` only adds the named expression reference.

The affected Executive Overview visual's stale sort binding `analytics dim_date.calendar_date` was replaced by `DimDate.Date`. Its visual ID is `813d135d1d6e4570d89f`; its page ID is `3f0c385e4017cd30f78d`. No layout, styling, navigation, measure or relationship change was made.

Static checks found eight pages, 112 visuals, 51 measures and 220 valid explicit column/measure bindings, including sorting. They compare the generated nine CSV headers with TMDL source columns, retain the existing typed conversions, and check the single parameter reference in each import. Existing relationship and measure definitions are hash-preserved against pre-change evidence.

**POWER_BI_RUNTIME_NOT_VERIFIED.** This execution had no accessible Power BI automation/refresh runtime. JSON/TMDL text checks cannot establish Desktop opening, query execution, rendered visuals or DAX evaluation. Those remain required owner-side acceptance checks before claiming full reproducibility.
