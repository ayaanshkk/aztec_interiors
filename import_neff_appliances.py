"""
Import Neff Appliances to database
"""

from sqlalchemy import create_engine, text

DATABASE_URL = "postgresql://postgres.mcexfcjowunsmtilvepc:techmynt2025@aws-1-eu-west-1.pooler.supabase.com:5432/postgres"
TENANT_ID = "7"

# Neff appliances data
neff_data = [
    # Product Name, Low Model, Low Series, Low Price, Mid Model, Mid Series, Mid Price, High Model, High Series, High Price
    ("HOB 90cm Gas", None, None, None, "T29CIR8N0", "N70", 567, "T29RHS4S0", "N90", 879),
    ("HOB 75cm Gas", "T27GKQ8N0", "N50", 469, "T27CIQ8N0", "N70", 472, None, None, None),
    ("HOB 60cm Gas", "T26GKH8N0", "N50", 239, "T26CIP8S0", "N70", 331, None, None, None),
    ("60 cm Induction", "T36FBE1L0G", "N30", 365, "T66FHE4L0", "N70", 628, None, None, None),
    ("80 cm Induction", None, None, None, "T58FHW1L0", "N70", 823, "T68FUV4L0", "N90", 968),
    ("90 cm Induction", None, None, None, None, None, None, "T69FUV4L0", "N90", 1121),
    
    ("S/Oven - Flex design", None, None, None, "B59CR7KY0B", "N70", 1281, "B69CS7MY0B", "N90", 1468),
    ("Slide n hide - Pyro", "B6ACH7AG7B", "N50", 777, "B54CR71G0B", "N70", 976, "B64CS71G0B", "N90", 1079),
    ("Pyro", "B6ACH7AG7B", "N50", 735, "B24CR71G0B", "N70", 839, None, None, None),
    ("Slide n Hide - Eco", None, None, None, "B54CR31G0B", "N70", 877, "B64CS51G0B", "N90", 1054),
    ("Eco", "B1ACE4HN0B", "N50", 578, "B24CR31G0B", "N70", 782, None, None, None),
    
    ("Hood 60cm", "D62PBC0N0B", "N30", 276, "D64QFM1N0B", "N50", 472, "D65BMP5N0B", "N70", 573),
    ("Hood 80cm", "D83IDK1S0B", "N30", 378, "D85IFN1S0B", "N50", 669, None, None, None),
    ("Hood 90cm", "D94BHM1N0B", "N50", 475, "D95BMP5N0B", "N70", 718, "D98IPT2S0B", "N90", 871),
    ("Hood Integrated 60cm", "D61MAC1X0B", "N30", 149, "D64MAC1X0B", "N30", 177, "D65XAM2S0B", "N70", 524),
    ("Hood Integrated 90cm", None, None, None, None, None, None, "D95XAM2S0B", "N70", 574),
    ("Hood Downdraft 90cm", None, None, None, None, None, None, "I98WMM1S7B", "N90", 2628),
    
    ("M/Oven Only", "HLAWG25S3B", "N30", 377, "HLAWD23N0B", "N50", 404, "C24GR3XG1B", "N70", 869),
    ("Combi M/Oven", "C1AMG84N1B", "N50", 716, "C24MR21N0B", "N70", 1065, "C24MS71G0B", "N90", 1469),
    ("Warming Drawer", None, None, None, "N1AHA01N0B", "N50", 371, None, None, None),
    
    ("Fridge", "KI1812FE0G", "N50", 928, "KI1813FE0G", "N70", 1011, "KI18815OD0", "N90", 1399),
    ("Freezer", "GI7812EE0G", "N50", 1121, "GI7815CE0G", "N90", 1135, "GI7815NE0", "N90", 1399),
    
    ("Fridge / Freezer", "KI7851SE0G", "N30", 729, "KI7862FE0G", "N50", 912, "K17863DD0G", "N70", 1009),
    
    ("D/wsher 81.5cm vario hinge", None, None, None, "S175HTX06G", "N50", 469, "S187TC800E", "N70", 972),
    ("D/wsher 87.5cm vario hinge", None, None, None, "S295HCX02G", "N50", 823, None, None, None),
    
    ("Washing Machine", None, None, None, "W543BX2GB", None, 722, "W544BX2GB", None, 774),
    ("Washer Dryer", None, None, None, "V6320X2GB", None, 968, "V6540X3GB", None, 1162),
    ("Candy CSEV9LG 9Kg Vented Tumble Dryer", "CSEV9DF", None, 259, None, None, None, None, None, None),
]

def import_appliances():
    engine = create_engine(DATABASE_URL)
    
    with engine.connect() as conn:
        items_created = 0
        
        for item in neff_data:
            product_name = item[0]
            
            # Low series
            if item[1] and item[3]:
                series_info = item[2] if item[2] else ""
                conn.execute(text("""
                    INSERT INTO "StreemLyne_MT"."PriceList_Master"
                    (tenant_id, category, item_code, item_name, description, base_price, door_type, brand, unit)
                    VALUES (:tenant_id, 'Appliances', :code, :name, :description, :price, 'Low', 'Neff', 'each')
                """), {
                    'tenant_id': TENANT_ID,
                    'code': item[1],
                    'name': product_name,
                    'description': f"{product_name} - Low Series ({series_info})" if series_info else f"{product_name} - Low Series",
                    'price': item[3]
                })
                items_created += 1
                print(f"  ✅ {product_name} - Low ({item[1]}) - £{item[3]}")
            
            # Mid series
            if item[4] and item[6]:
                series_info = item[5] if item[5] else ""
                conn.execute(text("""
                    INSERT INTO "StreemLyne_MT"."PriceList_Master"
                    (tenant_id, category, item_code, item_name, description, base_price, door_type, brand, unit)
                    VALUES (:tenant_id, 'Appliances', :code, :name, :description, :price, 'Mid', 'Neff', 'each')
                """), {
                    'tenant_id': TENANT_ID,
                    'code': item[4],
                    'name': product_name,
                    'description': f"{product_name} - Mid Series ({series_info})" if series_info else f"{product_name} - Mid Series",
                    'price': item[6]
                })
                items_created += 1
                print(f"  ✅ {product_name} - Mid ({item[4]}) - £{item[6]}")
            
            # High series
            if item[7] and item[9]:
                series_info = item[8] if item[8] else ""
                conn.execute(text("""
                    INSERT INTO "StreemLyne_MT"."PriceList_Master"
                    (tenant_id, category, item_code, item_name, description, base_price, door_type, brand, unit)
                    VALUES (:tenant_id, 'Appliances', :code, :name, :description, :price, 'High', 'Neff', 'each')
                """), {
                    'tenant_id': TENANT_ID,
                    'code': item[7],
                    'name': product_name,
                    'description': f"{product_name} - High Series ({series_info})" if series_info else f"{product_name} - High Series",
                    'price': item[9]
                })
                items_created += 1
                print(f"  ✅ {product_name} - High ({item[7]}) - £{item[9]}")
            
            if items_created % 10 == 0 and items_created > 0:
                print(f"\n  📊 Imported {items_created} items so far...")
        
        conn.commit()
        print(f"\n✅ Successfully imported {items_created} Neff appliance items!")

if __name__ == '__main__':
    print("=" * 60)
    print("NEFF APPLIANCES IMPORT")
    print("=" * 60)
    print()
    import_appliances()