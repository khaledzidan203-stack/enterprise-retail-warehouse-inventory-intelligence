"""Generate the nine model datasets in a new isolated build directory."""
import sys
sys.dont_write_bytecode=True
import argparse
import json
from pathlib import Path
from src.python.pipeline import run

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input-dir',type=Path)
    p.add_argument('--reference-dir',type=Path)
    p.add_argument('--policy',type=Path)
    p.add_argument('--output-dir',type=Path,required=True)
    p.add_argument('--sample',action='store_true',help='Generate independent public-safe example inputs')
    p.add_argument('--seed',type=int,default=20261007)
    a=p.parse_args()
    if a.sample and any((a.input_dir,a.reference_dir,a.policy)):p.error('--sample cannot be combined with private input overrides')
    try:r=run(a.output_dir,a.input_dir,a.reference_dir,a.policy,a.sample,a.seed)
    except (OSError,ValueError,KeyError,AssertionError) as e:p.exit(1,f'Pipeline failed; no reference inputs were overwritten: {e}\n')
    print(json.dumps({'status':r['status'],'data_origin':r['data_origin'],'metrics':r['metrics']},default=str,indent=2))
    return 0

if __name__=='__main__':raise SystemExit(main())
