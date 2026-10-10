# Publication scope, provenance and licensing

## Included assets

This public repository contains the original, preserved project deliverables: Python/SQLite source and automated tests, original retail RAW CSVs, published historical V2 integrated/reference data, supplied synthetic scenario fixtures, 9 historical reporting CSV inputs, complete Power BI PBIP/PBIR/TMDL, 8 authentic screenshots, configuration, and technical documentation.

**Source:** [Retail Transactions and Stocks Data — Mendeley Data, V1](../DATA_SOURCES.md), licensed **CC BY 4.0**. The two original RAW files were checked against publisher SHA-256 fingerprints. Public source data has been adapted into governed datasets and illustrated through modeled warehouse and supplier scenarios. Give credit to the original source when redistributing source-derived material.

**Different rights:** CC BY 4.0 covers the cited source dataset, **not automatically this project's authored software, DAX, report layouts or other materials**. No general-purpose code license is asserted.

## Excluded development and machine-specific material

This release intentionally omits local Power BI caches, machine-specific settings, virtual environments, temporary build outputs, private dashboard construction utilities, backups and superseded draft design/checkpoint documents. Such files are unnecessary to inspect the final report or run the documented analytical code.

## Reproducibility boundary

The historical final V2 Power BI report and nine reference inputs are preserved. The runnable **NEW_REPLAY_V1** reconstructs a different explicitly modeled simulation: historical inventory/service equivalence has **not** been established. Actual Power BI Desktop refresh and visual interaction are **not yet independently runtime verified**.

`release_manifest.json` is the current list of published paths and protected source asset hashes. The GitHub Actions workflow runs publication/file integrity checks and an executable Python/SQLite fictional-sample validation; it is not a Power BI Desktop runtime.

[Read the methodology](methodology.md) · [Source attribution and raw hashes](../DATA_SOURCES.md) · [Validation evidence](FINAL_RELEASE_VALIDATION.md)
