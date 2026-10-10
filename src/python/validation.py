"""Independent generated-artifact checks. Historical inputs are validation-only."""
import csv
import json
import re
import sqlite3
from contextlib import closing
from collections import Counter, defaultdict
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from . import ingestion, pipeline, sql_model

KEYS = {'DimDate':['Date'], 'DimStore':['Store'], 'DimProduct':['Product No'],
        'DimSupplier':['Supplier'], 'DimDistributionCenter':['DistributionCenter'],
        'FactStoreSkuAsOf':['Store','Product No'], 'FactDCSkuAsOf':['DistributionCenter','Product No'],
        'FactStoreDailyService':['Date','Store'], 'FactSupplierDCExecution':['Supplier','DistributionCenter']}
EXPECTED = dict(store_rows=50447, dc_rows=9304, daily_rows=12706, supplier_rows=120,
    store_onhand=68734, dc_onhand=53030, returns_full=7547, holdout_demand=30000,
    holdout_fulfilled=29363, holdout_shortage=637, holdout_returns=1738,
    zero_sales84_units=45021, zero_sales84_pairs=31776)

def rows(path):
    with Path(path).open(encoding='utf-8-sig', newline='') as f:
        reader=csv.DictReader(f)
        if not reader.fieldnames or len(set(reader.fieldnames)) != len(reader.fieldnames):
            raise AssertionError(f'Invalid CSV header: {path}')
        result=list(reader)
        if any(None in r or None in r.values() for r in result):
            raise AssertionError(f'Ragged CSV: {path}')
        return reader.fieldnames,result

def table_path(root,name):
    return Path(root)/('analytics_v1' if name in pipeline.FACT_FILES else 'powerbi_model_v1')/pipeline.FACT_FILES.get(name,name+'.csv')

def keyed(data, keys):
    result={}
    for row in data:
        key=tuple(row[k] for k in keys)
        if not all(key) or key in result:raise AssertionError(f'Duplicate/null grain: {key}')
        result[key]=row
    return result

def equal(a,b):
    if a==b:return True
    try:return abs(Decimal(a)-Decimal(b)) <= Decimal('0.00000001')
    except (InvalidOperation,TypeError):return False

def validate_build(build):
    build=Path(build)
    execution=json.loads((build/'execution.json').read_text())
    tables={}
    for name,columns in execution['schemas'].items():
        path=table_path(build/'data',name)
        header,records=rows(path)
        assert header==columns, f'Schema mismatch: {name}'
        if name in pipeline.FACT_SCHEMAS:assert header==pipeline.FACT_SCHEMAS[name]
        assert len(records)==execution['row_counts'][name]
        keyed(records,KEYS[name]);tables[name]=records
        assert ingestion.file_hash(path)==execution['generated_sha256'][path.relative_to(build).as_posix()]
    assert set(tables)==set(KEYS)
    sets={n:{r[KEYS[n][0]] for r in tables[n]} for n in KEYS if n.startswith('Dim')}
    for name,records in tables.items():
        for row in records:
            for column,dim in [('Store','DimStore'),('Product No','DimProduct'),('Supplier','DimSupplier'),('DistributionCenter','DimDistributionCenter'),('AsOfDate','DimDate'),('Date','DimDate')]:
                if column in row:assert row[column] in sets[dim], f'Orphan: {name}.{column}'
    dates=sorted(sets['DimDate'])
    assert len(dates)==(date.fromisoformat(dates[-1])-date.fromisoformat(dates[0])).days+1
    for name in ('FactStoreSkuAsOf','FactDCSkuAsOf'):
        for row in tables[name]:
            assert row['AsOfDate']==dates[-1]
            assert dates[0]<=row['StateDate']<=dates[-1]
            for col in ('EndOnHandQty','EndInTransitQty','EndOpenRequestQty','EndOnOrderQty','EndStoreBacklogQty'):
                if col in row:assert int(row[col])>=0
    store=keyed(tables['FactStoreSkuAsOf'],KEYS['FactStoreSkuAsOf'])
    dc=keyed(tables['FactDCSkuAsOf'],KEYS['FactDCSkuAsOf'])
    controls=rows(build/'evidence/store_controls.csv')[1]
    assert set(keyed(controls,['Store','Product']))==set(store)
    for r in controls:
        v={k:int(x) for k,x in r.items() if k not in ('Store','Product')}
        assert v['Opening']+v['Receipts']+v['Returns']-v['Fulfilled']==v['Closing']
        assert v['Shipped']-v['Receipts']==v['InTransit']
        assert v['Requested']-v['Shipped']==v['Backlog']
        target=store[(r['Store'],r['Product'])]
        for a,b in [('Closing','EndOnHandQty'),('InTransit','EndInTransitQty'),('Backlog','EndOpenRequestQty'),('Returns','FullHistoryCustomerReturnQty')]:assert v[a]==int(target[b])
    dcontrols=rows(build/'evidence/dc_controls.csv')[1]
    assert set(keyed(dcontrols,['DistributionCenter','Product']))==set(dc)
    for r in dcontrols:
        v={k:int(x) for k,x in r.items() if k not in ('DistributionCenter','Product')}
        assert v['Opening']+v['Receipts']-v['Shipped']==v['Closing']
        assert v['Ordered']-v['Receipts']-v['Cancelled']==v['Open']
        target=dc[(r['DistributionCenter'],r['Product'])]
        assert v['Closing']==int(target['EndOnHandQty']) and v['Open']==int(target['EndOnOrderQty'])
        assert int(target['NetInventoryPosition'])==v['Closing']+v['Open']-int(target['EndStoreBacklogQty'])
    assert sum(int(r['Shipped']) for r in controls)==sum(int(r['Shipped']) for r in dcontrols)
    events=rows(build/'evidence/events.csv')[1]
    demand=defaultdict(list); returns=Counter(); event_daily=defaultdict(Counter); event_totals=Counter()
    for e in events:
        assert dates[0]<=e['Date']<=dates[-1] and int(e['Qty'])>=0
        key=(e['Location'],e['Product']); qty=int(e['Qty']); event_totals[e['Event']]+=qty
        if e['Event']=='GROSS_DEMAND':demand[key].append((e['Date'],qty))
        if e['Event']=='CUSTOMER_RETURN':returns[key]+=qty
        if e['Event'] in ('GROSS_DEMAND','CUSTOMER_RETURN','STORE_FULFILL'):event_daily[(e['Date'],e['Location'])][e['Event']]+=qty
    assert set(event_daily)==set(keyed(tables['FactStoreDailyService'],['Date','Store']))
    for r in tables['FactStoreDailyService']:
        d,f,s,ret=[Decimal(r[k]) for k in ('DemandQty','FulfilledQty','ShortageQty','ReturnInflowQty')]
        assert d==f+s and min(d,f,s,ret)>=0
        assert (r['UnitServiceRate']=='' if d==0 else equal(r['UnitServiceRate'],str(f/d)))
        e=event_daily[(r['Date'],r['Store'])]
        assert (d,f,ret)==(e['GROSS_DEMAND'],e['STORE_FULFILL'],e['CUSTOMER_RETURN'])
    for key,r in store.items():
        history=demand[key]
        assert int(r['FullHistoryGrossDemandQty'])==sum(q for _,q in history)
        assert int(r['FullHistoryCustomerReturnQty'])==returns[key]
        assert r['FirstPositiveDemandDate']==(min(t for t,q in history) if history else '')
        assert r['LastPositiveDemandDate']==(max(t for t,q in history) if history else '')
        for window in (28,56,84):
            cutoff=(date.fromisoformat(dates[-1])-timedelta(days=window-1)).isoformat()
            gross=sum(q for t,q in history if t>=cutoff)
            assert int(r[f'TrailingGrossUnits{window}'])==gross
            assert int(r[f'ZeroVelocityFlag{window}'])==int(gross==0)
            assert (r[f'CoverageDays{window}']=='' if gross==0 else equal(r[f'CoverageDays{window}'],str(Decimal(r['EndOnHandQty'])*window/gross)))
    lines=rows(build/'evidence/purchase_lines.csv')[1] if (build/'evidence/purchase_lines.csv').exists() else []
    keyed(lines,['POLineID']);cohorts=defaultdict(list)
    for r in lines:
        assert int(r['OrderedQty'])==sum(int(r[k]) for k in ('ReceivedQty','CancelledQty','OpenQty'))
        assert min(int(r[k]) for k in ('OrderedQty','ReceivedQty','CancelledQty','OpenQty'))>=0
        cohorts[(r['Supplier'],r['DistributionCenter'])].append(r)
    for r in tables['FactSupplierDCExecution']:
        group=cohorts[(r['Supplier'],r['DistributionCenter'])]
        assert int(r['POLines'])==len(group)
        assert int(r['DistinctPOHeaders'])==len({x['PONumber'] for x in group})
        for col in ('OrderedQty','ReceivedQty','CancelledQty','OpenQty'):assert int(r[col])==sum(int(x[col]) for x in group)
        assert (r['ReceivedToOrderedRatio']=='' if int(r['OrderedQty'])==0 else equal(r['ReceivedToOrderedRatio'],str(Decimal(r['ReceivedQty'])/Decimal(r['OrderedQty']))))
    with closing(sqlite3.connect(f'file:{(build/"analytics.sqlite").as_posix()}?mode=ro',uri=True)) as db:
        assert not db.execute('PRAGMA foreign_key_check').fetchall()
        assert not db.execute('SELECT * FROM DQFailures WHERE Failures<>0').fetchall()
        for name,columns in sql_model.PROJECTIONS.items():
            expected={tuple(r[c] if c in {'Date','AsOfDate','Store','Product No','Supplier','DistributionCenter','ABCClass'} else int(Decimal(r[c])) for c in columns) for r in tables[name]}
            assert expected==set(db.execute(f'SELECT * FROM {name}')),f'SQL row mismatch {name}'
        hold=db.execute('SELECT * FROM HoldoutKPI').fetchone()
        assert tuple(int(Decimal(str(execution['metrics'][k]))) for k in ('holdout_demand','holdout_fulfilled','holdout_shortage','holdout_returns'))==hold
    return {'status':'ANALYTICAL_PIPELINE_PASS','tables':len(tables),'grains':{n:len(r) for n,r in tables.items()},'event_rows':len(events),'purchase_lines':len(lines),'sql_row_reconciliation':'PASS'}

def reconcile(build, baseline_root):
    """Compare all cells, retaining every exception in an isolated build CSV."""
    build=Path(build); baseline_root=Path(baseline_root)
    out=build/'evidence/historical_differences.csv'
    summaries={}
    with out.open('w',encoding='utf-8',newline='') as f:
        writer=csv.writer(f);writer.writerow(['Table','Key','Column','Generated','Historical','DifferenceType'])
        for name,keys in KEYS.items():
            h,a=rows(table_path(build/'data',name));rh,b=rows(table_path(baseline_root/'data',name))
            assert h==rh,f'Historical schema mismatch: {name}'
            a,b=keyed(a,keys),keyed(b,keys);missing=set(b)-set(a);extra=set(a)-set(b);counts=Counter();changed=set()
            for k in sorted(missing):writer.writerow([name,json.dumps(k),'*','',json.dumps(b[k],sort_keys=True),'MISSING_KEY'])
            for k in sorted(extra):writer.writerow([name,json.dumps(k),'*',json.dumps(a[k],sort_keys=True),'','EXTRA_KEY'])
            for k in sorted(set(a)&set(b)):
                for col in h:
                    if not equal(a[k][col],b[k][col]):
                        counts[col]+=1;changed.add(k);writer.writerow([name,json.dumps(k),col,a[k][col],b[k][col],'ATTRIBUTE'])
            summaries[name]={'generated_rows':len(a),'historical_rows':len(b),'missing_keys':len(missing),'extra_keys':len(extra),'changed_common_rows':len(changed),'attribute_mismatches':dict(counts)}
    metrics=json.loads((build/'execution.json').read_text())['metrics']
    compared={k:{'expected':v,'generated':metrics[k],'delta':str(Decimal(str(metrics[k]))-v)} for k,v in EXPECTED.items()}
    matched=all(not (r['missing_keys'] or r['extra_keys'] or r['changed_common_rows']) for r in summaries.values()) and all(Decimal(r['delta'])==0 for r in compared.values())
    result={'status':'HISTORICAL_MATCH' if matched else 'PARTIAL_REPRODUCIBILITY','baseline':'Final V2 simulation projected into analytics_v1 and powerbi_model_v1; integrated V1 is a separate superseded scenario, not this oracle','tables':summaries,'metrics':compared,'all_differences':'evidence/historical_differences.csv','numeric_tolerance':'1e-8; quantities integral and exact'}
    pipeline.json_file(build/'historical_reconciliation.json',result)
    return result

def powerbi_static(root, build=None):
    root=Path(root);pbi=root/'powerbi';prefix='Enterprise Retail Inventory Intelligence'
    model=pbi/(prefix+'.SemanticModel')/'definition';report=pbi/(prefix+'.Report')/'definition'
    if not model.exists():return {'status':'NOT_VERIFIED','reason':'Power BI artifacts excluded pending publication rights','runtime':'POWER_BI_RUNTIME_NOT_VERIFIED'}
    expressions=(model/'expressions.tmdl').read_text(encoding='utf-8-sig')
    assert 'expression DataRoot =' in expressions and 'IsParameterQuery=true' in expressions
    assert 'ref expression DataRoot' in (model/'model.tmdl').read_text(encoding='utf-8-sig')
    for name in KEYS:
        text=(model/'tables'/(name+'.tmdl')).read_text(encoding='utf-8-sig')
        expected=table_path(Path('.'),name).as_posix()
        assert f'File.Contents(DataRoot & "/{expected}")' in text
        assert len(re.findall(r'File\.Contents\(',text))==1
        if build:
            header=rows(table_path(Path(build)/'data',name))[0]
            cols=re.findall(r'^\s+sourceColumn: (.+)$',text,re.M)
            assert cols==header,f'TMDL schema {name}'
    pages=list((report/'pages').glob('*/page.json'));visuals=list((report/'pages').glob('*/visuals/*/visual.json'))
    assert len(pages)==8 and len(visuals)==112
    definitions={}
    for p in (model/'tables').glob('*.tmdl'):
        text=p.read_text(encoding='utf-8-sig')
        names=re.findall(r'^\s+(?:column|measure) (\x27[^\x27]+\x27|[^\n=]+?)(?: =[^\n]*)?\r?$',text,re.M)
        definitions[p.stem]={n.strip().strip("'") for n in names}
    bound=0
    def check(x):
        nonlocal bound
        if isinstance(x,dict):
            for typ in ('Column','Measure'):
                if typ in x and isinstance(x[typ],dict):
                    v=x[typ];entity=v.get('Expression',{}).get('SourceRef',{}).get('Entity');prop=v.get('Property')
                    if entity and prop:
                        assert entity in definitions and prop in definitions[entity],f'Stale binding {entity}.{prop}'
                        bound+=1
            for v in x.values():check(v)
        elif isinstance(x,list):
            for v in x:check(v)
    for p in pages+visuals:check(json.loads(p.read_text(encoding='utf-8-sig')))
    measure_count=sum(len(re.findall(r'^\s+measure ',p.read_text(encoding='utf-8-sig'),re.M)) for p in (model/'tables').glob('*.tmdl'))
    assert measure_count==51
    return {'status':'STATIC_PASS','pages':len(pages),'visuals':len(visuals),'measures':measure_count,'checked_bindings':bound,'runtime':'POWER_BI_RUNTIME_NOT_VERIFIED'}
