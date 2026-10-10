-- NEW SQLite analytical implementation; not an alleged historical database.
PRAGMA foreign_keys=ON;
CREATE TABLE DimDate(Date TEXT NOT NULL PRIMARY KEY, Year INTEGER NOT NULL, MonthNumber INTEGER NOT NULL CHECK(MonthNumber BETWEEN 1 AND 12));
CREATE TABLE DimSupplier(Supplier TEXT NOT NULL PRIMARY KEY);
CREATE TABLE DimDistributionCenter(DistributionCenter TEXT NOT NULL PRIMARY KEY);
CREATE TABLE DimProduct(ProductNo TEXT NOT NULL PRIMARY KEY, Supplier TEXT NOT NULL REFERENCES DimSupplier, ABCClass TEXT NOT NULL);
CREATE TABLE DimStore(Store TEXT NOT NULL PRIMARY KEY, DistributionCenter TEXT NOT NULL REFERENCES DimDistributionCenter);
CREATE TABLE FactStoreDailyService(
 Date TEXT NOT NULL REFERENCES DimDate, Store TEXT NOT NULL REFERENCES DimStore,
 DemandQty INTEGER NOT NULL CHECK(DemandQty>=0), FulfilledQty INTEGER NOT NULL CHECK(FulfilledQty>=0),
 ShortageQty INTEGER NOT NULL CHECK(ShortageQty>=0), ReturnInflowQty INTEGER NOT NULL CHECK(ReturnInflowQty>=0),
 PRIMARY KEY(Date,Store), CHECK(DemandQty=FulfilledQty+ShortageQty));
CREATE TABLE FactStoreSkuAsOf(
 Store TEXT NOT NULL REFERENCES DimStore, ProductNo TEXT NOT NULL REFERENCES DimProduct,
 AsOfDate TEXT NOT NULL REFERENCES DimDate, EndOnHandQty INTEGER NOT NULL CHECK(EndOnHandQty>=0),
 EndInTransitQty INTEGER NOT NULL CHECK(EndInTransitQty>=0), EndOpenRequestQty INTEGER NOT NULL CHECK(EndOpenRequestQty>=0),
 TrailingGrossUnits84 INTEGER NOT NULL CHECK(TrailingGrossUnits84>=0), ZeroVelocityFlag84 INTEGER NOT NULL CHECK(ZeroVelocityFlag84 IN(0,1)),
 PRIMARY KEY(Store,ProductNo,AsOfDate));
CREATE TABLE FactDCSkuAsOf(
 DistributionCenter TEXT NOT NULL REFERENCES DimDistributionCenter, ProductNo TEXT NOT NULL REFERENCES DimProduct,
 AsOfDate TEXT NOT NULL REFERENCES DimDate, EndOnHandQty INTEGER NOT NULL CHECK(EndOnHandQty>=0),
 EndOnOrderQty INTEGER NOT NULL CHECK(EndOnOrderQty>=0), EndStoreBacklogQty INTEGER NOT NULL CHECK(EndStoreBacklogQty>=0),
 NetInventoryPosition INTEGER NOT NULL, PRIMARY KEY(DistributionCenter,ProductNo,AsOfDate),
 CHECK(NetInventoryPosition=EndOnHandQty+EndOnOrderQty-EndStoreBacklogQty));
CREATE TABLE FactSupplierDCExecution(
 Supplier TEXT NOT NULL REFERENCES DimSupplier, DistributionCenter TEXT NOT NULL REFERENCES DimDistributionCenter,
 OrderedQty INTEGER NOT NULL CHECK(OrderedQty>=0), ReceivedQty INTEGER NOT NULL CHECK(ReceivedQty>=0),
 CancelledQty INTEGER NOT NULL CHECK(CancelledQty>=0), OpenQty INTEGER NOT NULL CHECK(OpenQty>=0),
 PRIMARY KEY(Supplier,DistributionCenter), CHECK(OrderedQty=ReceivedQty+CancelledQty+OpenQty));
CREATE VIEW ServiceKPI AS SELECT SUM(DemandQty) DemandQty,SUM(FulfilledQty) FulfilledQty,SUM(ShortageQty) ShortageQty,
 SUM(ReturnInflowQty) ReturnInflowQty,1.0*SUM(FulfilledQty)/NULLIF(SUM(DemandQty),0) UnitServiceRate FROM FactStoreDailyService;
CREATE VIEW HoldoutKPI AS SELECT SUM(DemandQty) DemandQty,SUM(FulfilledQty) FulfilledQty,SUM(ShortageQty) ShortageQty,
 SUM(ReturnInflowQty) ReturnInflowQty FROM FactStoreDailyService WHERE Date BETWEEN '2026-02-02' AND '2026-04-24';
CREATE VIEW InventoryKPI AS SELECT
 (SELECT SUM(EndOnHandQty) FROM FactStoreSkuAsOf) StoreOnHand,
 (SELECT SUM(EndOnHandQty) FROM FactDCSkuAsOf) DCOnHand,
 (SELECT SUM(EndOnHandQty) FROM FactStoreSkuAsOf WHERE ZeroVelocityFlag84=1) ZeroVelocityUnits84,
 (SELECT COUNT(*) FROM FactStoreSkuAsOf WHERE ZeroVelocityFlag84=1) ZeroVelocityPairs84;
CREATE VIEW DQFailures AS
 SELECT 'ServiceEquation' CheckName,COUNT(*) Failures FROM FactStoreDailyService WHERE DemandQty<>FulfilledQty+ShortageQty
 UNION ALL SELECT 'SupplierEquation',COUNT(*) FROM FactSupplierDCExecution WHERE OrderedQty<>ReceivedQty+CancelledQty+OpenQty
 UNION ALL SELECT 'ZeroVelocityFlag',COUNT(*) FROM FactStoreSkuAsOf WHERE ZeroVelocityFlag84<>(TrailingGrossUnits84=0);
