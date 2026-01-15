# CMT Inventory System - AI Coding Assistant Instructions

## Project Overview
Flask-based inventory tracking for Trinity University of Asia Medical Technology dept. Manages equipment (borrowing/returns, maintenance, barcodes), consumables (usage, expiration, returnable supplies), and audit logging. Includes PDF reporting and data analytics.

## Architecture & Data Model

### Database Models (`models.py`)
- **User**: Role-based access (`admin`, `tech`, `faculty`) with hashed passwords.
- **Equipment**: Main equipment registry with `barcode` support and metadata.
- **Consumable**: Inventory tracking with `items_out` (lab stock), `items_on_stock` (replenishment), and `is_returnable` flag for bulk liquids/powders.
- **BorrowLog**: Equipment borrow records; tracks `borrower_type` (student/faculty) and `quantity_borrowed`.
- **UsageLog**: Consumable usage; supports `returned_at` for returnable items.
- **EquipmentMaintenance**: Tracks `maintenance_type` (calibration/repair/preventive/inspection), `scheduled_date`, `completed_date`, and `status` (scheduled/completed/overdue).
- **AuditLog**: System-wide action tracking; use `log_action(action, details)` helper in `app.py`.
- **StudentNote**: Workflow-based issue tracking (`pending`/`resolved`) for lost/damaged items.

### Critical Inventory Logic
The consumable inventory uses a **row-level calculation pattern**:
```python
# Always call after modifying consumable quantities:
recalc_single_row(consumable)  # Recalculates balance_stock and previous_month_stock
normalize_row_nonnegatives(consumable)  # Ensures non-negative values
```
**Stock deduction**: Use `consume_by_id(id, qty)` to reduce `items_out` (lab stock).
**Audit Trail**: Always call `log_action("Action Name", "Details")` after critical inventory or system changes.

### Barcode System
- Uses `python-barcode` for ID-based generation.
- Routes `/barcode/lookup?code=VALUE` for scanning into usage/borrow forms.
- Items have a `barcode` field (auto-generated or manual).

## Developer Workflows

### Running the Application
- **Start**: `run.bat` (activates `cmt_inventory` conda env, runs `app.py`, saves PID).
- **Stop**: `stop.bat` (kills process via `flask.pid`).
- **Database**: SQLite at `instance/database.db`.

### Database Migrations
Always check `models.py` against migration scripts (`migration_script.py`, `migrate_maintenance.py`, `migrate_barcode.py`, `migrate_audit_log.py`) when schema issues arise. Use `PRAGMA table_info` pattern for safe additions.

## Project-Specific Conventions

### Session & Authorization
- `if session.get('role') not in ['admin', 'tech']: return redirect(url_for('dashboard'))`
- Maintenance and Audit Logs are restricted to `admin` and `tech` roles.

### Reporting & Analytics
- **PDF Export**: Uses ReportLab (landscape A4). Routes: `/history/export/pdf`, `/analytics/export/pdf`.
- **Analytics**: Route `/analytics` aggregates stock levels, usage trends, and maintenance costs.

### Integration Points
- **Return Workflow**:
  - Equipment: Mark `BorrowLog.returned_at`.
  - Consumables: If `is_returnable=True`, add `quantity_used` back to `items_out`.
- **Maintenance Alerts**: Dashboard shows "Overdue" and "Upcoming" (within 7 days) maintenance items.

## Common Gotchas
- **Calculated Fields**: `Equipment.in_use` and `on_stock` are NOT in DB; calculated via subqueries in routes.
- **Cascade Deletes**: Manually delete `BorrowLog` and `StudentNote` records before deleting an `Equipment` or `Consumable` to avoid FK errors.
- **Date Handling**: Use `_expiration_sort_key` for sorting messy expiration date strings.
