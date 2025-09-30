#!/usr/bin/env python3
"""
Migration script to update database schema from models_old.py to models.py
This script handles SQLite database migration for Flask SQLAlchemy models.
"""

import sqlite3
import os
from datetime import datetime

def backup_database(db_path):
    """Create a backup of the existing database"""
    if not os.path.exists(db_path):
        print(f"Database {db_path} does not exist. Skipping backup.")
        return None
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = f"{db_path}.backup_{timestamp}"
    
    try:
        # Copy the database file
        import shutil
        shutil.copy2(db_path, backup_path)
        print(f"Database backed up to: {backup_path}")
        return backup_path
    except Exception as e:
        print(f"Error creating backup: {e}")
        return None

def migrate_database(db_path):
    """Perform the database migration"""
    print("Starting database migration...")
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        # Begin transaction
        cursor.execute("BEGIN TRANSACTION;")
        
        # 1. Update Consumable table
        print("Updating Consumable table...")
        
        # Check if columns exist before trying to drop them
        cursor.execute("PRAGMA table_info(consumable);")
        columns = [column[1] for column in cursor.fetchall()]
        
        # Add is_returnable column if it doesn't exist
        if 'is_returnable' not in columns:
            cursor.execute("""
                ALTER TABLE consumable 
                ADD COLUMN is_returnable BOOLEAN DEFAULT 0 NOT NULL;
            """)
            print("Added is_returnable column to Consumable table")
        
        # SQLite doesn't support DROP COLUMN directly, so we need to recreate the table
        if 'test' in columns or 'total' in columns:
            print("Removing 'test' and 'total' columns from Consumable table...")
            
            # Create new table structure
            cursor.execute("""
                CREATE TABLE consumable_new (
                    id INTEGER PRIMARY KEY,
                    balance_stock INTEGER,
                    unit VARCHAR(50),
                    description VARCHAR(200),
                    expiration VARCHAR(20),
                    lot_number VARCHAR(50),
                    date_received VARCHAR(20),
                    items_out INTEGER,
                    items_on_stock INTEGER,
                    previous_month_stock INTEGER,
                    units_consumed INTEGER,
                    units_expired INTEGER,
                    is_returnable BOOLEAN DEFAULT 0 NOT NULL
                );
            """)
            
            # Copy data (excluding test and total columns)
            cursor.execute("""
                INSERT INTO consumable_new (
                    id, balance_stock, unit, description, expiration, 
                    lot_number, date_received, items_out, items_on_stock,
                    previous_month_stock, units_consumed, units_expired, is_returnable
                )
                SELECT 
                    id, balance_stock, unit, description, expiration,
                    lot_number, date_received, items_out, items_on_stock,
                    previous_month_stock, units_consumed, units_expired, 0
                FROM consumable;
            """)
            
            # Drop old table and rename new one
            cursor.execute("DROP TABLE consumable;")
            cursor.execute("ALTER TABLE consumable_new RENAME TO consumable;")
            print("Successfully removed 'test' and 'total' columns")
        
        # 2. Update BorrowLog table
        print("Updating BorrowLog table...")
        
        cursor.execute("PRAGMA table_info(borrow_log);")
        borrow_columns = [column[1] for column in cursor.fetchall()]
        
        # Check if we need to migrate BorrowLog structure
        if 'student_name' in borrow_columns:
            print("Migrating BorrowLog table structure...")
            
            # Create new BorrowLog table
            cursor.execute("""
                CREATE TABLE borrow_log_new (
                    id INTEGER PRIMARY KEY,
                    borrower_name VARCHAR(100) NOT NULL,
                    borrower_type VARCHAR(20) NOT NULL,
                    section_course VARCHAR(150) NOT NULL,
                    purpose TEXT NOT NULL,
                    equipment_id INTEGER,
                    quantity_borrowed INTEGER DEFAULT 1 NOT NULL,
                    borrowed_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    returned_at DATETIME,
                    FOREIGN KEY (equipment_id) REFERENCES equipment(id)
                );
            """)
            
            # Migrate data with field mapping
            cursor.execute("""
                INSERT INTO borrow_log_new (
                    id, borrower_name, borrower_type, section_course, purpose,
                    equipment_id, quantity_borrowed, borrowed_at, returned_at
                )
                SELECT 
                    id, 
                    student_name,
                    'student',
                    section || ' - ' || course,
                    purpose,
                    equipment_id,
                    1,
                    borrowed_at,
                    returned_at
                FROM borrow_log;
            """)
            
            # Drop old table and rename new one
            cursor.execute("DROP TABLE borrow_log;")
            cursor.execute("ALTER TABLE borrow_log_new RENAME TO borrow_log;")
            print("Successfully migrated BorrowLog table")
        
        # 3. Update UsageLog table
        print("Updating UsageLog table...")
        
        cursor.execute("PRAGMA table_info(usage_log);")
        usage_columns = [column[1] for column in cursor.fetchall()]
        
        if 'student_name' in usage_columns:
            print("Migrating UsageLog table structure...")
            
            # Create new UsageLog table
            cursor.execute("""
                CREATE TABLE usage_log_new (
                    id INTEGER PRIMARY KEY,
                    user_name VARCHAR(100) NOT NULL,
                    user_type VARCHAR(20) NOT NULL,
                    section_course VARCHAR(150) NOT NULL,
                    purpose TEXT NOT NULL,
                    consumable_id INTEGER,
                    quantity_used INTEGER,
                    used_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    returned_at DATETIME,
                    FOREIGN KEY (consumable_id) REFERENCES consumable(id)
                );
            """)
            
            # Migrate data
            cursor.execute("""
                INSERT INTO usage_log_new (
                    id, user_name, user_type, section_course, purpose,
                    consumable_id, quantity_used, used_at, returned_at
                )
                SELECT 
                    id,
                    student_name,
                    'student',
                    section || ' - ' || course,
                    purpose,
                    consumable_id,
                    quantity_used,
                    used_at,
                    NULL
                FROM usage_log;
            """)
            
            # Drop old table and rename new one
            cursor.execute("DROP TABLE usage_log;")
            cursor.execute("ALTER TABLE usage_log_new RENAME TO usage_log;")
            print("Successfully migrated UsageLog table")
        
        # 4. Update StudentNote table
        print("Updating StudentNote table...")
        
        cursor.execute("PRAGMA table_info(student_note);")
        note_columns = [column[1] for column in cursor.fetchall()]
        
        if 'student_name' in note_columns:
            print("Migrating StudentNote table structure...")
            
            # Create new StudentNote table
            cursor.execute("""
                CREATE TABLE student_note_new (
                    id INTEGER PRIMARY KEY,
                    person_name VARCHAR(100) NOT NULL,
                    person_number VARCHAR(20) NOT NULL,
                    person_type VARCHAR(20) NOT NULL,
                    section_course VARCHAR(150) NOT NULL,
                    note_type VARCHAR(20) NOT NULL,
                    description TEXT NOT NULL,
                    equipment_id INTEGER,
                    consumable_id INTEGER,
                    created_by INTEGER NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (equipment_id) REFERENCES equipment(id),
                    FOREIGN KEY (consumable_id) REFERENCES consumable(id),
                    FOREIGN KEY (created_by) REFERENCES user(id)
                );
            """)
            
            # Migrate data
            cursor.execute("""
                INSERT INTO student_note_new (
                    id, person_name, person_number, person_type, section_course,
                    note_type, description, equipment_id, consumable_id,
                    created_by, created_at
                )
                SELECT 
                    id,
                    student_name,
                    student_number,
                    'student',
                    section || ' - ' || course,
                    note_type,
                    description,
                    equipment_id,
                    consumable_id,
                    created_by,
                    created_at
                FROM student_note;
            """)
            
            # Drop old table and rename new one
            cursor.execute("DROP TABLE student_note;")
            cursor.execute("ALTER TABLE student_note_new RENAME TO student_note;")
            print("Successfully migrated StudentNote table")
        
        # Commit the transaction
        cursor.execute("COMMIT;")
        print("Migration completed successfully!")
        
        # Verify the migration
        print("\nVerifying migration...")
        verify_migration(cursor)
        
    except Exception as e:
        print(f"Error during migration: {e}")
        cursor.execute("ROLLBACK;")
        raise
    finally:
        conn.close()

def verify_migration(cursor):
    """Verify that the migration was successful"""
    try:
        # Check table structures
        tables_to_check = ['consumable', 'borrow_log', 'usage_log', 'student_note']
        
        for table in tables_to_check:
            cursor.execute(f"PRAGMA table_info({table});")
            columns = cursor.fetchall()
            print(f"\n{table.upper()} table structure:")
            for column in columns:
                print(f"  - {column[1]} ({column[2]})")
        
        # Check record counts
        print("\nRecord counts:")
        for table in tables_to_check:
            cursor.execute(f"SELECT COUNT(*) FROM {table};")
            count = cursor.fetchone()[0]
            print(f"  - {table}: {count} records")
            
    except Exception as e:
        print(f"Error during verification: {e}")

def main():
    """Main migration function"""
    # You may need to adjust this path based on your Flask app structure
    db_path = "instance/database.db"  # Common Flask SQLite path
    
    # Alternative paths to check
    possible_paths = [
        "instance/database.db",
        "database.db", 
        "app.db",
        "instance/app.db"
    ]
    
    # Find the database file
    actual_db_path = None
    for path in possible_paths:
        if os.path.exists(path):
            actual_db_path = path
            break
    
    if not actual_db_path:
        print("Database file not found. Please specify the correct path.")
        db_path = input("Enter the path to your SQLite database file: ").strip()
        if not os.path.exists(db_path):
            print("Database file not found at specified path.")
            return
        actual_db_path = db_path
    
    print(f"Using database: {actual_db_path}")
    
    # Create backup
    backup_path = backup_database(actual_db_path)
    
    # Perform migration
    try:
        migrate_database(actual_db_path)
        print(f"\nMigration completed successfully!")
        if backup_path:
            print(f"Original database backed up to: {backup_path}")
    except Exception as e:
        print(f"\nMigration failed: {e}")
        if backup_path:
            print(f"You can restore from backup: {backup_path}")

if __name__ == "__main__":
    main()