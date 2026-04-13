"""
Migration script to add ArchiveRecord table.
"""
import os
import sqlite3

basedir = os.path.abspath(os.path.dirname(__file__))
db_path = os.path.join(basedir, "instance", "database.db")


def migrate():
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        print("Starting ArchiveRecord migration...")

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS archive_record (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_table VARCHAR(64) NOT NULL,
                source_id INTEGER,
                record_date DATETIME,
                payload_json TEXT NOT NULL,
                archived_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                archived_by INTEGER,
                FOREIGN KEY (archived_by) REFERENCES user(id)
            )
        """)

        conn.commit()
        print("\u2713 ArchiveRecord migration completed successfully!")

    except sqlite3.Error as e:
        print(f"\u2717 Error during migration: {e}")
        conn.rollback()
    finally:
        conn.close()


if __name__ == "__main__":
    if not os.path.exists(db_path):
        print(f"\u2717 Database not found at {db_path}")
        print("  Run the application first to create the database.")
    else:
        migrate()
