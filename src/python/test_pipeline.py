"""Portable end-to-end sample, SQL constraints, and negative-path tests."""
import csv
import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch
from src.python import pipeline, simulation, sample_data, validation, ingestion

ROOT=Path(__file__).resolve().parents[2]

class PipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        (ROOT/'build').mkdir(exist_ok=True)
        cls.temp=tempfile.TemporaryDirectory(prefix='test_',dir=ROOT/'build')
        cls.work=Path(cls.temp.name)
        cls.first=cls.work/'first';cls.second=cls.work/'second'
        cls.run_cli(cls.first);cls.run_cli(cls.second)

    @classmethod
    def tearDownClass(cls):
        assert cls.work.resolve().is_relative_to(ROOT/'build')
        cls.temp.cleanup()

    @classmethod
    def run_cli(cls,path):
        command=[sys.executable,'-B',str(ROOT/'run_pipeline.py'),'--sample','--output-dir',str(path)]
        result=subprocess.run(command,cwd=cls.work,capture_output=True,text=True)
        if result.returncode:raise AssertionError(result.stderr)
        return json.loads(result.stdout)

    def test_documented_cli_alternate_cwd_and_sample_baseline(self):
        result=json.loads((self.first/'execution.json').read_text())
        self.assertEqual(result['status'],'ANALYTICAL_PIPELINE_PASS')
        self.assertEqual(result['data_origin'],'SYNTHETIC_PUBLIC_EXAMPLE')
        self.assertEqual(result['metrics'],dict(store_rows=6,dc_rows=6,daily_rows=656,supplier_rows=4,store_onhand=24,dc_onhand=54,returns_full='40',holdout_demand='327',holdout_fulfilled=327,holdout_shortage=0,holdout_returns='10',zero_sales84_units=8,zero_sales84_pairs=2))

    def test_independent_all_rows_windows_conservation_sql(self):
        self.assertEqual(validation.validate_build(self.first)['status'],'ANALYTICAL_PIPELINE_PASS')

    def test_deterministic_every_artifact(self):
        first={p.relative_to(self.first).as_posix():ingestion.file_hash(p) for p in self.first.rglob('*') if p.is_file()}
        second={p.relative_to(self.second).as_posix():ingestion.file_hash(p) for p in self.second.rglob('*') if p.is_file()}
        self.assertEqual(first,second)

    def test_overwrite_and_outside_build_rejected(self):
        for path in (self.first,ROOT/'data/generated',ROOT/'build'):
            with self.assertRaisesRegex(ValueError,'NEW child directory'):pipeline.run(path,sample=True)
        with self.assertRaises(ValueError):sample_data.generate(self.first/'inputs')

    def test_missing_input_clear_nonzero_exit(self):
        p=subprocess.run([sys.executable,'-B',str(ROOT/'run_pipeline.py'),'--input-dir',str(self.work/'missing'),'--output-dir',str(self.work/'invalid')],capture_output=True,text=True)
        self.assertNotEqual(p.returncode,0);self.assertIn('Pipeline failed',p.stderr)

    def test_input_validation_fractional_units_and_duplicate_policy(self):
        for value in ('1.1','NaN','Infinity'):
            with self.assertRaises(ValueError):simulation.integer(value)
        p=self.work/'duplicate.csv'
        p.write_text('Key,Qty\nx,1\nx,2\n')
        with self.assertRaisesRegex(ValueError,'Duplicate input key'):simulation.reference(p,['Key'],['Qty'])
        p.write_text('Key,Key\nx,x\n')
        with self.assertRaisesRegex(ValueError,'Invalid input schema'):simulation.reference(p,['Key'],['Qty'])

    def test_empirical_zero_calendar_and_boundaries(self):
        self.assertEqual(simulation.rolling_quantile([(0,3),(2,1)],3,4,2,1),3)
        self.assertEqual(simulation.rolling_quantile([(0,3)],3,4,1,.5),0)
        self.assertEqual(simulation.rolling_quantile([(0,3)],5,2,2,1),0)
        self.assertEqual(simulation.fraction(7,'x'),simulation.fraction(7,'x'))
        self.assertNotEqual(simulation.fraction(7,'x'),simulation.fraction(8,'x'))

    def test_sql_enforces_pk_fk_null_and_equations(self):
        with closing(sqlite3.connect(':memory:')) as db:
            db.executescript((ROOT/'src/sql/analytics.sql').read_text())
            db.execute("INSERT INTO DimDate VALUES ('2026-01-01',2026,1)")
            db.execute("INSERT INTO DimDistributionCenter VALUES ('D')")
            db.execute("INSERT INTO DimStore VALUES ('S','D')")
            statements=["INSERT INTO DimDate VALUES ('2026-01-01',2026,1)","INSERT INTO DimStore VALUES ('X','NO')", "INSERT INTO DimSupplier VALUES (NULL)","INSERT INTO FactStoreDailyService VALUES ('2026-01-01','S',3,2,0,0)","INSERT INTO FactStoreDailyService VALUES ('2026-01-01','S',1,2,-1,0)"]
            for statement in statements:
                with self.assertRaises(sqlite3.IntegrityError):db.execute(statement)

    def test_negative_opening_and_unreliable_supplier_are_explicit(self):
        inputs=self.work/'scenario_inputs';sample_data.generate(inputs)
        path=inputs/'data/raw'/ingestion.INVENTORY_FILE
        columns,records=validation.rows(path);records[0]['Qty on hand']='-2'
        with path.open('w',newline='') as f:
            w=csv.DictWriter(f,columns);w.writeheader();w.writerows(records)
        path=inputs/'data/synthetic/dc_inventory_policy_v2.csv'
        columns,records=validation.rows(path)
        for r in records:r['OTIFTarget']='0';r['FillRateTarget']='0'
        with path.open('w',newline='') as f:
            w=csv.DictWriter(f,columns);w.writeheader();w.writerows(records)
        output=self.work/'adverse'
        result=pipeline.run(output,inputs/'data/raw',inputs/'data/synthetic',inputs/'config/store_replenishment_policy_v2.json',seed=5)
        self.assertEqual(result['assumptions']['negative_openings_projected_to_zero'],1)
        self.assertEqual(validation.validate_build(output)['status'],'ANALYTICAL_PIPELINE_PASS')
        cohorts=validation.rows(output/'data/analytics_v1/analytics_supplier_dc_execution_v1.csv')[1]
        self.assertGreater(sum(int(r['CancelledQty']) for r in cohorts),0)
        self.assertGreater(sum(int(r['OpenQty']) for r in cohorts),0)
        self.assertEqual(sum(int(r['ReceivedQty']) for r in cohorts),0)

    def test_production_never_reads_historical_references(self):
        original=Path.open
        def guarded(path,*args,**kwargs):
            if path.resolve().is_relative_to(ROOT/'data'):
                raise AssertionError('Sample production accessed private data')
            return original(path,*args,**kwargs)
        with patch.object(Path,'open',guarded):
            result=pipeline.run(self.work/'guarded',sample=True)
        self.assertEqual(result['status'],'ANALYTICAL_PIPELINE_PASS')

    def test_historical_mismatch_is_explicit_and_all_cells_retained(self):
        # Independently generated fixture baseline, never private historical data.
        changed=self.second/'data/analytics_v1/analytics_store_sku_asof_v1.csv'
        original=changed.read_bytes()
        try:
            columns,records=validation.rows(changed)
            records[0]['EndOnHandQty']=str(int(records[0]['EndOnHandQty'])+1)
            with changed.open('w',newline='') as f:
                w=csv.DictWriter(f,columns);w.writeheader();w.writerows(records)
            result=validation.reconcile(self.first,self.second)
            self.assertEqual(result['status'],'PARTIAL_REPRODUCIBILITY')
            self.assertEqual(result['tables']['FactStoreSkuAsOf']['attribute_mismatches'],{'EndOnHandQty':1})
        finally:changed.write_bytes(original)

if __name__=='__main__':unittest.main()
