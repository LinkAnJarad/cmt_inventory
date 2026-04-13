"""
Migration script to add FacultyInCharge table and link it to BorrowLog and UsageLog.
"""
import os
import sqlite3

basedir = os.path.abspath(os.path.dirname(__file__))
db_path = os.path.join(basedir, "instance", "database.db")


def _column_exists(cursor, table_name, column_name):
    cursor.execute(f"PRAGMA table_info({table_name})")
    return any(row[1] == column_name for row in cursor.fetchall())


def migrate():
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        print("Starting FacultyInCharge migration...")

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS faculty_in_charge (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name VARCHAR(120) NOT NULL UNIQUE,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)

        if not _column_exists(cursor, "borrow_log", "faculty_in_charge_id"):
            cursor.execute("""
                ALTER TABLE borrow_log
                ADD COLUMN faculty_in_charge_id INTEGER REFERENCES faculty_in_charge(id)
            """)

        if not _column_exists(cursor, "usage_log", "faculty_in_charge_id"):
            cursor.execute("""
                ALTER TABLE usage_log
                ADD COLUMN faculty_in_charge_id INTEGER REFERENCES faculty_in_charge(id)
            """)

        conn.commit()
        print("✓ FacultyInCharge migration completed successfully!")

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
