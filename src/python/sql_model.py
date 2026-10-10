"""Execute checked-in SQL and independently reconcile its generated-data KPIs."""
import sqlite3
from contextlib import closing
from pathlib import Path

PROJECTIONS={
 'DimDate':['Date','Year','MonthNumber'], 'DimSupplier':['Supplier'], 'DimDistributionCenter':['DistributionCenter'],
 'DimProduct':['Product No','Supplier','ABCClass'], 'DimStore':['Store','DistributionCenter'],
 'FactStoreDailyService':['Date','Store','DemandQty','FulfilledQty','ShortageQty','ReturnInflowQty'],
 'FactStoreSkuAsOf':['Store','Product No','AsOfDate','EndOnHandQty','EndInTransitQty','EndOpenRequestQty','TrailingGrossUnits84','ZeroVelocityFlag84'],
 'FactDCSkuAsOf':['DistributionCenter','Product No','AsOfDate','EndOnHandQty','EndOnOrderQty','EndStoreBacklogQty','NetInventoryPosition'],
 'FactSupplierDCExecution':['Supplier','DistributionCenter','OrderedQty','ReceivedQty','CancelledQty','OpenQty']}

def build(path, tables):
    path=Path(path)
    if path.exists():raise ValueError('SQLite output must be new')
    with closing(sqlite3.connect(path)) as db, db:
        db.executescript((Path(__file__).resolve().parents[1]/'sql/analytics.sql').read_text(encoding='utf-8'))
        for name,columns in PROJECTIONS.items():
            values=[]
            for row in tables[name]:
                values.append(tuple(str(row[c]) if c in {'Date','AsOfDate','Store','Product No','Supplier','DistributionCenter','ABCClass'} else int(row[c]) for c in columns))
            db.executemany(f'INSERT INTO {name} VALUES ({",".join("?" for _ in columns)})',values)
        foreign=db.execute('PRAGMA foreign_key_check').fetchall()
        errors=db.execute('SELECT * FROM DQFailures WHERE Failures<>0').fetchall()
        service=db.execute('SELECT DemandQty,FulfilledQty,ShortageQty,ReturnInflowQty FROM ServiceKPI').fetchone()
        expected=tuple(sum(int(r[c]) for r in tables['FactStoreDailyService']) for c in ['DemandQty','FulfilledQty','ShortageQty','ReturnInflowQty'])
        inventory=db.execute('SELECT * FROM InventoryKPI').fetchone()
        store=tables['FactStoreSkuAsOf'];dc=tables['FactDCSkuAsOf']
        inventory_expected=(sum(r['EndOnHandQty'] for r in store),sum(r['EndOnHandQty'] for r in dc),sum(r['EndOnHandQty'] for r in store if r['ZeroVelocityFlag84']),sum(r['ZeroVelocityFlag84'] for r in store))
        if foreign or errors or service!=expected or inventory!=inventory_expected:raise AssertionError('SQL/Python reconciliation failed')
        for name in tables:
            if db.execute(f'SELECT COUNT(*) FROM {name}').fetchone()[0]!=len(tables[name]):raise AssertionError('SQL row count mismatch')
        return {'status':'PASS','foreign_key_errors':foreign,'dq_errors':errors,'service_totals':service,'inventory_totals':inventory,'tables':len(tables)}
