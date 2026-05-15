"""
Direct Database Fix Script
Parses kitchens.xlsx and updates PriceList_Master with correct prices
"""
import pandas as pd
from sqlalchemy import create_engine, text
from datetime import datetime

# ================================================================
# DATABASE CONNECTION
# ================================================================
# Replace with your actual connection string
DATABASE_URL = "postgresql://postgres.mcexfcjowunsmtilvepc:techmynt2025@aws-1-eu-west-1.pooler.supabase.com:6543/postgres"
engine = create_engine(DATABASE_URL)

TENANT_ID = '7'

# ================================================================
# STEP 1: Parse Excel with CORRECTED column mapping
# ================================================================
def parse_excel(filepath):
    """
    Parse kitchens.xlsx with correct column indices
    
    Row 2 (index 1 with header=1) contains actual column names
    Col 3: 2025 Price (CARCASS)
    Col 5: basic slab door COMPONENT
    Col 7: acrylic COMPONENT
    Col 9: vinyl COMPONENT
    Col 11: black glass COMPONENT
    
    Cols 6, 8, 10, 12 are TOTAL columns - IGNORED
    """
    # Read Excel - row 2 has headers, data starts at row 3
    df = pd.read_excel(filepath, header=2)  # Skip first 2 rows, use row 3 as header
    
    print(f"✅ Loaded Excel with {len(df)} rows")
    
    items = []
    
    for idx, row in df.iterrows():
        code = row.iloc[0]  # Code column
        desc = row.iloc[1]  # Description
        
        # Skip empty rows or header rows
        if pd.isna(code) or str(code).strip() == '':
            continue
        
        # Skip any remaining header rows (check if code looks like "Code" or "2025 Price")
        code_str = str(code).strip()
        if code_str.lower() in ['code', 'nan', ''] or 'price' in code_str.lower():
            continue
        
        # Extract prices from CORRECT columns
        carcass_price = row.iloc[3]     # Col 3: "2025 Price"
        basic_slab = row.iloc[5]        # Col 5: Basic Slab COMPONENT
        acrylic = row.iloc[7]           # Col 7: Acrylic COMPONENT
        vinyl = row.iloc[9]             # Col 9: Vinyl COMPONENT
        black_glass = row.iloc[11]      # Col 11: Black Glass COMPONENT
        
        # Dimensions
        width = row.iloc[13] if len(row) > 13 else None
        height = row.iloc[14] if len(row) > 14 else None
        depth = row.iloc[15] if len(row) > 15 else None
        category = row.iloc[16] if len(row) > 16 else 'Kitchen'
        
        # Helper function to safely convert to float
        def safe_float(val):
            if pd.isna(val):
                return None
            try:
                return float(val)
            except (ValueError, TypeError):
                return None
        
        # Helper function to safely convert to int
        def safe_int(val):
            if pd.isna(val):
                return None
            try:
                return int(float(val))
            except (ValueError, TypeError):
                return None
        
        item = {
            'code': code_str,
            'description': str(desc).strip() if not pd.isna(desc) else '',
            'carcass': safe_float(carcass_price),
            'basic_slab': safe_float(basic_slab),
            'acrylic': safe_float(acrylic),
            'vinyl': safe_float(vinyl),
            'black_glass': safe_float(black_glass),
            'width': safe_int(width),
            'height': safe_int(height),
            'depth': safe_int(depth),
            'category': str(category).strip() if not pd.isna(category) else 'Kitchen'
        }
        
        # Skip items without carcass price (likely invalid rows)
        if not item['carcass']:
            continue
        
        items.append(item)
        
        # Print first few items to verify
        if len(items) <= 10:
            bs_price = item['basic_slab'] if item['basic_slab'] else 0
            ag_price = item['acrylic'] if item['acrylic'] else 0
            print(f"✅ {item['code']}: Carcass £{item['carcass']:.2f}, BS £{bs_price:.2f}, AG £{ag_price:.2f}")
    
    return items

# ================================================================
# STEP 2: Delete old Kitchen data
# ================================================================
def delete_old_data(session):
    """Delete all existing Kitchen items"""
    delete_query = text("""
        DELETE FROM "StreemLyne_MT"."PriceList_Master"
        WHERE tenant_id = :tenant_id
          AND category IN ('Kitchen', 'Base Units', 'Wall Units', 'Larder Units', 
                           'Dresser Units', 'Finishing', 'Accessories', 'Top Box', 'Quad')
    """)
    
    result = session.execute(delete_query, {'tenant_id': TENANT_ID})
    
    print(f"🗑️ Deleted {result.rowcount} old rows")

# ================================================================
# STEP 3: Insert new data with correct structure
# ================================================================
def insert_new_data(session, items):
    """
    Insert items with separate rows:
    - One row for Carcass Only
    - One row per door type (Basic Slab, Acrylic, Vinyl, Black Glass)
    """
    insert_query = text("""
        INSERT INTO "StreemLyne_MT"."PriceList_Master" 
        (tenant_id, category, item_name, description, item_code, door_type, 
         base_price, width, height, depth, dimension_based, created_at, updated_at)
        VALUES 
        (:tenant_id, :category, :item_name, :description, :item_code, :door_type,
         :base_price, :width, :height, :depth, false, :created_at, :updated_at)
    """)
    
    now = datetime.now()
    inserted_count = 0
    
    for item in items:
        # Skip items without carcass price
        if not item['carcass']:
            continue
        
        # ROW 1: Carcass Only
        session.execute(insert_query, {
            'tenant_id': TENANT_ID,
            'category': item['category'],
            'item_name': item['description'],
            'description': f"{item['code']} - {item['description']} - Carcass Only",
            'item_code': item['code'],
            'door_type': 'Carcass Only',
            'base_price': item['carcass'],
            'width': item['width'],
            'height': item['height'],
            'depth': item['depth'],
            'created_at': now,
            'updated_at': now
        })
        inserted_count += 1
        
        # ROW 2: Basic Slab component
        if item['basic_slab']:
            session.execute(insert_query, {
                'tenant_id': TENANT_ID,
                'category': item['category'],
                'item_name': item['description'],
                'description': f"{item['code']} - {item['description']} - Basic Slab",
                'item_code': item['code'],
                'door_type': 'Basic Slab',
                'base_price': item['basic_slab'],
                'width': item['width'],
                'height': item['height'],
                'depth': item['depth'],
                'created_at': now,
                'updated_at': now
            })
            inserted_count += 1
        
        # ROW 3: Acrylic component
        if item['acrylic']:
            session.execute(insert_query, {
                'tenant_id': TENANT_ID,
                'category': item['category'],
                'item_name': item['description'],
                'description': f"{item['code']} - {item['description']} - Acrylic Gloss/Matt",
                'item_code': item['code'],
                'door_type': 'Acrylic Gloss/Matt',
                'base_price': item['acrylic'],
                'width': item['width'],
                'height': item['height'],
                'depth': item['depth'],
                'created_at': now,
                'updated_at': now
            })
            inserted_count += 1
        
        # ROW 4: Vinyl component
        if item['vinyl']:
            session.execute(insert_query, {
                'tenant_id': TENANT_ID,
                'category': item['category'],
                'item_name': item['description'],
                'description': f"{item['code']} - {item['description']} - Vinyl Doors",
                'item_code': item['code'],
                'door_type': 'Vinyl Doors',
                'base_price': item['vinyl'],
                'width': item['width'],
                'height': item['height'],
                'depth': item['depth'],
                'created_at': now,
                'updated_at': now
            })
            inserted_count += 1
        
        # ROW 5: Black Glass component
        if item['black_glass']:
            session.execute(insert_query, {
                'tenant_id': TENANT_ID,
                'category': item['category'],
                'item_name': item['description'],
                'description': f"{item['code']} - {item['description']} - Black Glass",
                'item_code': item['code'],
                'door_type': 'Black Glass',
                'base_price': item['black_glass'],
                'width': item['width'],
                'height': item['height'],
                'depth': item['depth'],
                'created_at': now,
                'updated_at': now
            })
            inserted_count += 1
    
    print(f"✅ Inserted {inserted_count} rows")

# ================================================================
# STEP 4: Verify results
# ================================================================
def verify_data(session):
    """Verify 100B has correct structure"""
    verify_query = text("""
        SELECT item_code, door_type, base_price
        FROM "StreemLyne_MT"."PriceList_Master"
        WHERE tenant_id = :tenant_id
          AND item_code = '100B'
        ORDER BY door_type
    """)
    
    result = session.execute(verify_query, {'tenant_id': TENANT_ID})
    
    print("\n" + "="*60)
    print("VERIFICATION: 100B pricing structure")
    print("="*60)
    for row in result:
        print(f"{row.item_code:10} | {row.door_type:20} | £{row.base_price:.2f}")
    print("="*60)

# ================================================================
# MAIN EXECUTION
# ================================================================
def main():
    print("="*60)
    print("KITCHEN PRICELIST DATABASE FIX")
    print("="*60)
    
    # Parse Excel
    excel_file = 'kitchens.xlsx'  # Update path if needed
    items = parse_excel(excel_file)
    
    print(f"\n✅ Parsed {len(items)} items from Excel")
    
    # Database operations
    with engine.begin() as conn:
        print("\n🗑️ Deleting old data...")
        delete_old_data(conn)
        
        print("\n💾 Inserting new data...")
        insert_new_data(conn, items)
        
        print("\n✅ Verifying...")
        verify_data(conn)
    
    print("\n" + "="*60)
    print("✅ DATABASE FIX COMPLETE!")
    print("="*60)
    print("\nNext steps:")
    print("1. Check frontend - Carcass column should show prices")
    print("2. Test quote: 50B with no dropdown = £99.86 (carcass)")
    print("3. Test quote: 50B-BS = £34.48 (door only)")
    print("4. Test quote: 50B + 'Basic Slab' dropdown = £132.08")

if __name__ == '__main__':
    main()