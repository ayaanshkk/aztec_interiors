"""
Direct bedroom Excel import script
Run this once to fix all bedroom prices
"""

import pandas as pd
from sqlalchemy import create_engine, text

# DATABASE CONNECTION (from your .env)
DATABASE_URL = "postgresql://postgres.mcexfcjowunsmtilvepc:techmynt2025@aws-1-eu-west-1.pooler.supabase.com:5432/postgres"
TENANT_ID = "7"
EXCEL_FILE_PATH = r"C:\Users\ateeb\Downloads\bedrooms.xlsx"

def import_bedrooms():
    # Read Excel - try different header rows to find the right one
    print("Reading Excel file...")
    
    # First, read without header to inspect
    df_raw = pd.read_excel(EXCEL_FILE_PATH, header=None, nrows=5)
    print("\nFirst 5 rows of raw data:")
    for i in range(min(5, len(df_raw))):
        print(f"Row {i}: {df_raw.iloc[i, :10].tolist()}")
    
    # Now read with header - your Excel seems to have the header at row 3 (index 3)
    # Based on output showing 'carcas price ex VAT', try header=3
    df = pd.read_excel(EXCEL_FILE_PATH, header=3)
    
    print(f"\nLoaded {len(df)} rows")
    print(f"Columns: {df.columns.tolist()[:15]}")
    print(f"\nFirst data row:")
    print(df.iloc[0, :15].tolist())
    
    # Connect to database
    engine = create_engine(DATABASE_URL)
    
    with engine.connect() as conn:
        # First, delete existing bedroom items
        print("\nDeleting existing bedroom items...")
        result = conn.execute(text("""
            DELETE FROM "StreemLyne_MT"."PriceList_Master"
            WHERE tenant_id = :tenant_id AND category = 'Bedrooms'
        """), {'tenant_id': TENANT_ID})
        conn.commit()
        print(f"Deleted {result.rowcount} existing items")
        
        # Find column indices
        print("\nImporting bedroom items...")
        
        items_created = 0
        
        for idx, row in df.iterrows():
            # Get code
            code = str(row.iloc[0]).strip() if pd.notna(row.iloc[0]) else None
            if not code or code == 'nan' or code == '':
                continue
            
            # Get description from column 1
            item_name = str(row.iloc[1]).strip() if pd.notna(row.iloc[1]) else code
            if item_name == 'nan':
                item_name = code
            
            # Get dimensions (Width at 12, Height at 13, Depth at 14)
            try:
                width = int(float(row.iloc[12])) if pd.notna(row.iloc[12]) and row.iloc[12] != '' else None
            except:
                width = None
            
            try:
                height = int(float(row.iloc[13])) if pd.notna(row.iloc[13]) and row.iloc[13] != '' else None
            except:
                height = None
                
            try:
                depth = int(float(row.iloc[14])) if pd.notna(row.iloc[14]) and row.iloc[14] != '' else None
            except:
                depth = None
            
            # Based on actual Excel structure (header at row 3):
            # Columns: ['Code', 'Unnamed: 1', '2016 Price', '2025 Price', 'basic slab...', 'TOTAL', 'Acrylic...', 'TOTAL.1', 'vinyl...', 'TOTAL.2', 'Black Glass', 'TOTAL.3', 'Width', 'Height', 'Depth']
            # Index:      0         1            2             3              4            5          6           7           8          9            10            11        12       13        14
            #
            # We want the TOTAL columns:
            # Index 5: TOTAL (Basic Slab total)
            # Index 7: TOTAL.1 (Acrylic total)
            # Index 9: TOTAL.2 (Vinyl total)
            # Index 11: TOTAL.3 (Black Glass total)
            
            door_types_and_cols = [
                (5, 'Basic Slab'),           # TOTAL column
                (7, 'Acrylic Gloss/Matt'),   # TOTAL.1 column
                (9, 'Vinyl Doors'),          # TOTAL.2 column
                (11, 'Black Glass'),         # TOTAL.3 column
            ]
            
            for col_idx, door_type in door_types_and_cols:
                if col_idx < len(row):
                    price = row.iloc[col_idx]
                    
                    # Debug output for first item
                    if code == '40R':
                        print(f"  DEBUG {code} - {door_type}: Column {col_idx} = {price}")
                    
                    if pd.notna(price) and price != '' and price != 0:
                        try:
                            price = float(price)
                            
                            # Insert into database
                            conn.execute(text("""
                                INSERT INTO "StreemLyne_MT"."PriceList_Master"
                                (tenant_id, category, item_code, item_name, description, base_price, door_type,
                                 width, height, depth, unit, dimension_based)
                                VALUES (:tenant_id, :category, :item_code, :item_name, :description, :base_price, :door_type,
                                        :width, :height, :depth, :unit, :dimension_based)
                            """), {
                                'tenant_id': TENANT_ID,
                                'category': 'Bedrooms',
                                'item_code': code,
                                'item_name': item_name,
                                'description': f"{item_name} - {door_type}",
                                'base_price': price,
                                'door_type': door_type,
                                'width': width,
                                'height': height,
                                'depth': depth,
                                'unit': 'each',
                                'dimension_based': False
                            })
                            items_created += 1
                            
                            if items_created % 10 == 0:
                                print(f"  Created {items_created} items...")
                                
                        except Exception as e:
                            print(f"  Error processing {code} - {door_type}: {e}")
        
        conn.commit()
        print(f"\n✅ Successfully imported {items_created} bedroom items!")

if __name__ == '__main__':
    print("=" * 60)
    print("BEDROOM PRICELIST DIRECT IMPORT")
    print("=" * 60)
    
    # Run the import
    import_bedrooms()