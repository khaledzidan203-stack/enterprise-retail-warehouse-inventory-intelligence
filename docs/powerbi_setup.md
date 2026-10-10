# Open the original Power BI report

The repository contains the original historical **8-page Power BI PBIP** project with report and semantic-model definitions (PBIR/TMDL), **51 DAX measures**, **18 relationships** and **9 included historical CSV inputs**. All eight page screenshots are in [the gallery](../README.md#power-bi-dashboard-gallery).

## Requirements

- A compatible **Power BI Desktop** installation on Windows, including support for PBIP/PBIR/TMDL project files.
- Python **3.11+** for the one-time source path setup, and the checked-out repository on your computer.

## Configure historical data

From the repository root, with **Power BI Desktop closed**:

```powershell
python configure_powerbi.py --check
python configure_powerbi.py
```

The first command checks the hashes of all nine historical CSV files without editing the report. The second verifies the same inputs and writes the local absolute `data/` location into the `DataRoot` expression in the semantic model. It does **not** generate, alter or download data.

Open **[Enterprise Retail Inventory Intelligence.pbip](../powerbi/Enterprise%20Retail%20Inventory%20Intelligence.pbip)** and refresh the model's nine CSV tables.

**Manual alternative:** the parameter is defined in `powerbi/Enterprise Retail Inventory Intelligence.SemanticModel/definition/expressions.tmdl`. Set the quoted `DataRoot` to your local repository's `data/` folder with forward slashes and no trailing slash. Keep the original reporting sources under `data/analytics_v1/` and `data/powerbi_model_v1/`. Those folder names are retained presentation contracts for the historical final V2 tables.

Do **not** substitute `build/` outputs from NEW_REPLAY_V1 unless you explicitly want to study a different modeled scenario; those outputs differ from the preserved historical report.

## Recommended acceptance checklist

1. Confirm the nine CSVs refresh without Power Query errors.
2. Confirm eight pages open with working INDEX and Home navigation.
3. Test appropriate Store, Product, DC, Supplier and Date filters; remember snapshots and supplier cohorts do not share daily Date grain.
4. Compare network on-hand, service/shortage and supplier measures with the preserved historical CSVs.
5. Confirm screenshot correspondence and any page visuals that use date-grain or model-policy assumptions.

**Verification boundary:** source checks confirm eight pages, 112 visuals, 51 DAX measures, 18 relationships and nine imports. On **2026-10-10**, the project owner confirmed that a fresh public GitHub clone opened and refreshed in Windows Power BI Desktop and that all eight pages, report navigation, slicers and visuals worked (**OWNER-ATTESTED PASS**). This is manual user-reported runtime acceptance, not independent automation, per-measure DAX testing or historical-simulation parity. [Dated acceptance record](FINAL_RELEASE_VALIDATION.md).

[Report guide](REPORT_PAGE_GUIDE.md) · [Analytical dictionary](analytics_dictionary.md) · [Microsoft Power Query parameter documentation](https://learn.microsoft.com/en-us/power-query/power-query-query-parameters)
