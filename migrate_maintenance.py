"""
Migration script to add EquipmentMaintenance table
Run this once to add the maintenance feature to existing database
"""
import sqlite3
import os

# Database path
basedir = os.path.abspath(os.path.dirname(__file__))
db_path = os.path.join(basedir, "instance", "database.db")

def migrate():
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        # Check if equipment_maintenance table already exists
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='equipment_maintenance'")
        if cursor.fetchone():
            print("✓ EquipmentMaintenance table already exists. No migration needed.")
            return
        
        print("Creating equipment_maintenance table...")
        
        # Create the equipment_maintenance table
        cursor.execute('''
            CREATE TABLE equipment_maintenance (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                equipment_id INTEGER NOT NULL,
                maintenance_type VARCHAR(50) NOT NULL,
                scheduled_date DATE NOT NULL,
                completed_date DATE,
                performed_by VARCHAR(200),
                notes TEXT,
                cost REAL DEFAULT 0.0,
                status VARCHAR(20) NOT NULL DEFAULT 'scheduled',
                created_by INTEGER NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (equipment_id) REFERENCES equipment (id),
                FOREIGN KEY (created_by) REFERENCES user (id)
            )
        ''')
        
        conn.commit()
        print("✓ Successfully created equipment_maintenance table!")
        
    except sqlite3.Error as e:
        print(f"✗ Error during migration: {e}")
        conn.rollback()
    finally:
        conn.close()

if __name__ == "__main__":
    if not os.path.exists(db_path):
        print(f"✗ Database not found at {db_path}")
        print("  Run the application first to create the database.")
    else:
        migrate()
