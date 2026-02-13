"""
Migration script to add door style price columns to price_list_items table.
Run this script from the backend directory: python migrations/add_door_style_prices.py
"""

import sys
import os

# Add the parent directory to the path so we can import the app
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text, inspect

# Import directly from db module
from db import engine

def migrate():
    """Add door style price columns to price_list_items table."""
    
    print("Connecting to database...")
    
    # Check if columns already exist
    inspector = inspect(engine)
    existing_columns = [col['name'] for col in inspector.get_columns('price_list_items')]
    
    print(f"Found {len(existing_columns)} existing columns in price_list_items table")
    
    columns_to_add = [
        ('basic_slab_price', 'NUMERIC(10, 2)'),
        ('vinyl_doors_price', 'NUMERIC(10, 2)'),
        ('acrylic_gloss_matt_price', 'NUMERIC(10, 2)'),
        ('black_glass_price', 'NUMERIC(10, 2)'),
    ]
    
    for column_name, column_type in columns_to_add:
        if column_name in existing_columns:
            print(f"✓ Column '{column_name}' already exists - skipping")
            continue
        
        # Add the column
        try:
            with engine.connect() as conn:
                conn.execute(text(f"ALTER TABLE price_list_items ADD COLUMN {column_name} {column_type}"))
                conn.commit()
            print(f"✓ Added column '{column_name}' to price_list_items table")
        except Exception as e:
            print(f"✗ Error adding column '{column_name}': {e}")
            return False
    
    print("\n✅ Migration completed successfully!")
    print("\nNext steps:")
    print("1. Populate the door style price fields with data from your price list")
    print("2. Restart your Flask backend server")
    print("3. Test the automatic price calculation with different door styles")
    
    return True

if __name__ == '__main__':
    print("Starting door style price migration...")
    print("=" * 50)
    success = migrate()
    sys.exit(0 if success else 1)
