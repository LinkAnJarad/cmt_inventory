import sqlite3
import os

def migrate_audit_log():
    # Database path
    db_path = os.path.join(os.path.dirname(__file__), "instance", "database.db")
    
    if not os.path.exists(db_path):
        print(f"Error: Database not found at {db_path}")
        return

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        print("Starting AuditLog table migration...")

        # Create the audit_log table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                action VARCHAR(100) NOT NULL,
                details TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                ip_address VARCHAR(45),
                FOREIGN KEY(user_id) REFERENCES user(id)
            )
        """)
        
        print("✓ AuditLog table created or already exists.")
        
        # Verify the table structure
        cursor.execute("PRAGMA table_info(audit_log)")
        columns = cursor.fetchall()
        print("Current audit_log columns:")
        for col in columns:
            print(f" - {col[1]} ({col[2]})")

        conn.commit()
        print("\nMigration completed successfully!")

    except sqlite3.Error as e:
        print(f"An error occurred: {e}")
        conn.rollback()
    finally:
        conn.close()

if __name__ == "__main__":
    migrate_audit_log()
