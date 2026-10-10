"""Canonical orchestration. All production dependencies are explicit inputs."""
import csv
import hashlib
import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from . import ingestion, observed_movements, inventory_entities, reference_dimensions, observed_daily_model, simulation, sql_model, sample_data

FACT_FILES={'FactStoreSkuAsOf':'analytics_store_sku_asof_v1.csv','FactDCSkuAsOf':'analytics_dc_sku_asof_v1.csv','FactStoreDailyService':'analytics_store_daily_service_v1.csv','FactSupplierDCExecution':'analytics_supplier_dc_execution_v1.csv'}
FACT_SCHEMAS=dict(zip(FACT_FILES,[simulation.STORE_COLUMNS,simulation.DC_COLUMNS,simulation.DAILY_COLUMNS,simulation.SUPPLIER_COLUMNS]))

def json_file(path, value):
    Path(path).write_text(json.dumps(value,indent=2,sort_keys=True,default=str)+'\n',encoding='utf-8')

def csv_file(path, columns, rows):
    path.parent.mkdir(parents=True,exist_ok=True)
    def scalar(value):
        if value is None:return ''
        if isinstance(value,(float,Decimal)) and not isinstance(value,int):return format(value,'.8f')
        return str(value)
    with path.open('x',encoding='utf-8',newline='') as f:
        w=csv.writer(f,lineterminator='\n');w.writerow(columns)
        for row in rows:
            w.writerow(scalar(row[k]) for k in columns)

def normalized(raw_dir, kind):
    filename=ingestion.SALES_FILE if kind=='sales' else ingestion.INVENTORY_FILE
    with (raw_dir/filename).open(encoding='utf-8-sig',newline='') as f:
        yield from ingestion.read_rows(f,kind,'data/raw/'+filename)

def run(output, raw_dir=None, reference_dir=None, policy=None, sample=False, seed=20261007):
    project=Path(__file__).resolve().parents[2]
    output=Path(output).resolve()
    # Restrict generated writes to one controlled tree and never overwrite runs.
    if not output.is_relative_to(project/'build') or output==project/'build' or output.exists():
        raise ValueError('Output must be a NEW child directory of project/build; existing data will never be overwritten')
    output.mkdir(parents=True)
    if sample:
        sample_data.generate(output/'inputs')
        raw_dir=output/'inputs/data/raw';reference_dir=output/'inputs/data/synthetic';policy=output/'inputs/config/store_replenishment_policy_v2.json'
    else:
        raw_dir=Path(raw_dir or project/'data/raw').resolve()
        reference_dir=Path(reference_dir or project/'data/synthetic').resolve()
        policy=Path(policy or project/'config/store_replenishment_policy_v2.json').resolve()
    inputs=[raw_dir/ingestion.SALES_FILE,raw_dir/ingestion.INVENTORY_FILE,Path(policy)] + [reference_dir/f for f in reference_dimensions.SCHEMAS] + [reference_dir/f for f in ['dc_inventory_policy_v2.csv','dc_opening_inventory_v2.csv']]
    hashes={p.name:ingestion.file_hash(p) for p in inputs}
    movement=observed_movements.aggregate_movements(normalized(raw_dir,'sales'))
    contracts=inventory_entities.profile_sources(normalized(raw_dir,'sales'),normalized(raw_dir,'inventory'),movement)
    supplied={}
    for filename in reference_dimensions.SCHEMAS:
        with (reference_dir/filename).open(encoding='utf-8-sig',newline='') as f:
            reader=csv.DictReader(f)
            if not reader.fieldnames or len(reader.fieldnames)!=len(set(reader.fieldnames)):raise ValueError('Duplicate/missing governed headers')
            supplied[filename]=list(reader)
    dims=reference_dimensions.assemble_dimensions(contracts,supplied)
    calendar=observed_daily_model.source_calendar(normalized(raw_dir,'sales'))
    daily=observed_daily_model.assemble_daily_model(movement,dims,calendar)
    replay=simulation.replay(contracts,movement,dims,daily,reference_dir,policy,seed)
    tables={t.name:list(t.records()) for t in dims.tables+(daily.dates,)}
    schemas={t.name:list(t.columns) for t in dims.tables+(daily.dates,)}
    for name,key in zip(FACT_FILES,['store','dc','daily','supplier']):
        tables[name]=replay[key];schemas[name]=FACT_SCHEMAS[name]
    if sample:
        for rows in (tables['FactStoreSkuAsOf'],tables['FactStoreDailyService']):
            for row in rows:
                row['DemandProvenance']='SYNTHETIC_EXAMPLE_SOURCE'
                row['ReturnProvenance']='SYNTHETIC_EXAMPLE_SOURCE'
    for name,rows in tables.items():
        path=output/'data'/('analytics_v1' if name in FACT_FILES else 'powerbi_model_v1')/(FACT_FILES.get(name,name+'.csv'))
        csv_file(path,schemas[name],rows)
    for key in ['store_controls','dc_controls','purchase_lines']:
        rows=replay[key]
        if rows:csv_file(output/'evidence'/(key+'.csv'),list(rows[0]),rows)
    columns=['Date','Event','Location','Product','Qty','Reference','Provenance']
    if sample:
        replay['events']=[(*r[:6], 'SYNTHETIC_EXAMPLE_SOURCE' if r[6]=='OBS' else r[6]) for r in replay['events']]
    csv_file(output/'evidence/events.csv',columns,(dict(zip(columns,r)) for r in replay['events']))
    sql=sql_model.build(output/'analytics.sqlite',tables)
    if hashes!={p.name:ingestion.file_hash(p) for p in inputs}:raise ValueError('Inputs changed during pipeline execution')
    hold=[r for r in replay['daily'] if date(2026,2,2)<=r['Date']<=date(2026,4,24)]
    metrics={'store_rows':len(replay['store']),'dc_rows':len(replay['dc']),'daily_rows':len(replay['daily']),'supplier_rows':len(replay['supplier']),
        'store_onhand':sum(r['EndOnHandQty'] for r in replay['store']),'dc_onhand':sum(r['EndOnHandQty'] for r in replay['dc']),
        'returns_full':sum(r['ReturnInflowQty'] for r in replay['daily']),
        'holdout_demand':sum(r['DemandQty'] for r in hold),'holdout_fulfilled':sum(r['FulfilledQty'] for r in hold),
        'holdout_shortage':sum(r['ShortageQty'] for r in hold),'holdout_returns':sum(r['ReturnInflowQty'] for r in hold),
        'zero_sales84_units':sum(r['EndOnHandQty'] for r in replay['store'] if r['ZeroVelocityFlag84']),
        'zero_sales84_pairs':sum(r['ZeroVelocityFlag84'] for r in replay['store'])}
    result={'status':'ANALYTICAL_PIPELINE_PASS','historical_equivalence':'NOT_CLAIMED_NEW_REPLAY_V1','data_origin':'SYNTHETIC_PUBLIC_EXAMPLE' if sample else 'PRIVATE_INPUTS_RIGHTS_NOT_CLEARED',
        'asof':str(calendar.end),'seed':seed,'schemas':schemas,'row_counts':{k:len(v) for k,v in tables.items()},'metrics':metrics,
        'assumptions':replay['assumptions'],'input_sha256':hashes,'sql':sql,
        'generated_sha256':{str(p.relative_to(output)).replace('\\','/'):ingestion.file_hash(p) for p in sorted((output/'data').rglob('*.csv'))}}
    json_file(output/'execution.json',result)
    return result
