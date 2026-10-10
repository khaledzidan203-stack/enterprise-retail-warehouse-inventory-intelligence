"""Point the preserved report to this checkout's historical CSVs; no analytics run."""
import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parent
MODEL = ROOT / 'powerbi/Enterprise Retail Inventory Intelligence.SemanticModel/definition/expressions.tmdl'

def configure(check_only=False):
    # Validate the nine original inputs against their existing historical manifests.
    count = 0
    for folder, manifest in [('analytics_v1','analytics_manifest_v1.json'), ('powerbi_model_v1','powerbi_model_manifest_v1.json')]:
        source = ROOT / 'data' / folder
        for artifact in json.loads((source / manifest).read_text(encoding='utf-8-sig'))['artifacts']:
            path = source / artifact['file_name']
            if path.suffix != '.csv' or path.name == 'analytics_metric_contracts_v1.csv':
                continue
            if hashlib.sha256(path.read_bytes()).hexdigest() != artifact['sha256']:
                raise ValueError(f'Historical file changed: {path.name}')
            count += 1
    if count != 9:
        raise ValueError('Expected all nine historical Power BI CSVs')
    if not check_only:
        if os.name == 'nt':
            processes = subprocess.check_output(['tasklist','/FI','IMAGENAME eq PBIDesktop.exe','/FO','CSV'], text=True)
            if 'pbidesktop.exe' in processes.lower():
                raise ValueError('Close Power BI Desktop before configuring DataRoot')
        location = (ROOT / 'data').as_posix().replace('"','""')
        MODEL.write_text(f'expression DataRoot = "{location}" meta [IsParameterQuery=true, Type="Text", IsParameterQueryRequired=true]\n', encoding='utf-8')
    return {'historical_inputs':'PASS','tables':count,'DataRoot':'<checkout>/data','configured':not check_only}

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Verify original inputs without editing any file')
    args = parser.parse_args()
    try:
        print(json.dumps(configure(args.check), indent=2))
    except (OSError,ValueError,KeyError,subprocess.SubprocessError) as error:
        parser.exit(1, f'Power BI configuration failed: {error}\n')
