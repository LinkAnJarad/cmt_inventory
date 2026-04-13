"""
Migration script to add ItemSet and ItemSetItem tables.
Run this once to enable mixed item sets for equipment and consumables.
"""
import os
import sqlite3

basedir = os.path.abspath(os.path.dirname(__file__))
db_path = os.path.join(basedir, "instance", "database.db")


def migrate():
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        print("Starting ItemSet migration...")

        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='item_set'")
        if cursor.fetchone():
            print("✓ ItemSet table already exists. No migration needed.")
            return

        print("Creating item_set table...")
        cursor.execute("""
            CREATE TABLE item_set (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name VARCHAR(120) NOT NULL,
                set_type VARCHAR(20),
                created_by INTEGER,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (created_by) REFERENCES user (id)
            )
        """)

        print("Creating item_set_item table...")
        cursor.execute("""
            CREATE TABLE item_set_item (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                set_id INTEGER NOT NULL,
                equipment_id INTEGER,
                consumable_id INTEGER,
                quantity INTEGER NOT NULL DEFAULT 1,
                FOREIGN KEY (set_id) REFERENCES item_set (id),
                FOREIGN KEY (equipment_id) REFERENCES equipment (id),
                FOREIGN KEY (consumable_id) REFERENCES consumable (id)
            )
        """)

        conn.commit()
        print("✓ ItemSet migration completed successfully!")

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
