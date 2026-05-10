"""
Import Bosch Appliances to database
"""

from sqlalchemy import create_engine, text

DATABASE_URL = "postgresql://postgres.mcexfcjowunsmtilvepc:techmynt2025@aws-1-eu-west-1.pooler.supabase.com:5432/postgres"
TENANT_ID = "7"

# Bosch appliances data
bosch_data = [
    # Product Name, Low Series, Low Price, Mid Series, Mid Price, High Series, High Price
    ("HOB 90cm Gas", "PCR9A5I90", "S6", 563, "PPM9A6I40", "S6", 671, None, None, None),
    ("HOB 75cm Gas", "PGQ7B5K90/PPQ7A6I40", "S4", 365, "PPQ7A6I40", "S6", 467, "PCQ7A5I90", "S6", 431),
    ("HOB 60 cm Gas", "PCP6A5I90", "S2", 304, "PNP6B6K40", "S4", 325, "PCP6A6I90", "S6", 327),
    ("60 cm Induction", "PUG61RAA5B", "S2", 262, "PIE631BB5E", "S4", 469, "PIX631HC1E", "S6", 668),
    ("80cm Induction", "PIV831HB1E", "S6", 869, "PXV831HC1E", "S6", 917, "PXY83KHC1E", "S6", 1514),
    
    ("Single Oven - Eco", "HQA534BB3B", "S4", 378, "HBG7341B1B", "S8", 718, None, None, None),
    ("Single Oven - Pyro", "HQA574BB3B", "S4", 439, "HBG7741B1B", "S8", 827, "HBG7764B1B", "S8", 1329),
    
    ("Hood 60cm", "DWB64BC50B", "S2", 262, "DWB66DM50B", "S4", 429, None, None, None),
    ("Hood 90cm", "DWB94BC50B", "S2", 433, "DWB96DM50B", "S4", 538, "DWK91LT60B", "S8", 998),
    ("Hood Integrated 60cm", "DEM66AC00B", "S2", 167, None, None, None, "DBB67AM60B", "S6", 622),
    ("Hood Integrated 90cm", None, None, None, None, None, None, "DBB97AM60B", "S6", 639),
    ("Hood Downdraft 80cm", None, None, None, None, None, None, "DDW88MM60B", "S8", 2592),
    
    ("Microwave", "BFL523MB0B", "S4", 359, "BFL7221B1B", "S8", 725, "CEG732XB1B", "S8", 863),
    ("Combi M/Oven", "CMA583MB0B", "S4", 671, "CMG7241B1B", "S8", 1058, "CMG7761B1B", "S8", 1726),
    ("Warming Drawer", None, None, None, "BIC510NB0", "S6", 369, "BID7101B1B", "S8", 619),
    
    ("Fridge", "KIR81NSE0G", "S2", 819, "KIR81VFE0G", "S4", 872, "KIR81ADD0G", "S6", 1067),
    ("Freezer", None, None, None, "GIN81VEE0G", "S4", 1072, None, None, None),
    
    ("Fridge / Freezer", "KIN85NSE0G", "S2", 674, "KIN86VFE0G", "S4", 856, None, None, None),
    
    ("Dishwasher 81.5m", "SMV4HVX00G", "S4", 529, "SMV6ZCX10G", "S6", 828, "SMD8YCX03G", "S8", 971),
    ("Dishwasher 87.5m", "SBH4HVX00G", "S4", 567, None, None, None, None, None, None),
    
    ("Washing Machine", None, None, None, "WIW28302GB", "S6", 671, "WIW28502GB", "S8", 769),
    ("Washer Dryer", "WKD28352GB", "S4", 969, "WKD28543GB", "S6", 1169, None, None, None),
]

def import_appliances():
    engine = create_engine(DATABASE_URL)
    
    with engine.connect() as conn:
        items_created = 0
        
        for item in bosch_data:
            product_name = item[0]
            
            # Low series
            if item[1] and item[3]:
                conn.execute(text("""
                    INSERT INTO "StreemLyne_MT"."PriceList_Master"
                    (tenant_id, category, item_code, item_name, description, base_price, door_type, brand, unit)
                    VALUES (:tenant_id, 'Appliances', :code, :name, :description, :price, 'Low', 'Bosch', 'each')
                """), {
                    'tenant_id': TENANT_ID,
                    'code': item[1],
                    'name': product_name,
                    'description': f"{product_name} - Low Series ({item[2]})",
                    'price': item[3]
                })
                items_created += 1
            
            # Mid series
            if item[4] and item[6]:
                conn.execute(text("""
                    INSERT INTO "StreemLyne_MT"."PriceList_Master"
                    (tenant_id, category, item_code, item_name, description, base_price, door_type, brand, unit)
                    VALUES (:tenant_id, 'Appliances', :code, :name, :description, :price, 'Mid', 'Bosch', 'each')
                """), {
                    'tenant_id': TENANT_ID,
                    'code': item[4],
                    'name': product_name,
                    'description': f"{product_name} - Mid Series ({item[5]})",
                    'price': item[6]
                })
                items_created += 1
            
            # High series
            if item[7] and item[9]:
                conn.execute(text("""
                    INSERT INTO "StreemLyne_MT"."PriceList_Master"
                    (tenant_id, category, item_code, item_name, description, base_price, door_type, brand, unit)
                    VALUES (:tenant_id, 'Appliances', :code, :name, :description, :price, 'High', 'Bosch', 'each')
                """), {
                    'tenant_id': TENANT_ID,
                    'code': item[7],
                    'name': product_name,
                    'description': f"{product_name} - High Series ({item[8]})",
                    'price': item[9]
                })
                items_created += 1
            
            if items_created % 10 == 0:
                print(f"Imported {items_created} items...")
        
        conn.commit()
        print(f"\n✅ Successfully imported {items_created} Bosch appliance items!")

if __name__ == '__main__':
    print("=" * 60)
    print("BOSCH APPLIANCES IMPORT")
    print("=" * 60)
    import_appliances()