"""
Migration script to add barcode columns to Equipment and Consumable tables.
Also generates barcodes for existing records.
"""

import sqlite3
import uuid
from datetime import datetime

def generate_barcode(prefix, item_id):
    """Generate a unique barcode string for an item."""
    # Format: PREFIX-ID-RANDOM (e.g., EQ-001-A1B2, CON-001-C3D4)
    random_suffix = uuid.uuid4().hex[:4].upper()
    return f"{prefix}-{item_id:04d}-{random_suffix}"

def migrate_database(db_path='instance/database.db'):
    """
    Add barcode columns to Equipment and Consumable tables.
    Generate barcodes for existing records.
    
    Args:
        db_path (str): Path to your SQLite database file
    """
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        print("Starting barcode migration...")
        
        # ==================== Equipment Table ====================
        print("\n--- Equipment Table ---")
        cursor.execute("PRAGMA table_info(equipment)")
        columns = [column[1] for column in cursor.fetchall()]
        
        # Add barcode column if it doesn't exist (without UNIQUE constraint initially)
        if 'barcode' not in columns:
            print("Adding 'barcode' column to equipment table...")
            cursor.execute("""
                ALTER TABLE equipment 
                ADD COLUMN barcode VARCHAR(50)
            """)
            print("✓ Barcode column added to equipment table")
        else:
            print("✓ Barcode column already exists in equipment table")
        
        # Generate barcodes for equipment without one
        cursor.execute("SELECT id FROM equipment WHERE barcode IS NULL OR barcode = ''")
        equipment_ids = cursor.fetchall()
        
        if equipment_ids:
            print(f"Generating barcodes for {len(equipment_ids)} equipment items...")
            for (eq_id,) in equipment_ids:
                barcode = generate_barcode("EQ", eq_id)
                cursor.execute("UPDATE equipment SET barcode = ? WHERE id = ?", (barcode, eq_id))
            print(f"✓ Generated barcodes for {len(equipment_ids)} equipment items")
        else:
            print("✓ All equipment items already have barcodes")
        
        # ==================== Consumable Table ====================
        print("\n--- Consumable Table ---")
        cursor.execute("PRAGMA table_info(consumable)")
        columns = [column[1] for column in cursor.fetchall()]
        
        # Add barcode column if it doesn't exist (without UNIQUE constraint initially)
        if 'barcode' not in columns:
            print("Adding 'barcode' column to consumable table...")
            cursor.execute("""
                ALTER TABLE consumable 
                ADD COLUMN barcode VARCHAR(50)
            """)
            print("✓ Barcode column added to consumable table")
        else:
            print("✓ Barcode column already exists in consumable table")
        
        # Generate barcodes for consumables without one
        cursor.execute("SELECT id FROM consumable WHERE barcode IS NULL OR barcode = ''")
        consumable_ids = cursor.fetchall()
        
        if consumable_ids:
            print(f"Generating barcodes for {len(consumable_ids)} consumable items...")
            for (con_id,) in consumable_ids:
                barcode = generate_barcode("CON", con_id)
                cursor.execute("UPDATE consumable SET barcode = ? WHERE id = ?", (barcode, con_id))
            print(f"✓ Generated barcodes for {len(consumable_ids)} consumable items")
        else:
            print("✓ All consumable items already have barcodes")
        
        # Commit the changes
        conn.commit()
        print("\n" + "="*50)
        print("✓ Barcode migration completed successfully!")
        print("="*50)
        
    except sqlite3.Error as e:
        print(f"✗ Database error: {e}")
        conn.rollback()
        raise
    except Exception as e:
        print(f"✗ Error: {e}")
        conn.rollback()
        raise
    finally:
        conn.close()

if __name__ == "__main__":
    import os
    
    # Get the database path relative to this script
    basedir = os.path.abspath(os.path.dirname(__file__))
    db_path = os.path.join(basedir, "instance", "database.db")
    
    if not os.path.exists(db_path):
        print(f"Database not found at {db_path}")
        print("Please run the application first to create the database.")
    else:
        migrate_database(db_path)
