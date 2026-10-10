# Final Release Validation | Evidence, CI and Honest Limitations

[Project index](PROJECT_INDEX.md) · [Evidence map](PROJECT_EVIDENCE_MAP.md) · [GitHub Actions](https://github.com/khaledzidan203-stack/enterprise-retail-warehouse-inventory-intelligence/actions)

## Recorded engineering results

| Acceptance gate | Status | What it does and does not prove |
|:---|:---|:---|
| Project Python tests in original working tree | **55/55 PASS** | Validated the original working implementation at the time |
| Isolated local fresh clone on public synthetic example | **47/47 PASS** | Installation and sample code could run outside original workspace |
| B1–B5 observed/dimension records | **PASS** | OBS demand/returns, date and dimensions reconciled |
| Python → SQLite analytical projections | **PASS** | All nine generated tables mapped to valid SQL, no FK/DQ exceptions |
| Synthetic sample determinism | **PASS** | Repeated generated artifacts agreed |
| Historical V2 ↔ NEW_REPLAY_V1 exact simulation | **NOT MET** | Different opening/launch/allocation and supplier assumptions |
| Power BI source / import static verification | **PASS** | 8 pages, 112 visuals, 51 measures, 18 relationships, 9 imports |
| Power BI Desktop open, refresh, DAX behavior | **NOT VERIFIED** | Requires real Windows Power BI Desktop session |
| Raw-data origin / permission | **ATTRIBUTED** | Original Mendeley files were hash-matched; CC BY 4.0 |

**Project status remains PARTIAL_REPRODUCIBILITY.** The included original historical report is a complete saved Power BI source artifact, and the new model is independently executable; this does *not* imply the original historical SIM engine has been regenerated.

## Current GitHub CI

The [workflow](../.github/workflows/ci.yml) has two scoped jobs:

- **Publication and report integrity:** `python -B prepare_release.py --check` and `python -B configure_powerbi.py --check` check allowlisted files, original hashes, Power BI source structure and nine import paths.
- **Executable Python/SQLite sample:** two runs of `python -B run_pipeline.py --sample` into distinct output directories, then `python -B validate.py --mode public --build build/ci_sample_a --compare-build build/ci_sample_b`. This actually executes the fictional sample and reproducibility validation.

**Check the latest Actions result;** a README badge only reflects the latest current workflow run. Ubuntu GitHub runners do not execute Power BI Desktop or certify historical simulation parity.

## Repeat locally

```powershell
python prepare_release.py --check
python configure_powerbi.py --check
python run_pipeline.py --sample --output-dir build/check_a
python run_pipeline.py --sample --output-dir build/check_b
python validate.py --mode public --build build/check_a --compare-build build/check_b
```

Each output directory must be new. For a full RAW-based reconstruction using NEW_REPLAY_V1, see the [walkthrough](TECHNICAL_WALKTHROUGH.md). Historical-baseline comparison exits `2` when known SIM differences are found; that status is intentionally exposed.

## Power BI acceptance still outstanding

The next owner-side acceptance test, not completed by this publication, is to clone on a different Windows workstation, run `configure_powerbi.py` with Desktop closed, open the native PBIP, refresh nine historical tables, navigate eight pages, test appropriate date/store/product/DC/supplier interactions and compare the reported figures with historical CSVs. Until evidence of that run exists, keep the state **POWER_BI_RUNTIME_NOT_VERIFIED**.

**Publication invariant:** never overwrite original V2 CSVs with NEW_REPLAY_V1 just to force a match; never change the eight genuine screenshots to pretend they are new-simulation outputs. [Source/license notice](../DATA_SOURCES.md).
