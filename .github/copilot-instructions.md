# CMT Inventory System - AI Coding Assistant Instructions

## Project Overview
Flask-based inventory tracking for Trinity University of Asia Medical Technology Department. The app manages:
- Equipment lifecycle (registry, borrow/return, maintenance, barcode printing)
- Consumable lifecycle (stock movement, usage, returnable-item returns, expiration tracking)
- Bulk operations via reusable mixed item sets
- Faculty-in-charge assignment for student transactions
- Audit logs, PDF exports, analytics, and local database backup/restore workflows

Primary app entry is `app.py` with SQLAlchemy models in `models.py`.

## Architecture and Data Model

### Core Models (`models.py`)
- **User**: `username`, hashed `password`, `role` (`admin`, `tech`, `faculty`)
- **Equipment**: inventory row with `qty`, metadata fields, and `barcode`
- **Consumable**: row-level stock fields (`items_out`, `items_on_stock`, `balance_stock`, `previous_month_stock`, `units_consumed`, `units_expired`), plus `is_returnable` and `barcode`
- **FacultyInCharge**: reusable faculty lookup table; referenced by borrow/usage logs
- **BorrowLog**: borrower identity, type, section/course, purpose, optional `faculty_in_charge_id`, `equipment_id`, `quantity_borrowed`, timestamps
- **UsageLog**: user identity, type, section/course, purpose, optional `faculty_in_charge_id`, `consumable_id`, `quantity_used`, `returned_at`
- **StudentNote**: issue records (`lost`, `damaged`, `other`) with `pending`/`resolved` workflow
- **EquipmentMaintenance**: scheduled/completed/overdue maintenance tracking and cost
- **AuditLog**: user and system action history with IP and timestamp
- **ItemSet** and **ItemSetItem**: mixed sets of equipment and consumables for bulk borrow/use workflows

## Critical Business Logic

### Consumable Row-Level Recalculation
Always maintain consumable computed fields using this pattern after quantity edits:
```python
normalize_row_nonnegatives(consumable)
recalc_single_row(consumable)
```

`recalc_single_row` updates row values as:
- `balance_stock = items_out + items_on_stock`
- `previous_month_stock = items_out + items_on_stock + units_consumed`

### Stock Deduction
Use `consume_by_id(consumable_id, quantity)` when usage should deduct from `items_out` for one specific consumable row.

### Returnable Consumables
In return flow (`/consumables/return/<usage_id>`), only return stock when `consumable.is_returnable` is true. Returned quantity is added back to `items_out`, then recalc is required.

### Faculty Requirement Rule
Use `_faculty_required(user_type, faculty_id_value)` for borrow/use flows:
- If actor type is `student`, faculty-in-charge selection is required.

### Audit Trail
Always log important state changes:
- `log_action(action, details)` for user-triggered events
- `log_system_action(action, details)` for background/system events (for example weekly backup worker)

## Barcode System
- Generation uses `python-barcode` (`ImageWriter` and `SVGWriter`)
- Lookup route: `/barcode/lookup?code=VALUE`
- Print routes include row-level and bulk printing
- Equipment/consumables can regenerate barcodes

## Backup and Operations

### Local Backups
- Database path: `instance/database.db`
- Backups stored in: `instance/backup/`
- Weekly auto-backup worker runs in a background thread and records state in:
  - `instance/backup/last_weekly_backup.txt`

### Backup Routes
- Manual backup download: `/backup`
- Admin backup management:
  - `/admin/backups/download/<filename>`
  - `/admin/backups/delete/<filename>`
  - `/admin/backups/restore/<filename>`

### Shutdown Flow
- `/admin/shutdown` logs event, triggers backup, and sends process stop signal.

## Authorization Conventions
Use role guards consistently:
- Tech/Admin-only sections generally use:
  - `if session.get('role') not in ['admin', 'tech']: return redirect(url_for('dashboard'))`
- Admin-only sections (user management, system logs, backup file management) use:
  - `if session.get('role') != 'admin': return redirect(url_for('dashboard'))`

## Reporting and Analytics
- PDF exports rely on ReportLab and generally use landscape A4 tables.
- Key export routes:
  - `/consumables/export/pdf`
  - `/equipment/export/pdf`
  - `/history/export/pdf`
  - `/analytics/export/pdf`
  - `/maintenance/export/pdf`
  - `/admin/logs/export/pdf`

## Developer Workflows

### Run and Stop
- Start app: `run.bat`
- Stop app: `stop.bat`
- PID file: `flask.pid`

### Migrations
When schema mismatches occur, check `models.py` together with migration scripts:
- `migration_script.py`
- `migrate_maintenance.py`
- `migrate_barcode.py`
- `migrate_audit_log.py`
- `migrate_name_course_split.py`
- `migrate_faculty_in_charge.py`
- `migrate_item_sets.py`

Most migrations use SQLite `PRAGMA table_info(...)` checks for safe, additive changes.

## Common Gotchas
- **Computed stock fields are not independent source-of-truth values**: after changing row quantities, recalc before commit.
- **Deletion requires dependent cleanup**: equipment/consumable deletes should account for related logs/notes to avoid FK issues.
- **Faculty-in-charge integrity**: student borrower/user flows should not bypass `_faculty_required` validation.
- **Maintenance status drift**: maintenance list view updates overdue status at read time for scheduled items past due date.
- **Backup route permissions differ**: `/backup` currently lacks admin gate, while `/admin/backups/*` routes are admin-restricted.
- **Date sorting for consumables**: use `_expiration_sort_key` when sorting mixed expiration formats (`YYYY-MM-DD` vs `N/A`).
