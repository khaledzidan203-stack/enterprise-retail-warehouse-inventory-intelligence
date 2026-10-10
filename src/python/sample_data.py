"""Independently authored, deterministic synthetic fixtures; no private reads."""
import csv
import json
from datetime import date, timedelta
from pathlib import Path
from . import ingestion, reference_dimensions

def write_csv(path, columns, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x',encoding='utf-8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=columns,lineterminator='\n');w.writeheader();w.writerows(rows)

def generate(root):
    root=Path(root)
    if root.exists():
        raise ValueError('Synthetic input destination must not already exist')
    start,end=date(2025,6,1),date(2026,4,24)
    products=['DEMO-P1','DEMO-P2','DEMO-P3'];stores=['DEMO-S1','DEMO-S2']
    supplier={p:'DEMO-V1' if p!='DEMO-P2' else 'DEMO-V2' for p in products}
    def common(p,s):
        return {'Supplier':supplier[p],'Product No':p,'Product Description':f'Synthetic example {p}',
                'Product Division':'Demo Division','Product Category':'Demo Category','Product Subcategory':'Demo Subcategory',
                'Product Segment':'Demo Segment','Store':s,'Sales Channel':'Synthetic Channel'}
    sales=[];inventory=[]
    for i in range((end-start).days+1):
        for j,s in enumerate(stores):
            p=products[(i+j)%2]
            row=common(p,s)|{'Transaction Date':str(start+timedelta(days=i)),'Sales Type':'Full Price','Is Return':'0','Reason of Return':'',
                'Qty Sold':str(1+(i+j)%3),'Sales Amount':str(10*(1+(i+j)%3)),'Cogs':str(4*(1+(i+j)%3)),'Number of Transactions':'1'}
            sales.append(row)
            if i%17==0:
                sales.append(row|{'Is Return':'1','Qty Sold':'-1','Sales Amount':'-10','Cogs':'-4'})
    # Two explicit zero transactions, including a key already covered by demand.
    sales.extend([sales[0]|{'Qty Sold':'0','Sales Amount':'0','Cogs':'0'} for _ in range(2)])
    for s in stores:
        for p in products:
            inventory.append(common(p,s)|{'Start Date':str(start),'End Date':'9999-12-31','Stock Status':'Full Price','Store Type':'Demo Store',
                'Qty on hand':'4','Stocks Selling Amount':'40','Cost of Stocks':'16','Stock Unit Selling Price':'10','Stock Unit Cost Price':'4'})
    write_csv(root/'data/raw'/ingestion.SALES_FILE,list(ingestion.SALES_COLUMNS),sales)
    write_csv(root/'data/raw'/ingestion.INVENTORY_FILE,list(ingestion.INVENTORY_COLUMNS),inventory)
    geo=[dict(zip(reference_dimensions.SCHEMAS['store_geography.csv'],[s,f'DEMO-R{i+1}',f'Demo Region {i+1}',f'DEMO-C{i+1}',f'DEMO-DC{i+1}',1])) for i,s in enumerate(stores)]
    policy=[dict(zip(reference_dimensions.SCHEMAS['product_supply_policy.csv'],[p,supplier[p],'Demo Division','A' if p=='DEMO-P1' else 'B',2,4,1])) for p in products]
    profiles=[dict(zip(reference_dimensions.SCHEMAS['supplier_operational_profile.csv'],[v,'Demo',sum(x==v for x in supplier.values()),3,'0.8','0.85',1])) for v in sorted(set(supplier.values()))]
    centers=[dict(zip(reference_dimensions.SCHEMAS['distribution_centers.csv'],[f'DEMO-DC{i}',f'Demo Center {i}',f'DEMO-R{i}',f'Demo Region {i}',1])) for i in (1,2)]
    for filename,rows in zip(reference_dimensions.SCHEMAS,[geo,policy,profiles,centers]):
        write_csv(root/'data/synthetic'/filename,reference_dimensions.SCHEMAS[filename],rows)
    dc_policy=[];opening=[]
    for dc in ('DEMO-DC1','DEMO-DC2'):
        for p in products:
            dc_policy.append({'DistributionCenter':dc,'Product No':p,'Supplier':supplier[p],'ReorderPointQty':4,'TargetStockQty':12,
                'CasePack':2,'MOQ':4,'BaseLeadTimeDays':3,'ReviewCycleDays':2,'OTIFTarget':'0.8','FillRateTarget':'0.85'})
            opening.append({'DistributionCenter':dc,'Product No':p,'OpeningInventoryQty':12,'AsOfDate':str(start)})
    write_csv(root/'data/synthetic/dc_inventory_policy_v2.csv',list(dc_policy[0]),dc_policy)
    write_csv(root/'data/synthetic/dc_opening_inventory_v2.csv',list(opening[0]),opening)
    config={'policy_id':'DEMO_NEW_REPLAY_INPUT','review':{'demand_lookback_days':84,'recalibration_days':7,'dc_to_store_lead_time_days':1},
        'mature_replenishment':{'abc_service_quantiles':{'A':0.99,'B':0.98,'C':0.95},'reorder_point':{'demand_window_days':2,'minimum_units':1},'target_stock':{'demand_window_days':4,'minimum_units':1}}}
    (root/'config').mkdir()
    (root/'config/store_replenishment_policy_v2.json').write_text(json.dumps(config,indent=2,sort_keys=True)+'\n',encoding='utf-8')
