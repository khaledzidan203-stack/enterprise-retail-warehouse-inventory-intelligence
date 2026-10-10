"""Unified validation: private or public tests, generated data, PBI, release checks."""
import sys
sys.dont_write_bytecode=True
import argparse
import json
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'src/python'))
from src.python import validation, pipeline

def flatten(suite):
    for test in suite:
        if isinstance(test,unittest.TestSuite):yield from flatten(test)
        else:yield test

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--mode',choices=['public','private'],default='public')
    p.add_argument('--build',type=Path,required=True)
    p.add_argument('--baseline-root',type=Path)
    p.add_argument('--compare-build',type=Path)
    a=p.parse_args()
    build=a.build.resolve()
    if not build.is_relative_to(ROOT/'build') or not (build/'execution.json').is_file():p.error('--build must be an existing generated build')
    suite=unittest.defaultTestLoader.discover(str(ROOT/'src/python'),pattern='test_*.py')
    selected=[];excluded=[]
    for test in flatten(suite):
        if a.mode=='public' and test.__class__.__name__ in ('ReferenceTests','SourceReferenceTests'):
            excluded.append(test.id())
        else:selected.append(test)
    result=unittest.TextTestRunner(verbosity=2).run(unittest.TestSuite(selected))
    report={'tests':{'run':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),'private_tests_not_verified':excluded},'mode':a.mode}
    try:
        if not result.wasSuccessful():raise AssertionError('Automated test suite failed')
        report['analytical']=validation.validate_build(build)
        report['powerbi']=validation.powerbi_static(ROOT,build)
        if (ROOT/'release_manifest.json').exists():
            from prepare_release import inspect_release
            report['publication']=inspect_release(ROOT)
        if a.compare_build:
            other=a.compare_build.resolve();files=[]
            for prefix in ('data','evidence'):
                files.extend(p.relative_to(build) for p in (build/prefix).rglob('*.csv') if p.name!='historical_differences.csv')
            from src.python.ingestion import file_hash
            assert all(file_hash(build/f)==file_hash(other/f) for f in files),'Nondeterministic generated CSV'
            for name in ('execution.json','analytics.sqlite'):assert file_hash(build/name)==file_hash(other/name)
            report['determinism']={'status':'PASS','compared_artifacts':len(files)+2}
        if a.baseline_root:
            if a.mode!='private':raise ValueError('Historical comparison requires --mode private')
            report['historical']=validation.reconcile(build,a.baseline_root.resolve())
        report['status']='PARTIAL_REPRODUCIBILITY' if report.get('historical',{}).get('status')=='PARTIAL_REPRODUCIBILITY' else 'ANALYTICAL_PIPELINE_PASS'
    except (AssertionError,ValueError,OSError,KeyError) as e:
        report['status']='FAILED';report['error']=str(e)
    pipeline.json_file(build/'validation.json',report)
    print(json.dumps(report,indent=2))
    return 1 if report['status']=='FAILED' else 2 if report['status']=='PARTIAL_REPRODUCIBILITY' else 0

if __name__=='__main__':raise SystemExit(main())
