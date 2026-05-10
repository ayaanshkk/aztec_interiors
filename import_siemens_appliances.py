"""
Import Siemens Appliances to database
"""

from sqlalchemy import create_engine, text

DATABASE_URL = "postgresql://postgres.mcexfcjowunsmtilvepc:techmynt2025@aws-1-eu-west-1.pooler.supabase.com:5432/postgres"
TENANT_ID = "7"

# Siemens appliances data
siemens_data = [
    # Product Name, Low Model, Low Series, Low Price, Mid Model, Mid Series, Mid Price, High Model, High Series, High Price
    ("HOB 90cm Gas", None, None, None, "EP9A6MI40", "iQ500", 571, "ER9A6SH40", "iQ700", 929),
    ("HOB 75cm Gas", None, None, None, "EP7A6QI40", "iQ500", 529, None, None, None),
    ("HOB 60cm Gas", None, None, None, "EP6A6HI10", "iQ500", 449, None, None, None),
    ("60 cm Induction", "EU611BEB5B", "iQ100", 442, "ED651HSB1E", "iQ500", 666, "EX651HEC1E", "iQ700", 722),
    ("80 cm Induction", "EH831HVB1E", "iQ100", 879, "ED851HWB1E", "iQ500", 869, "EX851HVC1E", "iQ700", 963),
    ("90 cm Induction", "EX275HXC1E", "iQ700", 1348, "EX275HXC1E", "iQ700", 1332, "EX975LVV1E", "iQ700", 1472),
    
    ("Single Oven - Eco", "HB537GBS3B", "iQ500", 567, "HB732G1B1B", "iQ700", 801, "HB736G1B1B", "iQ700", 929),
    ("Single Oven - Pyro", "HB578GBS7B", "iQ500", 669, "HR776G1B1B", "iQ700", 1264, "HB778G3B1B", "iQ700", 1317),
    
    ("Hood 60cm", "LC67BHM50B", "iQ300", 468, "LC67KFN60B", "iQ300", 621, None, None, None),
    ("Hood 80cm", "LC87KFN60B", "iQ300", 667, None, None, None, None, None, None),
    ("Hood Integrated 60cm", "LE66MAC00B", "iQ100", 223, "LJ67BAM60B", "iQ500", 521, None, None, None),
    ("Hood Integrated 80cm", None, None, None, "LJ97BAM60B", "iQ500", 564, None, None, None),
    ("Hood Downdraft 90cm", None, None, None, None, None, None, "LD98WMM60B", "iQ700", 2493),
    
    ("M/Oven Only", "CM585AGS1B", "iQ500", 723, "BF722L1B1B", "iQ700", 727, None, None, None),
    ("Combi M/Oven", "CM585AGS1B", "iQ500", 718, "CM724G1B1B", "iQ700", 1468, "CM776G1B1B", "iQ700", 1456),
    
    ("Fridge", "KI81RNSE0G", "iQ100", 916, "KI81RVFE0G", "iQ300", 978, "KI81RADD0G", "iQ500", 1067),
    ("Freezer", None, None, None, "GI81NVEE0G", "iQ300", 1067, None, None, None),
    
    ("Fridge / Freezer", "KI96NNSE0", "iQ100", 867, "KI96NVFD0", "iQ300", 1026, None, None, None),
    
    ("Dishwasher 81.5m", "SN73HX10VG", "iQ300", 621, "SN95EX12CG", "iQ500", 818, "SN97TX02CE", "iQ700", 1299),
    ("Dishwasher 87.5m", "SX73HX10VG", "iQ300", 628, None, None, None, None, None, None),
    
    ("Washing Machine", None, None, None, None, None, None, "WI14W502GB", "iQ700", 768),
    ("Washer Dryer", None, None, None, "WK14D543GB", "iQ500", 1153, None, None, None),
]

def import_appliances():
    engine = create_engine(DATABASE_URL)
    
    with engine.connect() as conn:
        items_created = 0
        
        for item in siemens_data:
            product_name = item[0]
            
            # Low series
            if item[1] and item[3]:
                conn.execute(text("""
                    INSERT INTO "StreemLyne_MT"."PriceList_Master"
                    (tenant_id, category, item_code, item_name, description, base_price, door_type, brand, unit)
                    VALUES (:tenant_id, 'Appliances', :code, :name, :description, :price, 'Low', 'Siemens', 'each')
                """), {
                    'tenant_id': TENANT_ID,
                    'code': item[1],
                    'name': product_name,
                    'description': f"{product_name} - Low Series ({item[2]})",
                    'price': item[3]
                })
                items_created += 1
                print(f"  ✅ {product_name} - Low ({item[1]}) - £{item[3]}")
            
            # Mid series
            if item[4] and item[6]:
                conn.execute(text("""
                    INSERT INTO "StreemLyne_MT"."PriceList_Master"
                    (tenant_id, category, item_code, item_name, description, base_price, door_type, brand, unit)
                    VALUES (:tenant_id, 'Appliances', :code, :name, :description, :price, 'Mid', 'Siemens', 'each')
                """), {
                    'tenant_id': TENANT_ID,
                    'code': item[4],
                    'name': product_name,
                    'description': f"{product_name} - Mid Series ({item[5]})",
                    'price': item[6]
                })
                items_created += 1
                print(f"  ✅ {product_name} - Mid ({item[4]}) - £{item[6]}")
            
            # High series
            if item[7] and item[9]:
                conn.execute(text("""
                    INSERT INTO "StreemLyne_MT"."PriceList_Master"
                    (tenant_id, category, item_code, item_name, description, base_price, door_type, brand, unit)
                    VALUES (:tenant_id, 'Appliances', :code, :name, :description, :price, 'High', 'Siemens', 'each')
                """), {
                    'tenant_id': TENANT_ID,
                    'code': item[7],
                    'name': product_name,
                    'description': f"{product_name} - High Series ({item[8]})",
                    'price': item[9]
                })
                items_created += 1
                print(f"  ✅ {product_name} - High ({item[7]}) - £{item[9]}")
            
            if items_created % 10 == 0 and items_created > 0:
                print(f"\n  📊 Imported {items_created} items so far...")
        
        conn.commit()
        print(f"\n✅ Successfully imported {items_created} Siemens appliance items!")

if __name__ == '__main__':
    print("=" * 60)
    print("SIEMENS APPLIANCES IMPORT")
    print("=" * 60)
    print()
    import_appliances()