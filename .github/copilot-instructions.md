# CMT Inventory System - AI Coding Assistant Instructions

## Project Overview
Flask-based laboratory equipment and consumables tracking system for Trinity University of Asia Medical Technology department. Manages borrowing/returning equipment, tracking consumable usage with expiration dates, and generating PDF reports.

## Architecture & Data Model

### Database Models (`models.py`)
- **User**: Role-based access (admin, tech, faculty) with hashed passwords
- **Equipment**: Lab equipment with qty tracking, metadata (serial, brand, model, location)
- **Consumable**: Medical supplies with complex inventory tracking (items_out, items_on_stock, previous_month_stock, units_consumed, is_returnable flag)
- **BorrowLog**: Equipment borrowing records with `quantity_borrowed` for bulk operations, tracks `borrower_type` (student/faculty)
- **UsageLog**: Consumable usage tracking with returnable item support via `returned_at` field
- **StudentNote**: Issue tracking (lost/damaged/other) with status workflow (pending/resolved)

### Critical Inventory Logic
The consumable inventory uses a **row-level calculation pattern**:
```python
# Always call after modifying consumable quantities:
recalc_single_row(consumable)  # Recalculates balance_stock and previous_month_stock
normalize_row_nonnegatives(consumable)  # Ensures non-negative values
```

**Stock deduction**: Use `consume_by_id(consumable_id, quantity)` to reduce `items_out` (lab stock) - never modify directly.

### Computed Columns Pattern
Equipment routes calculate "in_use" and "on_stock" dynamically:
```python
active_borrows_sq = db.session.query(
    BorrowLog.equipment_id.label('eq_id'),
    func.sum(BorrowLog.quantity_borrowed).label('in_use')
).filter(BorrowLog.returned_at.is_(None)).group_by(BorrowLog.equipment_id).subquery()

# Then attach to Equipment objects: setattr(e, 'in_use', int(in_use or 0))
```

## Developer Workflows

### Running the Application
- **Start**: `run.bat` - Activates conda env `cmt_inventory`, runs via `pythonw app.py`, stores PID in `flask.pid`
- **Stop**: `stop.bat` - Reads PID from `flask.pid`, terminates process
- **Database**: SQLite at `instance/database.db` (auto-created on first run)
- **Default Admin**: username `admin`, password `admin123`

### Database Migrations
Use `migration_script.py` for schema changes. Example pattern:
```python
cursor.execute("PRAGMA table_info(table_name)")
columns = [column[1] for column in cursor.fetchall()]
if 'new_column' not in columns:
    cursor.execute("ALTER TABLE table_name ADD COLUMN new_column TYPE")
```

## Project-Specific Conventions

### Session & Authorization
- Session stores `user_id` and `role` (admin/tech/faculty)
- Routes check: `if session.get('role') not in ['admin', 'tech']: return redirect(url_for('dashboard'))`
- Admin-only routes: user management, deletions

### URL Query Parameters
All list views support `?q=search&sort=field&dir=asc|desc`:
- Equipment: sortable by computed fields `in_use`, `on_stock`
- Consumables: includes `is_returnable` sorting
- History: separate params `b_q/b_sort/b_dir` (borrowing) and `u_q/u_sort/u_dir` (usage)

### PDF Export Pattern
All export routes (`/equipment/export/pdf`, `/consumables/export/pdf`, `/history/export/pdf`):
- Use ReportLab with landscape A4 orientation
- Respect current view filters (q, sort, dir)
- Generate timestamped filenames: `{type}_report_{YYYYmmdd_HHMMSS}.pdf`
- Use Paragraph objects for text wrapping in table cells

### Input Sanitization Helpers
```python
_to_int(value, default=0)  # Safe string-to-int conversion
_clamp_nonneg(x)  # Ensures non-negative integers
```
Always use these when processing form inputs for quantities.

## Integration Points

### Template Data Flow
- `base.html`: Shows navigation only when `session.get('user_id')` exists
- Templates receive computed attributes attached via `setattr()` (e.g., equipment.in_use)
- Bulk operations (`bulk_operations.html`) handle multiple item selections via form arrays (`equipment_ids[]`, `quantities[]`)

### Return Workflow
1. Equipment: Mark `BorrowLog.returned_at`, optionally create StudentNote
2. Consumables: Only if `is_returnable=True`, add returned quantity back to `items_out`, mark UsageLog.returned_at

### Student Notes Status Workflow
- Created with `status='pending'`, `created_by=session['user_id']`
- Toggle via `/notes/toggle_status/<id>`: pending ↔ resolved (sets `resolved_at`, `resolved_by`)
- Filterable in UI: `?status=pending|resolved|all`

## Testing & Debugging
- `print_db.py`: Utility to inspect database state
- `list.py`: Check installed package versions
- Sample data seeded on first run (see `equipment_data`, `consumables_data` in app.py)
- Use `outerjoin` for User relationships in StudentNote queries to avoid filtering out orphaned records

## Common Gotchas
- **Consumable calculations**: Always call `recalc_single_row()` after quantity changes, otherwise balance_stock will be stale
- **Bulk operations**: BorrowLog uses `quantity_borrowed` sum, not count of logs
- **Foreign key cleanup**: Delete dependent records before parent (see `delete_equipment`, `delete_consumable` routes)
- **Returnable consumables**: Check `Consumable.is_returnable` before showing return UI
