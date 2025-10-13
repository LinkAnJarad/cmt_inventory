"""
Migration script to update database schema from models_previous.py to models.py
Main changes:
- Add status, resolved_at, resolved_by columns to StudentNote table
"""

import sqlite3
from datetime import datetime

def migrate_database(db_path='your_database.db'):
    """
    Migrate the database from the previous schema to the new schema.
    
    Args:
        db_path (str): Path to your SQLite database file
    """
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        print("Starting database migration...")
        
        # Check if the new columns already exist
        cursor.execute("PRAGMA table_info(student_note)")
        columns = [column[1] for column in cursor.fetchall()]
        
        # Add status column if it doesn't exist
        if 'status' not in columns:
            print("Adding 'status' column to student_note table...")
            cursor.execute("""
                ALTER TABLE student_note 
                ADD COLUMN status VARCHAR(20) NOT NULL DEFAULT 'pending'
            """)
            print("✓ Status column added successfully")
        else:
            print("✓ Status column already exists")
        
        # Add resolved_at column if it doesn't exist
        if 'resolved_at' not in columns:
            print("Adding 'resolved_at' column to student_note table...")
            cursor.execute("""
                ALTER TABLE student_note 
                ADD COLUMN resolved_at DATETIME
            """)
            print("✓ Resolved_at column added successfully")
        else:
            print("✓ Resolved_at column already exists")
        
        # Add resolved_by column if it doesn't exist
        if 'resolved_by' not in columns:
            print("Adding 'resolved_by' column to student_note table...")
            cursor.execute("""
                ALTER TABLE student_note 
                ADD COLUMN resolved_by INTEGER REFERENCES user(id)
            """)
            print("✓ Resolved_by column added successfully")
        else:
            print("✓ Resolved_by column already exists")
        
        # Commit the changes
        conn.commit()
        print("Migration completed successfully!")
        
        # Verify the migration
        cursor.execute("PRAGMA table_info(student_note)")
        updated_columns = [column[1] for column in cursor.fetchall()]
        print(f"Updated StudentNote table columns: {updated_columns}")
        
    except sqlite3.Error as e:
        print(f"An error occurred during migration: {e}")
        conn.rollback()
        raise
    
    finally:
        conn.close()

def rollback_migration(db_path='your_database.db'):
    """
    Rollback the migration (remove the new columns).
    Note: SQLite doesn't support DROP COLUMN directly, so this creates a new table.
    
    Args:
        db_path (str): Path to your SQLite database file
    """
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        print("Starting migration rollback...")
        
        # Create a backup table with the old schema
        cursor.execute("""
            CREATE TABLE student_note_backup AS
            SELECT 
                id, person_name, person_number, person_type, section_course,
                note_type, description, equipment_id, consumable_id,
                created_by, created_at
            FROM student_note
        """)
        
        # Drop the current table
        cursor.execute("DROP TABLE student_note")
        
        # Recreate the table with the old schema
        cursor.execute("""
            CREATE TABLE student_note (
                id INTEGER PRIMARY KEY,
                person_name VARCHAR(100) NOT NULL,
                person_number VARCHAR(20) NOT NULL,
                person_type VARCHAR(20) NOT NULL,
                section_course VARCHAR(150) NOT NULL,
                note_type VARCHAR(20) NOT NULL,
                description TEXT NOT NULL,
                equipment_id INTEGER REFERENCES equipment(id),
                consumable_id INTEGER REFERENCES consumable(id),
                created_by INTEGER NOT NULL REFERENCES user(id),
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Insert data back from backup
        cursor.execute("""
            INSERT INTO student_note 
            SELECT * FROM student_note_backup
        """)
        
        # Drop the backup table
        cursor.execute("DROP TABLE student_note_backup")
        
        conn.commit()
        print("Rollback completed successfully!")
        
    except sqlite3.Error as e:
        print(f"An error occurred during rollback: {e}")
        conn.rollback()
        raise
    
    finally:
        conn.close()

if __name__ == "__main__":
    # Configuration
    DATABASE_PATH = "instance/database.db"  # Update this with your actual database path
    
    print("Database Migration Tool")
    print("1. Migrate to new schema")
    print("2. Rollback migration")
    
    choice = input("Enter your choice (1 or 2): ").strip()
    
    if choice == "1":
        migrate_database(DATABASE_PATH)
    elif choice == "2":
        confirm = input("Are you sure you want to rollback? This will remove the new columns (y/N): ")
        if confirm.lower() == 'y':
            rollback_migration(DATABASE_PATH)
        else:
            print("Rollback cancelled.")
    else:
        print("Invalid choice. Please run the script again.")