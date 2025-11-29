"""
Generate SQL INSERT statements from Excel price list
This will create a .sql file you can run in Supabase
"""

import pandas as pd
import os

def generate_sql_from_excel(excel_path, output_file='pricelist_import.sql'):
    """Generate SQL INSERT statements from Excel"""
    
    print("\n📋 Reading Excel file...")
    
    # Read bedroom sheet with header on row 3
    df = pd.read_excel(excel_path, sheet_name='Bedroom', header=3)
    
    # Rename columns
    df.columns = ['Code', 'Description', '2016_Price', '2025_Price', 'Door_Drawer_Desc', 'Total1', 
                  'Acrylic', 'Total2', 'Vinyl_Doors', 'Total3', 'Black_Glass', 'Total4',
                  'Width', 'Height', 'Depth', 'Category', 'Category2', 'qty1', 'Height1', 'Width1',
                  'qty2', 'Height2', 'Width2', 'qty3', 'Height3', 'Width3']
    
    # Filter rows with actual prices
    df = df[df['2025_Price'].notna() & df['Code'].notna()]
    
    print(f"Found {len(df)} bedroom items with pricing")
    
    sql_statements = []
    sql_statements.append("-- ============================================================================")
    sql_statements.append("-- BEDROOM PRICE LIST IMPORT")
    sql_statements.append(f"-- Generated from: {os.path.basename(excel_path)}")
    sql_statements.append(f"-- Total items: {len(df)}")
    sql_statements.append("-- ============================================================================\n")
    
    sql_statements.append("-- Delete existing bedroom items (optional - comment out if you want to keep existing)")
    sql_statements.append("-- DELETE FROM price_list_items WHERE category = 'bedroom';\n")
    
    sql_statements.append("-- Insert bedroom price list items")
    sql_statements.append("INSERT INTO price_list_items (category, item_code, item_name, description, base_price, width, height, depth, subcategory, dimension_based, active)")
    sql_statements.append("VALUES")
    
    values = []
    for idx, row in df.iterrows():
        code = str(row['Code']).strip() if pd.notna(row['Code']) else None
        if not code or code == 'Code':  # Skip header rows
            continue
        
        description = str(row['Description']).strip() if pd.notna(row['Description']) else ''
        description = description.replace("'", "''")  # Escape single quotes for SQL
        
        price_2025 = float(row['2025_Price']) if pd.notna(row['2025_Price']) else 0
        width = int(row['Width']) if pd.notna(row['Width']) else None
        height = int(row['Height']) if pd.notna(row['Height']) else None
        depth = int(row['Depth']) if pd.notna(row['Depth']) else None
        category = str(row['Category']).strip() if pd.notna(row['Category']) else ''
        category = category.replace("'", "''")  # Escape single quotes
        
        # Create full description with dimensions
        full_desc = description
        if width or height or depth:
            dims = []
            if width: dims.append(f"W{width}mm")
            if height: dims.append(f"H{height}mm")
            if depth: dims.append(f"D{depth}mm")
            full_desc += f" ({' x '.join(dims)})"
        full_desc = full_desc.replace("'", "''")  # Escape single quotes
        
        dimension_based = 'TRUE' if (width or height or depth) else 'FALSE'
        
        width_str = str(width) if width else 'NULL'
        height_str = str(height) if height else 'NULL'
        depth_str = str(depth) if depth else 'NULL'
        
        value = f"    ('bedroom', '{code}', '{description}', '{full_desc}', {price_2025}, {width_str}, {height_str}, {depth_str}, '{category}', {dimension_based}, TRUE)"
        values.append(value)
    
    sql_statements.append(',\n'.join(values))
    sql_statements.append("\nON CONFLICT (category, item_code) DO UPDATE SET")
    sql_statements.append("    item_name = EXCLUDED.item_name,")
    sql_statements.append("    description = EXCLUDED.description,")
    sql_statements.append("    base_price = EXCLUDED.base_price,")
    sql_statements.append("    width = EXCLUDED.width,")
    sql_statements.append("    height = EXCLUDED.height,")
    sql_statements.append("    depth = EXCLUDED.depth,")
    sql_statements.append("    subcategory = EXCLUDED.subcategory,")
    sql_statements.append("    dimension_based = EXCLUDED.dimension_based,")
    sql_statements.append("    updated_at = CURRENT_TIMESTAMP;")
    
    sql_statements.append("\n\n-- ============================================================================")
    sql_statements.append("-- VERIFICATION QUERY")
    sql_statements.append("-- ============================================================================")
    sql_statements.append("\n-- Check imported items")
    sql_statements.append("SELECT category, item_code, item_name, base_price, width, height, depth")
    sql_statements.append("FROM price_list_items")
    sql_statements.append("WHERE category = 'bedroom'")
    sql_statements.append("ORDER BY item_code")
    sql_statements.append("LIMIT 20;")
    
    sql_statements.append("\n-- Count total items")
    sql_statements.append("SELECT category, COUNT(*) as total_items, SUM(base_price) as total_value")
    sql_statements.append("FROM price_list_items")
    sql_statements.append("WHERE category = 'bedroom'")
    sql_statements.append("GROUP BY category;")
    
    # Write to file
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write('\n'.join(sql_statements))
    
    print(f"\n✅ SQL file generated: {output_file}")
    print(f"✅ Total items: {len(values)}")
    print(f"\nNext steps:")
    print(f"1. Open {output_file}")
    print(f"2. Copy all contents")
    print(f"3. Paste into Supabase SQL Editor")
    print(f"4. Click 'Run' to import data")
    
    return output_file


if __name__ == "__main__":
    # Update this path to your Excel file location
    excel_path = r'C:\Users\ayaan\Techmynt Solutions\aztec_interiors\KBB Pricelist 2.xlsx'
    
    # Or try common locations
    if not os.path.exists(excel_path):
        # Try in backend/uploads
        excel_path = 'uploads/KBB_Pricelist_2.xlsx'
    
    if not os.path.exists(excel_path):
        # Try in parent directory
        excel_path = '../KBB_Pricelist_2.xlsx'
    
    if not os.path.exists(excel_path):
        print(f"❌ Excel file not found!")
        print("\nPlease update the excel_path variable with the correct location.")
        print("\nSearched locations:")
        print("  - C:\\Users\\ayaan\\Techmynt Solutions\\aztec_interiors\\KBB_Pricelist_2.xlsx")
        print("  - uploads/KBB_Pricelist_2.xlsx")
        print("  - ../KBB_Pricelist_2.xlsx")
        input("\nPress Enter to exit...")
        exit(1)
    
    print("="*80)
    print("GENERATE PRICE LIST SQL")
    print("="*80)
    print(f"Excel file: {excel_path}")
    
    try:
        output_file = generate_sql_from_excel(excel_path)
        print("\n" + "="*80)
        print("✅ SUCCESS!")
        print("="*80)
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
    
    input("\nPress Enter to exit...")