"""
Migration script to split borrower/user names and course/section fields.
Adds new columns and backfills from existing combined fields when available.
"""
import os
import sqlite3

basedir = os.path.abspath(os.path.dirname(__file__))
db_path = os.path.join(basedir, "instance", "database.db")


def _column_exists(cursor, table_name, column_name):
    cursor.execute(f"PRAGMA table_info({table_name})")
    return any(row[1] == column_name for row in cursor.fetchall())


def _split_name(full_name):
    if not full_name:
        return "", ""
    parts = [p for p in str(full_name).strip().split() if p]
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], " ".join(parts[1:])


def _parse_course_section(section_course):
    if not section_course:
        return "", ""
    text = str(section_course).strip()
    if not text:
        return "", ""

    first_token = text.split()[0]
    if "-" in first_token:
        parts = first_token.split("-", 1)
        course_code = parts[0].strip()
        section = parts[1].strip() if len(parts) > 1 else ""
        return course_code, section

    if "/" in text:
        parts = [p.strip() for p in text.split("/") if p.strip()]
        if len(parts) >= 2:
            return parts[0], parts[1]

    tokens = [t for t in text.split() if t]
    if len(tokens) >= 2:
        return tokens[0], tokens[1]

    return text, ""


def migrate():
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        print("Starting name/course split migration...")

        # Borrow logs
        if not _column_exists(cursor, "borrow_log", "borrower_first_name"):
            cursor.execute("ALTER TABLE borrow_log ADD COLUMN borrower_first_name VARCHAR(120)")
        if not _column_exists(cursor, "borrow_log", "borrower_last_name"):
            cursor.execute("ALTER TABLE borrow_log ADD COLUMN borrower_last_name VARCHAR(120)")
        if not _column_exists(cursor, "borrow_log", "course_code"):
            cursor.execute("ALTER TABLE borrow_log ADD COLUMN course_code VARCHAR(80)")
        if not _column_exists(cursor, "borrow_log", "section"):
            cursor.execute("ALTER TABLE borrow_log ADD COLUMN section VARCHAR(80)")

        # Usage logs
        if not _column_exists(cursor, "usage_log", "user_first_name"):
            cursor.execute("ALTER TABLE usage_log ADD COLUMN user_first_name VARCHAR(120)")
        if not _column_exists(cursor, "usage_log", "user_last_name"):
            cursor.execute("ALTER TABLE usage_log ADD COLUMN user_last_name VARCHAR(120)")
        if not _column_exists(cursor, "usage_log", "course_code"):
            cursor.execute("ALTER TABLE usage_log ADD COLUMN course_code VARCHAR(80)")
        if not _column_exists(cursor, "usage_log", "section"):
            cursor.execute("ALTER TABLE usage_log ADD COLUMN section VARCHAR(80)")

        conn.commit()

        # Backfill borrow_log
        borrow_has_name = _column_exists(cursor, "borrow_log", "borrower_name")
        borrow_has_section_course = _column_exists(cursor, "borrow_log", "section_course")
        if borrow_has_name or borrow_has_section_course:
            cursor.execute("SELECT id, borrower_name, borrower_first_name, borrower_last_name, section_course, course_code, section FROM borrow_log")
            for row in cursor.fetchall():
                row_id, borrower_name, first_name, last_name, section_course, course_code, section = row
                new_first = first_name or ""
                new_last = last_name or ""
                new_course = course_code or ""
                new_section = section or ""

                if borrow_has_name and (not new_first and not new_last):
                    new_first, new_last = _split_name(borrower_name)

                if borrow_has_section_course and (not new_course and not new_section):
                    new_course, new_section = _parse_course_section(section_course)

                cursor.execute(
                    """
                    UPDATE borrow_log
                    SET borrower_first_name = ?, borrower_last_name = ?, course_code = ?, section = ?
                    WHERE id = ?
                    """,
                    (new_first, new_last, new_course, new_section, row_id),
                )

        # Backfill usage_log
        usage_has_name = _column_exists(cursor, "usage_log", "user_name")
        usage_has_section_course = _column_exists(cursor, "usage_log", "section_course")
        if usage_has_name or usage_has_section_course:
            cursor.execute("SELECT id, user_name, user_first_name, user_last_name, section_course, course_code, section FROM usage_log")
            for row in cursor.fetchall():
                row_id, user_name, first_name, last_name, section_course, course_code, section = row
                new_first = first_name or ""
                new_last = last_name or ""
                new_course = course_code or ""
                new_section = section or ""

                if usage_has_name and (not new_first and not new_last):
                    new_first, new_last = _split_name(user_name)

                if usage_has_section_course and (not new_course and not new_section):
                    new_course, new_section = _parse_course_section(section_course)

                cursor.execute(
                    """
                    UPDATE usage_log
                    SET user_first_name = ?, user_last_name = ?, course_code = ?, section = ?
                    WHERE id = ?
                    """,
                    (new_first, new_last, new_course, new_section, row_id),
                )

        conn.commit()
        print("✓ Name/course split migration completed successfully!")

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
