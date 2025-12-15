import os
import io
import uuid
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, session, send_file, jsonify
from models import db, User, Equipment, Consumable, BorrowLog, UsageLog, StudentNote, EquipmentMaintenance
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy import or_, func

# Barcode generation
import barcode
from barcode.writer import ImageWriter, SVGWriter

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch

# Save process ID so we can stop it later
with open("flask.pid", "w") as f:
    f.write(str(os.getpid()))

app = Flask(__name__)
app.secret_key = 'random_secret_key_for_the_meantime_dev'

# Configure SQLite database with absolute path
basedir = os.path.abspath(os.path.dirname(__file__))
app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{os.path.join(basedir, "instance", "database.db")}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)

def _to_int(value, default=0):
    try:
        if value is None:
            return default
        if isinstance(value, int):
            return value
        s = str(value).strip()
        if s == "" or s.upper() == "N/A":
            return default
        return int(s)
    except Exception:
        return default

def _clamp_nonneg(x):
    x = _to_int(x, 0)
    return 0 if x < 0 else x

def _expiration_sort_key(exp):
    """
    Sort ISO-like dates first (YYYY-MM-DD), then anything else (like 'N/A') later.
    """
    s = (exp or "").strip()
    # Heuristic: ISO date is 10 chars and contains two dashes.
    if len(s) == 10 and s.count("-") == 2:
        return (0, s)  # earlier in sort
    return (1, s)      # later in sort

def normalize_row_nonnegatives(row: Consumable):
    row.items_out = _clamp_nonneg(row.items_out)
    row.items_on_stock = _clamp_nonneg(row.items_on_stock)
    row.units_consumed = _clamp_nonneg(row.units_consumed)

def recalc_row_level_values(row: Consumable):
    """
    Calculate row-level values:
      balance_stock = items_out + items_on_stock
      previous_month_stock = items_out + items_on_stock + units_consumed
    """
    # Normalize row-level nonnegatives first
    normalize_row_nonnegatives(row)
    
    # Calculate balance_stock for this specific row
    row_balance_stock = _clamp_nonneg(_to_int(row.items_out, 0) + _to_int(row.items_on_stock, 0))
    
    # Calculate previous_month_stock: items_out + items_on_stock + units_consumed
    row_previous_month_stock = _clamp_nonneg(
        _to_int(row.items_out, 0) + 
        _to_int(row.items_on_stock, 0) + 
        _to_int(row.units_consumed, 0)
    )
    
    # Assign the calculated values to the row
    row.balance_stock = row_balance_stock
    row.previous_month_stock = row_previous_month_stock



def recalc_single_row(row: Consumable):
    """
    Convenience function to recalculate values for a single row.
    """
    recalc_row_level_values(row)

# def consume_from_group(description: str, quantity: int):
#     """
#     Reduce items_out (lab stock) across the group FIFO by expiration date.
#     Returns the remaining quantity that could not be fulfilled (0 if fully applied).
#     """
#     remaining = _clamp_nonneg(quantity)
#     if remaining == 0:
#         return 0

#     rows = (Consumable.query
#             .filter(Consumable.description == description)
#             .all())
#     # Sort rows by expiration heuristic (soonest usable first)
#     rows.sort(key=lambda r: _expiration_sort_key(r.expiration))

#     for r in rows:
#         out = _clamp_nonneg(r.items_out)
#         if out <= 0:
#             continue
#         take = min(out, remaining)
#         r.items_out = out - take
#         remaining -= take
#         if remaining == 0:
#             break
#     return remaining

def consume_from_single_consumable(consumable_id: int, quantity: int):
    """
    Reduce items_out (lab stock) from a specific consumable by id.
    Returns the remaining quantity that could not be fulfilled (0 if fully applied).
    """
    remaining = _clamp_nonneg(quantity)
    if remaining == 0:
        return 0

    c = Consumable.query.get(consumable_id)
    if not c:
        return remaining
    
    out = _clamp_nonneg(c.items_out)
    if out <= 0:
        return remaining
    
    take = min(out, remaining)
    c.items_out = out - take
    remaining -= take
    
    return remaining

# Ensure DB + default admin user exist and seed
with app.app_context():
    os.makedirs(os.path.join(basedir, "instance"), exist_ok=True)
    db.create_all()

    # ADD: Update existing records to have default status
    try:
        # Check if status column exists, if not it will be created by create_all()
        existing_notes = StudentNote.query.filter(StudentNote.status.is_(None)).all()
        for note in existing_notes:
            note.status = 'pending'
        db.session.commit()
    except:
        # Column might not exist yet, will be created by create_all()
        pass

    # Sample data for equipment
    equipment_data = [
        {
            "description": "BELL",
            "qty": 9,
            "date_purchased": "08-22-2024",
            "serial_number": "NOT APPLICABLE",
            "brand_name": "NOT APPLICABLE",
            "model": "NOT APPLICABLE",
            "remarks": "OPERATIONAL",
            "location": "LABORATORY INSTRUMENTATION ROOM"
        },
        {
            "description": "PORTABLE SPEAKER",
            "qty": 1,
            "date_purchased": "10-03-2019",
            "serial_number": "806521005496",
            "brand_name": "CROWN",
            "model": "PRO-2008R",
            "remarks": "OPERATIONAL",
            "location": "LABORATORY INSTRUMENTATION ROOM"
        },
        {
            "description": "PORTABLE SPEAKER",
            "qty": 1,
            "date_purchased": "12-12-2016",
            "serial_number": "NOT APPLICABLE",
            "brand_name": "LUMANOG STORE",
            "model": "PRO5017R",
            "remarks": "OPERATIONAL",
            "location": "LABORATORY INSTRUMENTATION ROOM"
        },
        {
            "description": "PORTABLE SPEAKER",
            "qty": 1,
            "date_purchased": "04-07-2016",
            "serial_number": "NOT APPLICABLE",
            "brand_name": "LUMANOG STORE",
            "model": "PRO5017R",
            "remarks": "OPERATIONAL",
            "location": "LABORATORY INSTRUMENTATION ROOM"
        },
        {
            "description": "PORTABLE SPEAKER",
            "qty": 1,
            "date_purchased": "10-06-2015",
            "serial_number": "NOT APPLICABLE",
            "brand_name": "LUMANOG STORE",
            "model": "PRO5017R",
            "remarks": "OPERATIONAL",
            "location": "LABORATORY INSTRUMENTATION ROOM"
        },
        {
            "description": "DIGITAL TIMER",
            "qty": 5,
            "date_purchased": "09-29-2023",
            "serial_number": "NOT APPLICABLE",
            "brand_name": "WONDFO",
            "model": "NOT APPLICABLE",
            "remarks": "OPERATIONAL",
            "location": "LABORATORY INSTRUMENTATION ROOM"
        }
    ]

    # Sample data for consumables
    consumables_data = [
        {
            "balance_stock": 2,
            "unit": "boxes",
            "description": "10cc syringe",
            "expiration": "2028-04-30",
            "lot_number": "230523L",
            "date_received": "2023-07-26",
            "items_out": 0,
            "items_on_stock": 0,
            "previous_month_stock": 3,
            "units_consumed": 1,
            "units_expired": None,
            "is_returnable": False
        },
        {
            "balance_stock": 2,
            "unit": "boxes",
            "description": "10cc syringe",
            "expiration": "2028-05-31",
            "lot_number": "230622E",
            "date_received": "2024-01-25",
            "items_out": 1,
            "items_on_stock": 1,
            "previous_month_stock": 3,
            "units_consumed": 0,
            "units_expired": None,
            "is_returnable": False
        },
        {
            "balance_stock": 4,
            "unit": "boxes",
            "description": "5cc syringe",
            "expiration": "2028-11-30",
            "lot_number": "231213R",
            "date_received": "2024-01-25",
            "items_out": 0,
            "items_on_stock": 0,
            "previous_month_stock": 7,
            "units_consumed": 3,
            "units_expired": None,
            "is_returnable": False
        },
        {
            "balance_stock": 4,
            "unit": "boxes",
            "description": "5cc syringe",
            "expiration": "2029-03-31",
            "lot_number": "240412C",
            "date_received": "2024-08-13",
            "items_out": 0,
            "items_on_stock": 0,
            "previous_month_stock": 7,
            "units_consumed": 0,
            "units_expired": None,
            "is_returnable": False
        },
        {
            "balance_stock": 4,
            "unit": "boxes",
            "description": "5cc syringe",
            "expiration": "2029-04-01",
            "lot_number": "240411R",
            "date_received": "2024-08-13",
            "items_out": 1,
            "items_on_stock": 0,
            "previous_month_stock": 7,
            "units_consumed": 0,
            "units_expired": None,
            "is_returnable": False
        },
        {
            "balance_stock": 4,
            "unit": "boxes",
            "description": "5cc syringe",
            "expiration": "2029-09-14",
            "lot_number": "20240915Z",
            "date_received": "2025-02-07",
            "items_out": 1,
            "items_on_stock": 2,
            "previous_month_stock": 7,
            "units_consumed": 0,
            "units_expired": None,
            "is_returnable": False
        },
        {
            "balance_stock": 2,
            "unit": "packs",
            "description": "Activated charcoal",
            "expiration": "N/A",
            "lot_number": "N/A",
            "date_received": "N/A",
            "items_out": 0,
            "items_on_stock": 2,
            "previous_month_stock": 2,
            "units_consumed": 0,
            "units_expired": None,
            "is_returnable": False
        },
        {
            "balance_stock": 1,
            "unit": "roll",
            "description": "Alcohol lamp wick",
            "expiration": "N/A",
            "lot_number": "N/A",
            "date_received": "N/A",
            "items_out": 0,
            "items_on_stock": 2,
            "previous_month_stock": 2,
            "units_consumed": 1,
            "units_expired": None,
            "is_returnable": False
        },
        {
            "balance_stock": 10,
            "unit": "ml",
            "description": "Alcohol",
            "expiration": "N/A",
            "lot_number": "N/A",
            "date_received": "2024-02-01",
            "items_out": 0,
            "items_on_stock": 6,
            "previous_month_stock": 16,
            "units_consumed": 0,
            "units_expired": None,
            "is_returnable": True
        }
    ]

    # Populate equipment if table is empty
    if Equipment.query.count() == 0:
        for item_data in equipment_data:
            equipment = Equipment(**item_data)
            db.session.add(equipment)
        print("Equipment data populated")

    # Populate consumables if table is empty
    if Consumable.query.count() == 0:
        for item_data in consumables_data:
            consumable = Consumable(**item_data)
            # normalize nonnegatives before grouping
            normalize_row_nonnegatives(consumable)
            db.session.add(consumable)
        print("Consumables data populated")

    if not User.query.filter_by(username='admin').first():
        admin = User(
            username='admin',
            password=generate_password_hash('admin123'),
            role='admin'
        )
        db.session.add(admin)

    db.session.commit()

    # After seeding, recalculate individual row values
    for consumable in Consumable.query.all():
        recalc_single_row(consumable)
    db.session.commit()

@app.route('/')
def index():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        user = User.query.filter_by(username=username).first()

        if user and check_password_hash(user.password, password):
            session['user_id'] = user.id
            session['role'] = user.role
            return redirect(url_for('dashboard'))
        else:
            return "Invalid credentials"
    return render_template('login.html')

@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    from datetime import datetime, timedelta, date
    current_date = datetime.now().date()
    near_expiry_date = current_date + timedelta(days=30)
    
    # Low stock items (10% threshold)
    low_stock_consumables = (db.session.query(Consumable)
                           .filter(Consumable.previous_month_stock > 0)
                           .filter((Consumable.items_out + Consumable.items_on_stock) < (Consumable.previous_month_stock * 0.1))
                           .limit(5)  # Show top 5
                           .all())
    
    # Near expiration consumables (within 30 days or already expired)
    near_expiration = []
    for c in Consumable.query.all():
        if c.expiration and c.expiration != 'N/A':
            try:
                exp_date = datetime.strptime(c.expiration, '%Y-%m-%d').date()
                if exp_date <= near_expiry_date:
                    near_expiration.append(c)
            except ValueError:
                continue
    # Limit to top 5
    near_expiration = sorted(near_expiration, key=lambda x: x.expiration)[:5]
    
    # Maintenance alerts (overdue and upcoming)
    overdue_maintenance = (EquipmentMaintenance.query
                          .filter(EquipmentMaintenance.status == 'scheduled')
                          .filter(EquipmentMaintenance.scheduled_date < current_date)
                          .limit(5)
                          .all())
    
    # Update status to overdue
    for m in overdue_maintenance:
        m.status = 'overdue'
    db.session.commit()
    
    # Upcoming maintenance (next 7 days)
    upcoming_date = current_date + timedelta(days=7)
    upcoming_maintenance = (EquipmentMaintenance.query
                           .filter(EquipmentMaintenance.status == 'scheduled')
                           .filter(EquipmentMaintenance.scheduled_date >= current_date)
                           .filter(EquipmentMaintenance.scheduled_date <= upcoming_date)
                           .limit(5)
                           .all())
    
    return render_template('dashboard.html', 
                         role=session['role'],
                         low_stock=low_stock_consumables,
                         near_expiration=near_expiration,
                         overdue_maintenance=overdue_maintenance,
                         upcoming_maintenance=upcoming_maintenance)

# Update equipment function for bulk borrowing calculation
@app.route('/equipment')
def equipment():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    q = request.args.get('q', '').strip()
    sort = request.args.get('sort', 'description')
    direction = request.args.get('dir', 'asc').lower()
    direction = 'desc' if direction == 'desc' else 'asc'
    
    # New filter parameters
    location_filter = request.args.get('location', '').strip()
    brand_filter = request.args.get('brand', '').strip()
    date_from = request.args.get('date_from', '').strip()
    date_to = request.args.get('date_to', '').strip()

    # Whitelist of sortable fields, including computed ones
    sortable_fields = {
        'description', 'qty', 'date_purchased', 'serial_number',
        'brand_name', 'model', 'remarks', 'location',
        'in_use', 'on_stock'
    }
    if sort not in sortable_fields:
        sort = 'description'

    # Updated subquery to sum quantities for bulk borrowing
    active_borrows_sq = (db.session.query(
            BorrowLog.equipment_id.label('eq_id'),
            func.sum(BorrowLog.quantity_borrowed).label('in_use')  # Sum quantities instead of count
        )
        .filter(BorrowLog.returned_at.is_(None))
        .group_by(BorrowLog.equipment_id)
        .subquery())

    in_use_col = func.coalesce(active_borrows_sq.c.in_use, 0).label('in_use')
    on_stock_col = (func.coalesce(Equipment.qty, 0) - func.coalesce(active_borrows_sq.c.in_use, 0)).label('on_stock')

    # Base query with computed columns
    query = (db.session.query(Equipment, in_use_col, on_stock_col)
             .outerjoin(active_borrows_sq, Equipment.id == active_borrows_sq.c.eq_id))

    # Search across common text columns
    if q:
        like = f"%{q}%"
        query = query.filter(or_(
            Equipment.description.ilike(like),
            Equipment.serial_number.ilike(like),
            Equipment.brand_name.ilike(like),
            Equipment.model.ilike(like),
            Equipment.remarks.ilike(like),
            Equipment.location.ilike(like),
            Equipment.date_purchased.ilike(like),
        ))

    # Location filter
    if location_filter:
        query = query.filter(Equipment.location.ilike(f"%{location_filter}%"))

    # Brand filter
    if brand_filter:
        query = query.filter(Equipment.brand_name.ilike(f"%{brand_filter}%"))

    # Date range filter (date_purchased)
    if date_from:
        query = query.filter(Equipment.date_purchased >= date_from)
    if date_to:
        query = query.filter(Equipment.date_purchased <= date_to)

    # Sorting
    if sort == 'in_use':
        sort_col = in_use_col
    elif sort == 'on_stock':
        sort_col = on_stock_col
    else:
        sort_col = getattr(Equipment, sort)

    query = query.order_by(sort_col.desc() if direction == 'desc' else sort_col.asc())

    rows = query.all()

    # Attach computed fields onto Equipment objects for simple templating
    items = []
    for e, in_use, on_stock in rows:
        setattr(e, 'in_use', int(in_use or 0))
        setattr(e, 'on_stock', int(on_stock or 0))
        items.append(e)

    # Get unique values for filter dropdowns
    all_locations = db.session.query(Equipment.location).filter(Equipment.location.isnot(None)).distinct().all()
    locations = sorted([l[0] for l in all_locations if l[0] and l[0].strip()])
    
    all_brands = db.session.query(Equipment.brand_name).filter(Equipment.brand_name.isnot(None)).distinct().all()
    brands = sorted([b[0] for b in all_brands if b[0] and b[0].strip()])

    return render_template('equipment.html', items=items, q=q, sort=sort, dir=direction,
                         location_filter=location_filter, brand_filter=brand_filter,
                         date_from=date_from, date_to=date_to,
                         locations=locations, brands=brands)

@app.route('/consumables')
def consumables():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    q = request.args.get('q', '').strip()
    sort = request.args.get('sort', 'description')
    direction = request.args.get('dir', 'asc').lower()
    direction = 'desc' if direction == 'desc' else 'asc'
    
    # New filter parameters
    date_received_filter = request.args.get('date_received', '').strip()  # YYYY-MM (year-month)
    is_returnable_filter = request.args.get('is_returnable', '').strip()  # 'true', 'false', or empty for all
    date_from = request.args.get('date_from', '').strip()  # Date range start
    date_to = request.args.get('date_to', '').strip()      # Date range end
    group_by_month = request.args.get('group_by_month', '').strip()  # 'true' to group rows by month
    expiration_status = request.args.get('expiration_status', '').strip()  # 'expired', 'expiring_soon', 'ok', or empty for all
    stock_status = request.args.get('stock_status', '').strip()  # 'critical', 'depleting', or empty for all

    # Updated sortable fields (removed test and total)
    sortable_fields = {
        'description', 'balance_stock', 'unit', 'expiration', 'lot_number', 
        'date_received', 'items_out', 'items_on_stock', 'previous_month_stock', 
        'units_consumed', 'units_expired', 'is_returnable'
    }
    if sort not in sortable_fields:
        sort = 'description'

    query = Consumable.query

    if q:
        like = f"%{q}%"
        query = query.filter(or_(
            Consumable.description.ilike(like),
            Consumable.unit.ilike(like),
            Consumable.expiration.ilike(like),
            Consumable.lot_number.ilike(like),
            Consumable.date_received.ilike(like),
        ))

    # Returnable filter
    if is_returnable_filter in ['true', 'false']:
        is_returnable_val = is_returnable_filter == 'true'
        query = query.filter(Consumable.is_returnable == is_returnable_val)

    # Date received filter (specific month YYYY-MM or date range)
    if date_received_filter:
        # Filter by exact month (YYYY-MM format)
        query = query.filter(Consumable.date_received.like(f"{date_received_filter}%"))
    elif date_from or date_to:
        # Filter by date range
        if date_from:
            query = query.filter(Consumable.date_received >= date_from)
        if date_to:
            query = query.filter(Consumable.date_received <= date_to)

    # Expiration status filter
    if expiration_status:
        today = datetime.now().date()
        thirty_days_from_now = today + __import__('datetime').timedelta(days=30)
        
        if expiration_status == 'expired':
            # Items already expired
            query = query.filter(Consumable.expiration < today.strftime('%Y-%m-%d'))
        elif expiration_status == 'expiring_soon':
            # Items expiring within 30 days
            query = query.filter(
                Consumable.expiration >= today.strftime('%Y-%m-%d'),
                Consumable.expiration <= thirty_days_from_now.strftime('%Y-%m-%d')
            )
        elif expiration_status == 'ok':
            # Items not expiring soon
            query = query.filter(Consumable.expiration > thirty_days_from_now.strftime('%Y-%m-%d'))

    # Stock depletion filter - check if (items_out + items_on_stock) < 10% of previous_month_stock
    if stock_status:
        if stock_status == 'critical':
            # Critical: less than 10% of previous_month_stock remaining
            # balance_stock < 0.1 * previous_month_stock (where balance_stock = items_out + items_on_stock)
            query = query.filter(
                Consumable.previous_month_stock > 0,
                (Consumable.items_out + Consumable.items_on_stock) < (Consumable.previous_month_stock * 0.1)
            )
        elif stock_status == 'depleting':
            # Depleting: 10-25% of previous_month_stock remaining
            query = query.filter(
                Consumable.previous_month_stock > 0,
                (Consumable.items_out + Consumable.items_on_stock) >= (Consumable.previous_month_stock * 0.1),
                (Consumable.items_out + Consumable.items_on_stock) < (Consumable.previous_month_stock * 0.25)
            )

    sort_col = getattr(Consumable, sort)
    if direction == 'desc':
        query = query.order_by(sort_col.desc())
    else:
        query = query.order_by(sort_col.asc())

    items = query.all()
    
    # Group items by month if requested
    grouped_items = None
    if group_by_month == 'true':
        from collections import defaultdict
        grouped_items = defaultdict(list)
        for item in items:
            month_key = item.date_received[:7] if item.date_received else 'N/A'
            grouped_items[month_key].append(item)
        # Sort group keys
        grouped_items = dict(sorted(grouped_items.items(), reverse=True))

    # Get unique values for filter dropdowns
    all_months = db.session.query(
        func.substr(Consumable.date_received, 1, 7).label('month')
    ).filter(
        Consumable.date_received.isnot(None),
        func.length(Consumable.date_received) >= 7
    ).distinct().all()
    months = sorted([m[0] for m in all_months if m[0]], reverse=True)

    return render_template('consumables.html', items=items, q=q, sort=sort, dir=direction,
                         date_received_filter=date_received_filter,
                         date_from=date_from, date_to=date_to,
                         is_returnable_filter=is_returnable_filter,
                         group_by_month=group_by_month,
                         grouped_items=grouped_items,
                         available_months=months,
                         expiration_status=expiration_status,
                         stock_status=stock_status)

@app.route('/consumables/export/pdf')
def export_consumables_pdf():
    """
    Export the current consumables view (respecting q, sort, dir, date_received, date_from, date_to, is_returnable)
    to a landscape A4 PDF table with text wrapping.
    """
    if 'user_id' not in session:
        return redirect(url_for('login'))

    # Lazy import so the app can still run if reportlab isn't installed yet
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import inch
    except ImportError:
        return ("Missing dependency: reportlab. Install it first, e.g. "
                "`pip install reportlab`"), 500

    q = request.args.get('q', '').strip()
    sort = request.args.get('sort', 'description')
    direction = request.args.get('dir', 'asc').lower()
    direction = 'desc' if direction == 'desc' else 'asc'
    
    # New filter parameters
    date_received_filter = request.args.get('date_received', '').strip()
    is_returnable_filter = request.args.get('is_returnable', '').strip()
    date_from = request.args.get('date_from', '').strip()
    date_to = request.args.get('date_to', '').strip()
    expiration_status = request.args.get('expiration_status', '').strip()
    stock_status = request.args.get('stock_status', '').strip()

    # Updated sortable fields (removed test and total, added is_returnable)
    sortable_fields = {
        'description', 'balance_stock', 'unit', 'is_returnable',
        'expiration', 'lot_number', 'date_received', 'items_out',
        'items_on_stock', 'previous_month_stock', 'units_consumed', 'units_expired'
    }
    if sort not in sortable_fields:
        sort = 'description'

    query = Consumable.query
    if q:
        like = f"%{q}%"
        query = query.filter(or_(
            Consumable.description.ilike(like),
            Consumable.unit.ilike(like),
            Consumable.expiration.ilike(like),
            Consumable.lot_number.ilike(like),
            Consumable.date_received.ilike(like),
        ))

    # Apply new filters
    if is_returnable_filter in ['true', 'false']:
        is_returnable_val = is_returnable_filter == 'true'
        query = query.filter(Consumable.is_returnable == is_returnable_val)

    if date_received_filter:
        query = query.filter(Consumable.date_received.like(f"{date_received_filter}%"))
    elif date_from or date_to:
        if date_from:
            query = query.filter(Consumable.date_received >= date_from)
        if date_to:
            query = query.filter(Consumable.date_received <= date_to)

    # Expiration status filter
    if expiration_status:
        today = datetime.now().date()
        thirty_days_from_now = today + __import__('datetime').timedelta(days=30)
        
        if expiration_status == 'expired':
            query = query.filter(Consumable.expiration < today.strftime('%Y-%m-%d'))
        elif expiration_status == 'expiring_soon':
            query = query.filter(
                Consumable.expiration >= today.strftime('%Y-%m-%d'),
                Consumable.expiration <= thirty_days_from_now.strftime('%Y-%m-%d')
            )
        elif expiration_status == 'ok':
            query = query.filter(Consumable.expiration > thirty_days_from_now.strftime('%Y-%m-%d'))

    # Stock depletion filter
    if stock_status:
        if stock_status == 'critical':
            query = query.filter(
                Consumable.previous_month_stock > 0,
                (Consumable.items_out + Consumable.items_on_stock) < (Consumable.previous_month_stock * 0.1)
            )
        elif stock_status == 'depleting':
            query = query.filter(
                Consumable.previous_month_stock > 0,
                (Consumable.items_out + Consumable.items_on_stock) >= (Consumable.previous_month_stock * 0.1),
                (Consumable.items_out + Consumable.items_on_stock) < (Consumable.previous_month_stock * 0.25)
            )

    sort_col = getattr(Consumable, sort)
    query = query.order_by(sort_col.desc() if direction == 'desc' else sort_col.asc())
    items = query.all()

    # Build PDF
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        leftMargin=18, rightMargin=18, topMargin=24, bottomMargin=18,
    )

    styles = getSampleStyleSheet()
    
    # Create custom style for table cells
    cell_style = ParagraphStyle(
        'CellStyle',
        parent=styles['Normal'],
        fontSize=8,
        leading=10,
        wordWrap='CJK',
        alignment=0,  # Left alignment
    )
    
    header_style = ParagraphStyle(
        'HeaderStyle',
        parent=styles['Normal'],
        fontSize=9,
        leading=11,
        fontName='Helvetica-Bold',
        wordWrap='CJK',
        alignment=0,
    )

    def create_paragraph(text, is_header=False):
        """Create a Paragraph object for table cells to enable text wrapping"""
        if text is None or text == "":
            return Paragraph("", header_style if is_header else cell_style)
        return Paragraph(str(text), header_style if is_header else cell_style)

    elements = []

    title = Paragraph("Consumables Inventory Report", styles["Title"])
    
    # Build filter metadata string
    filter_info = []
    if q:
        filter_info.append(f"Search: '{q}'")
    if is_returnable_filter in ['true', 'false']:
        returnable_text = "Returnable" if is_returnable_filter == 'true' else "Non-Returnable"
        filter_info.append(returnable_text)
    if date_received_filter:
        filter_info.append(f"Month Received: {date_received_filter}")
    if date_from or date_to:
        date_range = f"Date Range: {date_from or 'any'} to {date_to or 'any'}"
        filter_info.append(date_range)
    if expiration_status:
        status_map = {'expired': 'Already Expired', 'expiring_soon': 'Expiring Soon (30d)', 'ok': 'Safe (30d+)'}
        filter_info.append(f"Expiration: {status_map.get(expiration_status, expiration_status)}")
    if stock_status:
        status_map = {'critical': 'Critical (<10%)', 'depleting': 'Depleting (10-25%)'}
        filter_info.append(f"Stock: {status_map.get(stock_status, stock_status)}")
    filter_text = " | ".join(filter_info) if filter_info else "No filters applied"
    
    meta_text = f"Generated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')} | {filter_text} | Sort: {sort} {direction.upper()}"
    meta = Paragraph(meta_text, styles["Normal"])

    elements.append(title)
    elements.append(Spacer(1, 6))
    elements.append(meta)
    elements.append(Spacer(1, 12))

    # Updated headers (removed Test and Total, added Returnable)
    headers = [
        "Description", "Balance Stock", "Unit", "Returnable",
        "Expiration", "Lot #", "Date Received", "Items Out",
        "Items In Stock", "Previous Month Stock", "Units Consumed", "Units Expired"
    ]

    def sval(x):
        return "" if x is None else str(x)

    def returnable_text(is_returnable):
        return "Yes" if is_returnable else "No"

    # Create header row with Paragraph objects
    header_row = [create_paragraph(header, is_header=True) for header in headers]
    data = [header_row]
    
    for it in items:
        data.append([
            create_paragraph(sval(it.description)),
            create_paragraph(sval(it.balance_stock)),
            create_paragraph(sval(it.unit)),
            create_paragraph(returnable_text(it.is_returnable)),
            create_paragraph(sval(it.expiration)),
            create_paragraph(sval(it.lot_number)),
            create_paragraph(sval(it.date_received)),
            create_paragraph(sval(it.items_out)),
            create_paragraph(sval(it.items_on_stock)),
            create_paragraph(sval(it.previous_month_stock)),
            create_paragraph(sval(it.units_consumed)),
            create_paragraph(sval(it.units_expired)),
        ])

    # Define column widths (in points) - adjust these based on your content needs
    col_widths = [120, 60, 40, 50, 60, 60, 70, 50, 60, 80, 70, 70]

    table = Table(data, repeatRows=1, colWidths=col_widths)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F3F4F6")),  # header bg (gray-100)
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#111827")),    # header text (gray-900)
        ("ALIGN", (0, 0), (-1, -1), "LEFT"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),  # Top alignment for better text wrapping
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 9),
        ("FONTSIZE", (0, 1), (-1, -1), 8),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#FAFAFA")]),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#D1D5DB")),  # gray-300 grid
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
    ]))

    elements.append(table)
    doc.build(elements)

    buffer.seek(0)
    filename = f"consumables_report_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.pdf"
    return send_file(
        buffer,
        mimetype="application/pdf",
        as_attachment=True,
        download_name=filename
    )

@app.route('/equipment/export/pdf')
def export_equipment_pdf():
    """
    Export the current equipment view (respecting q, sort, dir, location, brand, date range)
    to a landscape A4 PDF table with text wrapping.
    """
    if 'user_id' not in session:
        return redirect(url_for('login'))

    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import inch
    except ImportError:
        return ("Missing dependency: reportlab. Install it first, e.g. "
                "`pip install reportlab`"), 500

    q = request.args.get('q', '').strip()
    sort = request.args.get('sort', 'description')
    direction = request.args.get('dir', 'asc').lower()
    direction = 'desc' if direction == 'desc' else 'asc'
    
    # New filter parameters
    location_filter = request.args.get('location', '').strip()
    brand_filter = request.args.get('brand', '').strip()
    date_from = request.args.get('date_from', '').strip()
    date_to = request.args.get('date_to', '').strip()

    # Whitelist includes computed fields
    sortable_fields = {
        'description', 'qty', 'date_purchased', 'serial_number',
        'brand_name', 'model', 'remarks', 'location',
        'in_use', 'on_stock'
    }
    if sort not in sortable_fields:
        sort = 'description'

    # Updated subquery to use new BorrowLog structure
    active_borrows_sq = (db.session.query(
            BorrowLog.equipment_id.label('eq_id'),
            func.sum(BorrowLog.quantity_borrowed).label('in_use')  # Sum quantities for bulk borrowing
        )
        .filter(BorrowLog.returned_at.is_(None))
        .group_by(BorrowLog.equipment_id)
        .subquery())

    in_use_col = func.coalesce(active_borrows_sq.c.in_use, 0).label('in_use')
    on_stock_col = (func.coalesce(Equipment.qty, 0) - func.coalesce(active_borrows_sq.c.in_use, 0)).label('on_stock')

    query = (db.session.query(Equipment, in_use_col, on_stock_col)
             .outerjoin(active_borrows_sq, Equipment.id == active_borrows_sq.c.eq_id))

    if q:
        like = f"%{q}%"
        query = query.filter(or_(
            Equipment.description.ilike(like),
            Equipment.serial_number.ilike(like),
            Equipment.brand_name.ilike(like),
            Equipment.model.ilike(like),
            Equipment.remarks.ilike(like),
            Equipment.location.ilike(like),
            Equipment.date_purchased.ilike(like),
        ))

    # Apply new filters
    if location_filter:
        query = query.filter(Equipment.location.ilike(f"%{location_filter}%"))
    if brand_filter:
        query = query.filter(Equipment.brand_name.ilike(f"%{brand_filter}%"))
    if date_from:
        query = query.filter(Equipment.date_purchased >= date_from)
    if date_to:
        query = query.filter(Equipment.date_purchased <= date_to)

    if sort == 'in_use':
        sort_col = in_use_col
    elif sort == 'on_stock':
        sort_col = on_stock_col
    else:
        sort_col = getattr(Equipment, sort)

    query = query.order_by(sort_col.desc() if direction == 'desc' else sort_col.asc())
    rows = query.all()

    # Build PDF
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        leftMargin=18, rightMargin=18, topMargin=24, bottomMargin=18,
    )
    
    styles = getSampleStyleSheet()
    
    # Create custom style for table cells
    cell_style = ParagraphStyle(
        'CellStyle',
        parent=styles['Normal'],
        fontSize=8,
        leading=10,
        wordWrap='CJK',
        alignment=0,  # Left alignment
    )
    
    header_style = ParagraphStyle(
        'HeaderStyle',
        parent=styles['Normal'],
        fontSize=9,
        leading=11,
        fontName='Helvetica-Bold',
        wordWrap='CJK',
        alignment=0,
    )

    def create_paragraph(text, is_header=False):
        """Create a Paragraph object for table cells to enable text wrapping"""
        if text is None or text == "":
            return Paragraph("", header_style if is_header else cell_style)
        return Paragraph(str(text), header_style if is_header else cell_style)

    elements = []
    elements.append(Paragraph("Equipment Inventory Report", styles["Title"]))
    elements.append(Spacer(1, 6))
    
    # Build filter metadata string
    filter_info = []
    if q:
        filter_info.append(f"Search: '{q}'")
    if location_filter:
        filter_info.append(f"Location: {location_filter}")
    if brand_filter:
        filter_info.append(f"Brand: {brand_filter}")
    if date_from or date_to:
        date_range = f"Date: {date_from or 'any'} to {date_to or 'any'}"
        filter_info.append(date_range)
    filter_text = " | ".join(filter_info) if filter_info else "No filters applied"
    
    meta_text = f"Generated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')} | {filter_text} | Sort: {sort} {direction.upper()}"
    elements.append(Paragraph(meta_text, styles["Normal"]))
    elements.append(Spacer(1, 12))

    # Prepare data
    headers = [
        "Description", "Quantity", "In Use", "On Stock", "Date Purchased",
        "Serial #", "Brand", "Model", "Remarks", "Location"
    ]

    def sval(x):
        return "" if x is None else str(x)

    # Create header row with Paragraph objects
    header_row = [create_paragraph(header, is_header=True) for header in headers]
    data = [header_row]
    
    for e, in_use, on_stock in rows:
        data.append([
            create_paragraph(sval(e.description)),
            create_paragraph(sval(e.qty)),
            create_paragraph(sval(int(in_use or 0))),
            create_paragraph(sval(int(on_stock or 0))),
            create_paragraph(sval(e.date_purchased)),
            create_paragraph(sval(e.serial_number)),
            create_paragraph(sval(e.brand_name)),
            create_paragraph(sval(e.model)),
            create_paragraph(sval(e.remarks)),
            create_paragraph(sval(e.location)),
        ])

    # Define column widths (in points) - adjust these based on your content needs
    col_widths = [140, 50, 40, 50, 80, 80, 80, 80, 120, 80]

    table = Table(data, repeatRows=1, colWidths=col_widths)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F3F4F6")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#111827")),
        ("ALIGN", (0, 0), (-1, -1), "LEFT"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),  # Top alignment for better text wrapping
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 9),
        ("FONTSIZE", (0, 1), (-1, -1), 8),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#FAFAFA")]),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#D1D5DB")),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
    ]))
    elements.append(table)
    doc.build(elements)

    buffer.seek(0)
    filename = f"equipment_report_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.pdf"
    return send_file(
        buffer,
        mimetype="application/pdf",
        as_attachment=True,
        download_name=filename
    )

@app.route('/borrow_equipment', methods=['GET', 'POST'])
def borrow_equipment():
    if session.get('role') not in ['tech', 'admin']:
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        # Support bulk borrowing
        quantity = int(request.form.get('quantity_borrowed', 1))
        
        log = BorrowLog(
            borrower_name=request.form['borrower_name'],
            borrower_type=request.form['borrower_type'],
            section_course=request.form['section_course'],
            purpose=request.form['purpose'],
            equipment_id=request.form['equipment_id'],
            quantity_borrowed=quantity
        )
        db.session.add(log)
        db.session.commit()
        return redirect(url_for('equipment'))
    equipment_list = Equipment.query.all()
    return render_template('borrow_equipment.html', equipment=equipment_list)

@app.route('/use_consumable', methods=['GET', 'POST'])
def use_consumable():
    if session.get('role') not in ['tech', 'admin']:
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        quantity_used = _clamp_nonneg(request.form['quantity'])
        consumable_id = _to_int(request.form['consumable_id'], 0)

        if quantity_used <= 0:
            return redirect(url_for('consumables'))

        c = Consumable.query.get_or_404(consumable_id)

        # Log usage
        log = UsageLog(
            user_name=request.form['user_name'],
            user_type=request.form['user_type'],
            section_course=request.form['section_course'],
            purpose=request.form['purpose'],
            consumable_id=consumable_id,
            quantity_used=quantity_used
        )
        db.session.add(log)

        # Increment units_consumed for this specific row
        c.units_consumed = _to_int(c.units_consumed, 0) + quantity_used
        
        # Reduce items_out (lab stock) by ID
        remaining = consume_by_id(consumable_id, quantity_used)
        
        # Recalculate this specific row
        recalc_single_row(c)

        db.session.commit()
        return redirect(url_for('consumables'))

    consumables_list = Consumable.query.all()
    return render_template('use_consumable.html', consumables=consumables_list)


# Row-level Borrow Equipment
@app.route('/equipment/borrow/<int:id>', methods=['GET', 'POST'])
def borrow_equipment_row(id):
    if session.get('role') not in ['tech', 'admin']:
        return redirect(url_for('dashboard'))
    
    equipment = Equipment.query.get_or_404(id)
    
    if request.method == 'POST':
        log = BorrowLog(
            borrower_name=request.form['borrower_name'],
            borrower_type=request.form['borrower_type'],
            section_course=request.form['section_course'],
            purpose=request.form['purpose'],
            equipment_id=equipment.id,
            quantity_borrowed=int(request.form.get('quantity_borrowed', 1))
        )
        db.session.add(log)
        db.session.commit()
        return redirect(url_for('equipment'))
    
    return render_template('borrow_equipment_row.html', equipment=equipment)

def consume_by_id(consumable_id: int, quantity: int):
    """
    Reduce items_out (lab stock) for a specific consumable by its ID.
    Returns the remaining quantity that could not be fulfilled (0 if fully applied).
    """
    remaining = _clamp_nonneg(quantity)
    if remaining == 0:
        return 0

    c = Consumable.query.get(consumable_id)
    if not c:
        return remaining
    
    out = _clamp_nonneg(c.items_out)
    if out <= 0:
        return remaining
    
    take = min(out, remaining)
    c.items_out = out - take
    remaining -= take
    
    return remaining

@app.route('/consumables/use/<int:id>', methods=['GET', 'POST'])
def use_consumable_row(id):
    if session.get('role') not in ['tech', 'admin']:
        return redirect(url_for('dashboard'))
    
    c = Consumable.query.get_or_404(id)
    
    if request.method == 'POST':
        quantity_used = _clamp_nonneg(request.form['quantity'])

        if quantity_used > 0:
            # Log usage
            log = UsageLog(
                user_name=request.form['user_name'],
                user_type=request.form['user_type'],
                section_course=request.form['section_course'],
                purpose=request.form['purpose'],
                consumable_id=c.id,
                quantity_used=quantity_used
            )
            db.session.add(log)

            # Add units consumed on this row
            c.units_consumed = _to_int(c.units_consumed, 0) + quantity_used

            # Reduce items_out (lab stock) by ID
            consume_by_id(c.id, quantity_used)

            # Recalc this specific row
            recalc_single_row(c)

            db.session.commit()
        return redirect(url_for('consumables'))
    
    return render_template('use_consumable_row.html', consumable=c)

@app.route('/consumables/return/<int:usage_id>', methods=['GET', 'POST'])
def return_consumable(usage_id):
    if session.get('role') not in ['admin', 'tech']:
        return redirect(url_for('dashboard'))
    
    log = UsageLog.query.get_or_404(usage_id)
    
    # Check if consumable is returnable
    if not log.consumable or not log.consumable.is_returnable:
        return redirect(url_for('history'))
    
    if request.method == 'POST':
        # Get quantity to return
        quantity_returned = _clamp_nonneg(request.form.get('quantity_returned', 0))
        
        # Mark as returned
        if log.returned_at is None:
            log.returned_at = db.func.current_timestamp()
            
            # Add the returned quantity back to stock
            if quantity_returned > 0:
                log.consumable.items_out = _to_int(log.consumable.items_out, 0) + quantity_returned
                
                # Store the returned quantity for tracking
                log.quantity_returned = quantity_returned
            
            # Optional: create a student note for issues
            note_type = (request.form.get('note_type') or '').strip().lower()
            note_description = (request.form.get('description') or '').strip()

            if note_type and note_type != 'none' and note_description:
                note = StudentNote(
                    person_name=log.user_name,
                    person_number=log.user_type,
                    person_type=log.user_type,
                    section_course=log.section_course,
                    note_type=note_type,
                    description=note_description,
                    consumable_id=log.consumable_id,
                    equipment_id=None,
                    created_by=session['user_id']
                )
                db.session.add(note)
            
            # Recalculate this single row
            recalc_single_row(log.consumable)
        
        db.session.commit()
        return redirect(url_for('history'))
    
    return render_template('return_consumable.html', log=log)

# Return Equipment (mark BorrowLog returned and optionally create a StudentNote)
# Update return_equipment function
@app.route('/equipment/return/<int:borrow_id>', methods=['GET', 'POST'])
def return_equipment(borrow_id):
    if session.get('role') not in ['admin', 'tech']:
        return redirect(url_for('dashboard'))
    
    log = BorrowLog.query.get_or_404(borrow_id)

    if request.method == 'POST':
        # Mark as returned (if not already)
        if log.returned_at is None:
            log.returned_at = db.func.current_timestamp()

        # Optional: create a student note for issues (damaged, lost, other)
        note_type = (request.form.get('note_type') or '').strip().lower()
        note_description = (request.form.get('description') or '').strip()

        if note_type and note_type != 'none' and note_description:
            note = StudentNote(
                person_name=log.borrower_name,
                person_number='',  # No person number in new structure
                person_type=log.borrower_type,
                section_course=log.section_course,
                note_type=note_type,  # 'damaged', 'lost', 'other'
                description=note_description,
                equipment_id=log.equipment_id,
                consumable_id=None,
                created_by=session['user_id']
            )
            db.session.add(note)

        db.session.commit()
        return redirect(url_for('history'))

    return render_template('return_equipment.html', log=log)

@app.route('/bulk_operations')
def bulk_operations():
    if session.get('role') not in ['tech', 'admin']:
        return redirect(url_for('dashboard'))
    
    equipment_list = Equipment.query.all()
    consumables_list = Consumable.query.all()
    return render_template('bulk_operations.html', 
                         equipment=equipment_list, 
                         consumables=consumables_list)

@app.route('/bulk_borrow_equipment', methods=['POST'])
def bulk_borrow_equipment():
    if session.get('role') not in ['tech', 'admin']:
        return redirect(url_for('dashboard'))
    
    borrower_name = request.form['borrower_name']
    borrower_type = request.form['borrower_type']
    section_course = request.form['section_course']
    purpose = request.form['purpose']
    
    equipment_ids = request.form.getlist('equipment_ids[]')
    quantities = request.form.getlist('quantities[]')
    
    # Create borrow logs for each equipment
    for i, equipment_id in enumerate(equipment_ids):
        if equipment_id:  # Skip empty selections
            quantity = _clamp_nonneg(quantities[i] if i < len(quantities) else 1)
            if quantity > 0:
                log = BorrowLog(
                    borrower_name=borrower_name,
                    borrower_type=borrower_type,
                    section_course=section_course,
                    purpose=purpose,
                    equipment_id=equipment_id,
                    quantity_borrowed=quantity
                )
                db.session.add(log)
    
    db.session.commit()
    return redirect(url_for('equipment'))

@app.route('/bulk_use_consumables', methods=['POST'])
def bulk_use_consumables():
    if session.get('role') not in ['tech', 'admin']:
        return redirect(url_for('dashboard'))
    
    user_name = request.form['user_name']
    user_type = request.form['user_type']
    section_course = request.form['section_course']
    purpose = request.form['purpose']
    
    consumable_ids = request.form.getlist('consumable_ids[]')
    quantities = request.form.getlist('quantities[]')
    
    # Process each consumable usage
    for i, consumable_id in enumerate(consumable_ids):
        if consumable_id:  # Skip empty selections
            quantity_used = _clamp_nonneg(quantities[i] if i < len(quantities) else 1)
            if quantity_used > 0:
                c = Consumable.query.get(consumable_id)
                if c:
                    # Log usage
                    log = UsageLog(
                        user_name=user_name,
                        user_type=user_type,
                        section_course=section_course,
                        purpose=purpose,
                        consumable_id=consumable_id,
                        quantity_used=quantity_used
                    )
                    db.session.add(log)

                    # Increment units_consumed
                    c.units_consumed = _to_int(c.units_consumed, 0) + quantity_used
                    
                    # Consume by ID
                    consume_by_id(int(consumable_id), quantity_used)
                    
                    # Recalc this specific row
                    recalc_single_row(c)
    
    db.session.commit()
    return redirect(url_for('consumables'))

# Update history function
@app.route('/history')
def history():
    if session.get('role') not in ['admin', 'tech']:
        return redirect(url_for('dashboard'))

    # Borrowing table params
    b_q = request.args.get('b_q', '').strip()
    b_sort = request.args.get('b_sort', 'borrowed_at')
    b_dir = request.args.get('b_dir', 'desc').lower()
    b_dir = 'desc' if b_dir == 'desc' else 'asc'

    # Usage table params
    u_q = request.args.get('u_q', '').strip()
    u_sort = request.args.get('u_sort', 'used_at')
    u_dir = request.args.get('u_dir', 'desc').lower()
    u_dir = 'desc' if u_dir == 'desc' else 'asc'

    # BORROWS - Updated field names
    borrows_sortable = {'borrower_name', 'borrower_type', 'section_course', 'purpose', 'equipment', 'quantity_borrowed', 'borrowed_at', 'returned_at'}
    if b_sort not in borrows_sortable:
        b_sort = 'borrowed_at'

    b_query = BorrowLog.query.outerjoin(Equipment)

    # Update field references for borrows
    if b_q:
        like = f"%{b_q}%"
        b_query = b_query.filter(or_(
            BorrowLog.borrower_name.ilike(like),
            BorrowLog.borrower_type.ilike(like),
            BorrowLog.section_course.ilike(like),
            BorrowLog.purpose.ilike(like),
            Equipment.description.ilike(like),
        ))

    if b_sort == 'equipment':
        b_sort_col = Equipment.description
    else:
        b_sort_col = getattr(BorrowLog, b_sort)

    b_query = b_query.order_by(b_sort_col.desc() if b_dir == 'desc' else b_sort_col.asc())
    borrows = b_query.all()

    # USAGES - Updated field names
    usages_sortable = {'user_name', 'user_type', 'section_course', 'purpose', 'consumable', 'quantity_used', 'used_at'}
    if u_sort not in usages_sortable:
        u_sort = 'used_at'

    u_query = UsageLog.query.outerjoin(Consumable)

    # Update field references for usages
    if u_q:
        like = f"%{u_q}%"
        u_query = u_query.filter(or_(
            UsageLog.user_name.ilike(like),
            UsageLog.user_type.ilike(like),
            UsageLog.section_course.ilike(like),
            UsageLog.purpose.ilike(like),
            Consumable.description.ilike(like),
        ))

    if u_sort == 'consumable':
        u_sort_col = Consumable.description
    else:
        u_sort_col = getattr(UsageLog, u_sort)

    u_query = u_query.order_by(u_sort_col.desc() if u_dir == 'desc' else u_sort_col.asc())
    usages = u_query.all()

    return render_template(
        'history.html',
        borrows=borrows,
        usages=usages,
        # borrow table state
        b_q=b_q, b_sort=b_sort, b_dir=b_dir,
        # usage table state
        u_q=u_q, u_sort=u_sort, u_dir=u_dir,
    )

@app.route('/history/export/pdf')
def export_history_pdf():
    """
    Export the current history view for both sections (borrowing and usage)
    into a single PDF with text wrapping, respecting all filters and sorts.
    """
    if session.get('role') not in ['admin', 'tech']:
        return redirect(url_for('dashboard'))

    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import inch
    except ImportError:
        return ("Missing dependency: reportlab. Install it first, e.g. "
                "`pip install reportlab`"), 500

    # Borrowing params
    b_q = request.args.get('b_q', '').strip()
    b_sort = request.args.get('b_sort', 'borrowed_at')
    b_dir = request.args.get('b_dir', 'desc').lower()
    b_dir = 'desc' if b_dir == 'desc' else 'asc'

    # Usage params
    u_q = request.args.get('u_q', '').strip()
    u_sort = request.args.get('u_sort', 'used_at')
    u_dir = request.args.get('u_dir', 'desc').lower()
    u_dir = 'desc' if u_dir == 'desc' else 'asc'

    # Build borrows query (updated field names)
    borrows_sortable = {
        'borrower_name', 'borrower_type', 'section_course', 'purpose', 
        'equipment', 'quantity_borrowed', 'borrowed_at', 'returned_at'
    }
    if b_sort not in borrows_sortable:
        b_sort = 'borrowed_at'

    b_query = BorrowLog.query.outerjoin(Equipment)

    if b_q:
        like = f"%{b_q}%"
        b_query = b_query.filter(or_(
            BorrowLog.borrower_name.ilike(like),
            BorrowLog.borrower_type.ilike(like),
            BorrowLog.section_course.ilike(like),
            BorrowLog.purpose.ilike(like),
            Equipment.description.ilike(like),
        ))

    if b_sort == 'equipment':
        b_sort_col = Equipment.description
    else:
        b_sort_col = getattr(BorrowLog, b_sort)

    b_query = b_query.order_by(b_sort_col.desc() if b_dir == 'desc' else b_sort_col.asc())
    borrows = b_query.all()

    # Build usages query (updated field names)
    usages_sortable = {
        'user_name', 'user_type', 'section_course', 'purpose', 
        'consumable', 'quantity_used', 'used_at'
    }
    if u_sort not in usages_sortable:
        u_sort = 'used_at'

    u_query = UsageLog.query.outerjoin(Consumable)

    if u_q:
        like = f"%{u_q}%"
        u_query = u_query.filter(or_(
            UsageLog.user_name.ilike(like),
            UsageLog.user_type.ilike(like),
            UsageLog.section_course.ilike(like),
            UsageLog.purpose.ilike(like),
            Consumable.description.ilike(like),
        ))

    if u_sort == 'consumable':
        u_sort_col = Consumable.description
    else:
        u_sort_col = getattr(UsageLog, u_sort)

    u_query = u_query.order_by(u_sort_col.desc() if u_dir == 'desc' else u_sort_col.asc())
    usages = u_query.all()

    # Build PDF
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        leftMargin=18, rightMargin=18, topMargin=24, bottomMargin=18,
    )
    
    styles = getSampleStyleSheet()
    
    # Create custom style for table cells
    cell_style = ParagraphStyle(
        'CellStyle',
        parent=styles['Normal'],
        fontSize=8,
        leading=10,
        wordWrap='CJK',
        alignment=0,  # Left alignment
    )
    
    header_style = ParagraphStyle(
        'HeaderStyle',
        parent=styles['Normal'],
        fontSize=9,
        leading=11,
        fontName='Helvetica-Bold',
        wordWrap='CJK',
        alignment=0,
    )

    def create_paragraph(text, is_header=False):
        """Create a Paragraph object for table cells to enable text wrapping"""
        if text is None or text == "":
            return Paragraph("", header_style if is_header else cell_style)
        return Paragraph(str(text), header_style if is_header else cell_style)

    elements = []

    # Title/meta
    elements.append(Paragraph("Usage & Borrowing History Report", styles["Title"]))
    elements.append(Spacer(1, 6))
    elements.append(Paragraph(
        f"Generated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}",
        styles["Normal"],
    ))
    elements.append(Spacer(1, 12))

    # Borrowing section
    elements.append(Paragraph("Equipment Borrowing", styles["Heading2"]))
    elements.append(Spacer(1, 6))
    
    # Updated headers for borrowing
    borrow_headers = [
        "Borrower", "Type", "Section + Course", "Purpose", 
        "Equipment", "Quantity", "Borrowed At", "Returned At"
    ]

    def sval(x):
        return "" if x is None else str(x)

    # Create header row with Paragraph objects
    borrow_header_row = [create_paragraph(header, is_header=True) for header in borrow_headers]
    borrow_data = [borrow_header_row]
    
    for log in borrows:
        borrow_data.append([
            create_paragraph(sval(log.borrower_name)),
            create_paragraph(sval(log.borrower_type.title() if log.borrower_type else "")),
            create_paragraph(sval(log.section_course)),
            create_paragraph(sval(log.purpose)),
            create_paragraph(sval(log.equipment.description if log.equipment else "—")),
            create_paragraph(sval(log.quantity_borrowed)),
            create_paragraph(sval(log.borrowed_at)),
            create_paragraph(sval(log.returned_at if log.returned_at else "—")),
        ])

    # Define column widths for borrowing table
    borrow_col_widths = [120, 60, 100, 140, 120, 50, 100, 100]

    borrow_table = Table(borrow_data, repeatRows=1, colWidths=borrow_col_widths)
    borrow_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F3F4F6")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#111827")),
        ("ALIGN", (0, 0), (-1, -1), "LEFT"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),  # Top alignment for better text wrapping
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 9),
        ("FONTSIZE", (0, 1), (-1, -1), 8),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#FAFAFA")]),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#D1D5DB")),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
    ]))
    elements.append(borrow_table)

    # Page break between sections for clarity
    elements.append(PageBreak())

    # Usage section
    elements.append(Paragraph("Consumables Usage", styles["Heading2"]))
    elements.append(Spacer(1, 6))
    
    # Updated headers for usage
    usage_headers = [
        "User", "Type", "Section + Course", "Purpose",
        "Consumable", "Returnable", "Quantity Used", "Used At"
    ]
    
    # Create header row with Paragraph objects
    usage_header_row = [create_paragraph(header, is_header=True) for header in usage_headers]
    usage_data = [usage_header_row]
    
    for log in usages:
        # Check if consumable is returnable
        returnable_text = "Yes" if (log.consumable and log.consumable.is_returnable) else "No"
        
        usage_data.append([
            create_paragraph(sval(log.user_name)),
            create_paragraph(sval(log.user_type.title() if log.user_type else "")),
            create_paragraph(sval(log.section_course)),
            create_paragraph(sval(log.purpose)),
            create_paragraph(sval(log.consumable.description if log.consumable else "—")),
            create_paragraph(returnable_text),
            create_paragraph(sval(log.quantity_used)),
            create_paragraph(sval(log.used_at)),
        ])

    # Define column widths for usage table
    usage_col_widths = [120, 60, 100, 140, 120, 60, 70, 100]

    usage_table = Table(usage_data, repeatRows=1, colWidths=usage_col_widths)
    usage_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F3F4F6")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#111827")),
        ("ALIGN", (0, 0), (-1, -1), "LEFT"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),  # Top alignment for better text wrapping
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 9),
        ("FONTSIZE", (0, 1), (-1, -1), 8),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#FAFAFA")]),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#D1D5DB")),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
    ]))
    elements.append(usage_table)

    doc.build(elements)

    buffer.seek(0)
    filename = f"history_report_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.pdf"
    return send_file(
        buffer,
        mimetype="application/pdf",
        as_attachment=True,
        download_name=filename
    )

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/admin/create_user', methods=['GET', 'POST'])
def create_user():
    if session.get('role') != 'admin':
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        username = request.form['username']
        password = generate_password_hash(request.form['password'])
        role = request.form['role']

        if User.query.filter_by(username=username).first():
            return render_template('create_user.html', error="Username already exists")

        new_user = User(username=username, password=password, role=role)
        db.session.add(new_user)
        db.session.commit()
        return redirect(url_for('user_management'))

    return render_template('create_user.html')

@app.route('/admin/users')
def user_management():
    if session.get('role') != 'admin':
        return redirect(url_for('dashboard'))

    users = User.query.all()
    return render_template('user_management.html', users=users)

# Add Equipment
@app.route('/equipment/add', methods=['GET', 'POST'])
def add_equipment():
    if session.get('role') not in ['admin', 'tech']:
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        equipment = Equipment(
            description=request.form['description'],
            qty=int(request.form['qty']) if request.form['qty'] else 0,
            date_purchased=request.form['date_purchased'],
            serial_number=request.form['serial_number'],
            brand_name=request.form['brand_name'],
            model=request.form['model'],
            remarks=request.form['remarks'],
            location=request.form['location']
        )
        db.session.add(equipment)
        db.session.commit()
        return redirect(url_for('equipment'))
    
    return render_template('add_equipment.html')

# Edit Equipment
@app.route('/equipment/edit/<int:id>', methods=['GET', 'POST'])
def edit_equipment(id):
    if session.get('role') not in ['admin', 'tech']:
        return redirect(url_for('dashboard'))
    
    equipment = Equipment.query.get_or_404(id)
    
    if request.method == 'POST':
        equipment.description = request.form['description']
        equipment.qty = int(request.form['qty']) if request.form['qty'] else 0
        equipment.date_purchased = request.form['date_purchased']
        equipment.serial_number = request.form['serial_number']
        equipment.brand_name = request.form['brand_name']
        equipment.model = request.form['model']
        equipment.remarks = request.form['remarks']
        equipment.location = request.form['location']
        db.session.commit()
        return redirect(url_for('equipment'))
    
    return render_template('edit_equipment.html', equipment=equipment)

# Add Consumable
# Update add_consumable function
@app.route('/consumables/add', methods=['GET', 'POST'])
def add_consumable():
    if session.get('role') not in ['admin', 'tech']:
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        # Convert returnable type to boolean
        is_returnable = request.form.get('is_returnable') == 'true'
        
        consumable = Consumable(
            balance_stock=_to_int(request.form['balance_stock']),
            unit=request.form['unit'],
            description=request.form['description'],
            is_returnable=is_returnable,
            expiration=request.form['expiration'],
            lot_number=request.form['lot_number'],
            date_received=request.form['date_received'],
            items_out=_to_int(request.form['items_out']),
            items_on_stock=_to_int(request.form['items_on_stock']),
            previous_month_stock=_to_int(request.form['previous_month_stock']),
            units_consumed=_to_int(request.form['units_consumed']),
            units_expired=_to_int(request.form.get('units_expired'), None) if request.form.get('units_expired') else None
        )
        normalize_row_nonnegatives(consumable)
        db.session.add(consumable)
        db.session.flush()

        # Recalculate this single row
        recalc_single_row(consumable)

        db.session.commit()
        return redirect(url_for('consumables'))
    
    return render_template('add_consumable.html')

# Edit Consumable
# Update edit_consumable function
@app.route('/consumables/edit/<int:id>', methods=['GET', 'POST'])
def edit_consumable(id):
    if session.get('role') not in ['admin', 'tech']:
        return redirect(url_for('dashboard'))
    
    consumable = Consumable.query.get_or_404(id)
    
    if request.method == 'POST':
        # Convert returnable type to boolean
        is_returnable = request.form.get('is_returnable') == 'true'

        consumable.balance_stock = _to_int(request.form['balance_stock'])
        consumable.unit = request.form['unit']
        consumable.description = request.form['description']
        consumable.is_returnable = is_returnable
        consumable.expiration = request.form['expiration']
        consumable.lot_number = request.form['lot_number']
        consumable.date_received = request.form['date_received']
        consumable.items_out = _to_int(request.form['items_out'])
        consumable.items_on_stock = _to_int(request.form['items_on_stock'])
        consumable.previous_month_stock = _to_int(request.form['previous_month_stock'])
        consumable.units_consumed = _to_int(request.form['units_consumed'])
        consumable.units_expired = _to_int(request.form.get('units_expired'), None) if request.form.get('units_expired') else None

        normalize_row_nonnegatives(consumable)
        
        # Recalc this single row
        recalc_single_row(consumable)

        db.session.commit()
        return redirect(url_for('consumables'))
    
    return render_template('edit_consumable.html', consumable=consumable)

# Delete Consumable
@app.route('/consumables/delete/<int:id>', methods=['POST'])
def delete_consumable(id):
    if session.get('role') not in ['admin', 'tech']:
        return redirect(url_for('dashboard'))
    
    consumable = Consumable.query.get_or_404(id)

    # Clean up dependent rows to avoid FK issues
    UsageLog.query.filter_by(consumable_id=consumable.id).delete(synchronize_session=False)
    StudentNote.query.filter_by(consumable_id=consumable.id).delete(synchronize_session=False)

    db.session.delete(consumable)
    db.session.commit()

    return redirect(url_for('consumables'))

@app.route('/equipment/delete/<int:id>', methods=['POST'])
def delete_equipment(id):
    if session.get('role') not in ['admin', 'tech']:
        return redirect(url_for('dashboard'))

    equipment = Equipment.query.get_or_404(id)

    # Optional: clean up dependent rows to avoid FK issues (if foreign keys are enforced)
    BorrowLog.query.filter_by(equipment_id=equipment.id).delete(synchronize_session=False)
    StudentNote.query.filter_by(equipment_id=equipment.id).delete(synchronize_session=False)

    db.session.delete(equipment)
    db.session.commit()
    return redirect(url_for('equipment'))

# Delete User (Admin only)
@app.route('/admin/users/delete/<int:id>', methods=['POST'])
def delete_user(id):
    if session.get('role') != 'admin':
        return redirect(url_for('dashboard'))
    
    user = User.query.get_or_404(id)
    
    # Prevent admin from deleting themselves
    if user.id == session.get('user_id'):
        return "Error: You cannot delete your own account", 400
    
    db.session.delete(user)
    db.session.commit()
    return redirect(url_for('user_management'))

# Add Student Note
# Update add_student_note function
@app.route('/notes/add', methods=['GET', 'POST'])
def add_student_note():
    if session.get('role') not in ['admin', 'tech']:
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        note = StudentNote(
            person_name=request.form['person_name'],
            person_number=request.form['person_number'],
            person_type=request.form['person_type'],
            section_course=request.form['section_course'],
            note_type=request.form['note_type'],
            description=request.form['description'],
            equipment_id=request.form.get('equipment_id') or None,
            consumable_id=request.form.get('consumable_id') or None,
            created_by=session['user_id'],
            status='pending'  # ADD: explicitly set default status
        )
        db.session.add(note)
        db.session.commit()
        return redirect(url_for('student_notes'))
    
    equipment_list = Equipment.query.all()
    consumables_list = Consumable.query.all()
    return render_template('add_student_note.html', 
                         equipment=equipment_list, 
                         consumables=consumables_list)

# Update student_notes function
@app.route('/notes')
def student_notes():
    if session.get('role') not in ['admin', 'tech']:
        return redirect(url_for('dashboard'))

    q = request.args.get('q', '').strip()
    sort = request.args.get('sort', 'created_at')
    direction = request.args.get('dir', 'desc').lower()
    direction = 'desc' if direction == 'desc' else 'asc'
    
    # Filter by status
    status_filter = request.args.get('status', 'all')

    # Updated sortable fields - ADD status
    sortable_fields = {
        'person_name', 'person_type', 'section_course',
        'note_type', 'description', 'related_item', 'reported_by', 'created_at', 'status'
    }
    if sort not in sortable_fields:
        sort = 'created_at'

    # DEBUG: Check basic counts
    total_notes = StudentNote.query.count()
    total_users = User.query.count()
    print(f"Total notes: {total_notes}")
    print(f"Total users: {total_users}")
    
    # DEBUG: Check if users referenced by notes exist
    all_notes = StudentNote.query.all()
    for note in all_notes:
        user = User.query.get(note.created_by)
        print(f"Note {note.id}: created_by={note.created_by}, user exists: {user is not None}")
        if user:
            print(f"  User: {user.username}")

    # Build query with joins for related item and reporter
    # CHANGE: Use outerjoin instead of join for User to avoid filtering out notes
    query = (StudentNote.query
             .outerjoin(Equipment, StudentNote.equipment_id == Equipment.id)
             .outerjoin(Consumable, StudentNote.consumable_id == Consumable.id)
             .outerjoin(User, StudentNote.created_by == User.id))
    
    # DEBUG: Check count after joins
    notes_after_joins = query.count()
    print(f"Notes after joins: {notes_after_joins}")

    # COALESCE to pick the related item's description (equipment first, else consumable)
    related_item_col = func.coalesce(Equipment.description, Consumable.description)
    reported_by_col = User.username

    # ADD status filter
    if status_filter != 'all':
        query = query.filter(StudentNote.status == status_filter)
        print(f"Filtering by status: {status_filter}")

    if q:
        like = f"%{q}%"
        query = query.filter(or_(
            StudentNote.person_name.ilike(like),
            StudentNote.person_type.ilike(like),
            StudentNote.section_course.ilike(like),
            StudentNote.note_type.ilike(like),
            StudentNote.description.ilike(like),
            StudentNote.status.ilike(like),  # ADD status to search
            related_item_col.ilike(like),
            reported_by_col.ilike(like),
        ))

    if sort == 'related_item':
        sort_col = related_item_col
    elif sort == 'reported_by':
        sort_col = reported_by_col
    else:
        sort_col = getattr(StudentNote, sort)

    query = query.order_by(sort_col.desc() if direction == 'desc' else sort_col.asc())
    notes = query.all()
    print("Final notes count:")
    print(len(notes))

    return render_template('student_notes.html', notes=notes, q=q, sort=sort, dir=direction, status_filter=status_filter)

@app.route('/notes/toggle_status/<int:id>', methods=['POST'])
def toggle_note_status(id):
    if session.get('role') not in ['admin', 'tech']:
        return redirect(url_for('dashboard'))
    
    note = StudentNote.query.get_or_404(id)
    
    if note.status == 'pending':
        note.status = 'resolved'
        note.resolved_at = db.func.current_timestamp()
        note.resolved_by = session['user_id']
    else:
        note.status = 'pending'
        note.resolved_at = None
        note.resolved_by = None
    
    db.session.commit()
    return redirect(url_for('student_notes'))

# Delete Student Note (Admin/Tech only)
@app.route('/notes/delete/<int:id>', methods=['POST'])
def delete_student_note(id):
    if session.get('role') not in ['admin', 'tech']:
        return redirect(url_for('dashboard'))
    
    note = StudentNote.query.get_or_404(id)
    db.session.delete(note)
    db.session.commit()
    return redirect(url_for('student_notes'))


@app.route('/analytics')
def analytics():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    from datetime import datetime, timedelta
    current_date = datetime.now().date()
    near_expiry_date = current_date + timedelta(days=30)
    thirty_days_ago = current_date - timedelta(days=30)
    
    # === ALERTS & INVENTORY ===
    # Low stock items (10% threshold: items_out + items_on_stock < 10% of previous_month_stock)
    low_stock_consumables = (db.session.query(Consumable)
                           .filter(Consumable.previous_month_stock > 0)
                           .filter((Consumable.items_out + Consumable.items_on_stock) < (Consumable.previous_month_stock * 0.1))
                           .all())
    
    # Near expiration consumables (within 30 days or already expired)
    near_expiration = []
    for c in Consumable.query.all():
        if c.expiration and c.expiration != 'N/A':
            try:
                exp_date = datetime.strptime(c.expiration, '%Y-%m-%d').date()
                if exp_date <= near_expiry_date:
                    near_expiration.append(c)
            except ValueError:
                continue
    
    # === USAGE TRENDS ===
    # Equipment borrowing trends (last 30 days including today)
    recent_borrows = (db.session.query(BorrowLog)
                     .filter(BorrowLog.borrowed_at >= datetime.combine(thirty_days_ago, datetime.min.time()))
                     .all())
    borrow_count_30d = len(recent_borrows)
    active_borrows = db.session.query(BorrowLog).filter(BorrowLog.returned_at.is_(None)).count()
    
    # Daily borrowing breakdown (count of students who borrowed per day)
    daily_borrows = {}
    for i in range(31):  # 31 days to include today
        day = thirty_days_ago + timedelta(days=i)
        day_str = day.strftime('%Y-%m-%d')
        daily_borrows[day_str] = 0
    
    for borrow in recent_borrows:
        if borrow.borrowed_at:
            borrow_date = borrow.borrowed_at.date().strftime('%Y-%m-%d')
            if borrow_date in daily_borrows:
                daily_borrows[borrow_date] += 1
    
    # Consumable usage trends (last 30 days including today)
    recent_usage = (db.session.query(UsageLog)
                   .filter(UsageLog.used_at >= datetime.combine(thirty_days_ago, datetime.min.time()))
                   .all())
    usage_count_30d = len(recent_usage)
    total_units_consumed_30d = sum(u.quantity_used for u in recent_usage)
    
    # Daily usage breakdown (count of students who used consumables per day)
    daily_usage = {}
    for i in range(31):  # 31 days to include today
        day = thirty_days_ago + timedelta(days=i)
        day_str = day.strftime('%Y-%m-%d')
        daily_usage[day_str] = 0
    
    for usage in recent_usage:
        if usage.used_at:
            usage_date = usage.used_at.date().strftime('%Y-%m-%d')
            if usage_date in daily_usage:
                daily_usage[usage_date] += 1
    
    # Most borrowed equipment (top 5)
    most_borrowed = (db.session.query(Equipment, func.count(BorrowLog.id).label('borrow_count'))
                    .join(BorrowLog)
                    .group_by(Equipment.id)
                    .order_by(func.count(BorrowLog.id).desc())
                    .limit(5)
                    .all())
    
    # Top consumed items (top 5)
    top_consumed = (db.session.query(Consumable)
                   .filter(Consumable.units_consumed > 0)
                   .order_by(Consumable.units_consumed.desc())
                   .limit(5)
                   .all())
    
    # === STUDENT NOTES/ISSUES TRENDS ===
    all_notes = StudentNote.query.all()
    pending_notes = StudentNote.query.filter(StudentNote.status == 'pending').all()
    resolved_notes = StudentNote.query.filter(StudentNote.status == 'resolved').all()
    
    # Group notes by issue type
    issues_by_type = {}
    for note in all_notes:
        note_type = note.note_type
        if note_type not in issues_by_type:
            issues_by_type[note_type] = 0
        issues_by_type[note_type] += 1
    
    # Recent issues (last 30 days)
    recent_issues = (db.session.query(StudentNote)
                    .filter(StudentNote.created_at >= thirty_days_ago.strftime('%Y-%m-%d'))
                    .all())
    recent_pending = [n for n in recent_issues if n.status == 'pending']
    
    # === MAINTENANCE TRENDS ===
    # All maintenance records
    all_maintenance = EquipmentMaintenance.query.all()
    completed_maintenance = [m for m in all_maintenance if m.status == 'completed']
    scheduled_maintenance = [m for m in all_maintenance if m.status == 'scheduled']
    
    # Auto-update overdue status
    for m in scheduled_maintenance:
        if m.scheduled_date and m.scheduled_date < current_date:
            m.status = 'overdue'
    db.session.commit()
    
    # Recalculate after status updates
    overdue_maintenance = [m for m in all_maintenance if m.status == 'overdue']
    scheduled_maintenance = [m for m in all_maintenance if m.status == 'scheduled']
    
    # Recent maintenance (last 30 days)
    recent_maintenance = [m for m in all_maintenance if m.created_at and m.created_at.date() >= thirty_days_ago]
    recent_completed = [m for m in recent_maintenance if m.status == 'completed']
    
    # Maintenance by type
    maintenance_by_type = {}
    for m in all_maintenance:
        m_type = m.maintenance_type
        if m_type not in maintenance_by_type:
            maintenance_by_type[m_type] = 0
        maintenance_by_type[m_type] += 1
    
    # Total maintenance cost
    total_maintenance_cost = sum(_to_int(m.cost, 0) for m in completed_maintenance)
    
    # Completion rate
    maintenance_completion_rate = 0
    if len(all_maintenance) > 0:
        maintenance_completion_rate = round((len(completed_maintenance) / len(all_maintenance)) * 100, 1)
    
    # === OVERALL STATISTICS ===
    total_equipment = Equipment.query.count()
    total_consumables = Consumable.query.count()
    total_users = User.query.count()
    
    # Equipment currently in use
    equipment_in_use = (db.session.query(Equipment)
                       .join(BorrowLog, BorrowLog.equipment_id == Equipment.id)
                       .filter(BorrowLog.returned_at.is_(None))
                       .distinct()
                       .count())
    
    return render_template('analytics.html',
                         # Alerts & Inventory
                         low_stock=low_stock_consumables,
                         near_expiration=near_expiration,
                         # Usage Trends
                         most_borrowed=most_borrowed,
                         top_consumed=top_consumed,
                         borrow_count_30d=borrow_count_30d,
                         active_borrows=active_borrows,
                         usage_count_30d=usage_count_30d,
                         total_units_consumed_30d=total_units_consumed_30d,
                         daily_borrows=daily_borrows,
                         daily_usage=daily_usage,
                         # Notes Trends
                         all_notes_count=len(all_notes),
                         pending_notes_count=len(pending_notes),
                         resolved_notes_count=len(resolved_notes),
                         recent_pending_count=len(recent_pending),
                         issues_by_type=issues_by_type,
                         recent_issues=recent_issues[:10],  # Last 10 issues
                         # Maintenance Trends
                         all_maintenance_count=len(all_maintenance),
                         completed_maintenance_count=len(completed_maintenance),
                         scheduled_maintenance_count=len(scheduled_maintenance),
                         overdue_maintenance_count=len(overdue_maintenance),
                         recent_completed_count=len(recent_completed),
                         maintenance_by_type=maintenance_by_type,
                         total_maintenance_cost=total_maintenance_cost,
                         maintenance_completion_rate=maintenance_completion_rate,
                         recent_maintenance=recent_maintenance[:10],  # Last 10 maintenance records
                         # Overall Statistics
                         total_equipment=total_equipment,
                         total_consumables=total_consumables,
                         total_users=total_users,
                         equipment_in_use=equipment_in_use)

@app.route('/analytics/export/pdf')
def export_analytics_pdf():
    """
    Export the analytics dashboard as a comprehensive PDF report
    including overall statistics, alerts, usage trends, and issues tracking.
    """
    if 'user_id' not in session:
        return redirect(url_for('login'))

    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak, Image
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import inch
    except ImportError:
        return ("Missing dependency: reportlab. Install it first, e.g. "
                "`pip install reportlab`"), 500

    from datetime import datetime, timedelta
    current_date = datetime.now().date()
    near_expiry_date = current_date + timedelta(days=30)
    thirty_days_ago = current_date - timedelta(days=30)
    
    # === GATHER ALL DATA ===
    low_stock_consumables = (db.session.query(Consumable)
                           .filter(Consumable.previous_month_stock > 0)
                           .filter((Consumable.items_out + Consumable.items_on_stock) < (Consumable.previous_month_stock * 0.1))
                           .all())
    
    near_expiration = []
    for c in Consumable.query.all():
        if c.expiration and c.expiration != 'N/A':
            try:
                exp_date = datetime.strptime(c.expiration, '%Y-%m-%d').date()
                if exp_date <= near_expiry_date:
                    near_expiration.append(c)
            except ValueError:
                continue
    
    recent_borrows = (db.session.query(BorrowLog)
                     .filter(BorrowLog.borrowed_at >= datetime.combine(thirty_days_ago, datetime.min.time()))
                     .all())
    active_borrows = db.session.query(BorrowLog).filter(BorrowLog.returned_at.is_(None)).count()
    
    recent_usage = (db.session.query(UsageLog)
                   .filter(UsageLog.used_at >= datetime.combine(thirty_days_ago, datetime.min.time()))
                   .all())
    total_units_consumed_30d = sum(u.quantity_used for u in recent_usage)
    
    most_borrowed = (db.session.query(Equipment, func.count(BorrowLog.id).label('borrow_count'))
                    .join(BorrowLog)
                    .group_by(Equipment.id)
                    .order_by(func.count(BorrowLog.id).desc())
                    .limit(5)
                    .all())
    
    top_consumed = (db.session.query(Consumable)
                   .filter(Consumable.units_consumed > 0)
                   .order_by(Consumable.units_consumed.desc())
                   .limit(5)
                   .all())
    
    all_notes = StudentNote.query.all()
    pending_notes = StudentNote.query.filter(StudentNote.status == 'pending').all()
    resolved_notes = StudentNote.query.filter(StudentNote.status == 'resolved').all()
    
    issues_by_type = {}
    for note in all_notes:
        note_type = note.note_type
        if note_type not in issues_by_type:
            issues_by_type[note_type] = 0
        issues_by_type[note_type] += 1
    
    total_equipment = Equipment.query.count()
    total_consumables = Consumable.query.count()
    total_users = User.query.count()
    
    equipment_in_use = (db.session.query(Equipment)
                       .join(BorrowLog, BorrowLog.equipment_id == Equipment.id)
                       .filter(BorrowLog.returned_at.is_(None))
                       .distinct()
                       .count())
    
    # === MAINTENANCE DATA ===
    all_maintenance = EquipmentMaintenance.query.all()
    completed_maintenance = [m for m in all_maintenance if m.status == 'completed']
    scheduled_maintenance = [m for m in all_maintenance if m.status == 'scheduled']
    
    # Auto-update overdue status
    for m in scheduled_maintenance:
        if m.scheduled_date and m.scheduled_date < current_date:
            m.status = 'overdue'
    db.session.commit()
    
    # Recalculate after status updates
    overdue_maintenance = [m for m in all_maintenance if m.status == 'overdue']
    scheduled_maintenance = [m for m in all_maintenance if m.status == 'scheduled']
    recent_maintenance = [m for m in all_maintenance if m.created_at and m.created_at.date() >= thirty_days_ago]
    recent_completed = [m for m in recent_maintenance if m.status == 'completed']
    
    # Maintenance by type
    maintenance_by_type = {}
    for m in all_maintenance:
        m_type = m.maintenance_type
        if m_type not in maintenance_by_type:
            maintenance_by_type[m_type] = 0
        maintenance_by_type[m_type] += 1
    
    # Total maintenance cost
    total_maintenance_cost = sum(_to_int(m.cost, 0) for m in completed_maintenance)
    
    # Completion rate
    maintenance_completion_rate = 0
    if len(all_maintenance) > 0:
        maintenance_completion_rate = round((len(completed_maintenance) / len(all_maintenance)) * 100, 1)
    
    # === BUILD PDF ===
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        leftMargin=18, rightMargin=18, topMargin=24, bottomMargin=18,
    )
    
    styles = getSampleStyleSheet()
    
    title_style = ParagraphStyle(
        'TitleStyle',
        parent=styles['Heading1'],
        fontSize=18,
        fontName='Helvetica-Bold',
        textColor=colors.HexColor("#1F2937"),
        spaceAfter=12,
    )
    
    heading_style = ParagraphStyle(
        'HeadingStyle',
        parent=styles['Heading2'],
        fontSize=12,
        fontName='Helvetica-Bold',
        textColor=colors.HexColor("#374151"),
        spaceAfter=8,
        spaceBefore=12,
    )
    
    cell_style = ParagraphStyle(
        'CellStyle',
        parent=styles['Normal'],
        fontSize=8,
        leading=10,
        wordWrap='CJK',
    )
    
    header_style = ParagraphStyle(
        'HeaderStyle',
        parent=styles['Normal'],
        fontSize=9,
        leading=11,
        fontName='Helvetica-Bold',
        wordWrap='CJK',
    )
    
    def create_paragraph(text, style=None):
        if style is None:
            style = cell_style
        if text is None or text == "":
            return Paragraph("", style)
        return Paragraph(str(text), style)
    
    def sval(x):
        return "" if x is None else str(x)
    
    elements = []
    
    # === TITLE ===
    elements.append(Paragraph("Lab Analytics Report", title_style))
    elements.append(Paragraph(f"Generated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}", styles["Normal"]))
    elements.append(Spacer(1, 12))
    
    # === OVERALL STATISTICS ===
    elements.append(Paragraph("Overall Statistics", heading_style))
    stats_data = [
        [create_paragraph("Total Equipment", header_style), create_paragraph(str(total_equipment), cell_style)],
        [create_paragraph("In Use", header_style), create_paragraph(str(equipment_in_use), cell_style)],
        [create_paragraph("Total Consumables", header_style), create_paragraph(str(total_consumables), cell_style)],
        [create_paragraph("Total Users", header_style), create_paragraph(str(total_users), cell_style)],
        [create_paragraph("Active Borrows", header_style), create_paragraph(str(active_borrows), cell_style)],
    ]
    stats_table = Table(stats_data, colWidths=[200, 100])
    stats_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F3F4F6")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#111827")),
        ("ALIGN", (0, 0), (-1, -1), "LEFT"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#FAFAFA")]),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#D1D5DB")),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    elements.append(stats_table)
    elements.append(Spacer(1, 12))
    
    # === LOW STOCK ALERT ===
    elements.append(Paragraph("Low Stock Alert (< 10% of Previous Month Stock)", heading_style))
    if low_stock_consumables:
        low_stock_data = [
            [create_paragraph("Item Description", header_style), 
             create_paragraph("Current Stock", header_style),
             create_paragraph("Percentage", header_style)]
        ]
        for item in low_stock_consumables[:10]:  # Limit to 10 rows
            current = item.items_out + item.items_on_stock
            percentage = (current / (item.previous_month_stock or 1)) * 100
            low_stock_data.append([
                create_paragraph(sval(item.description)),
                create_paragraph(sval(current)),
                create_paragraph(f"{percentage:.1f}%"),
            ])
        low_stock_table = Table(low_stock_data, colWidths=[250, 100, 100])
        low_stock_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#FEE2E2")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#991B1B")),
            ("ALIGN", (0, 0), (-1, -1), "LEFT"),
            ("ALIGN", (1, 0), (-1, -1), "CENTER"),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#D1D5DB")),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))
        elements.append(low_stock_table)
    else:
        elements.append(Paragraph("No items with critically low stock.", styles["Normal"]))
    elements.append(Spacer(1, 12))
    
    # === NEAR EXPIRATION ===
    elements.append(Paragraph("Items Near Expiration (Within 30 Days)", heading_style))
    if near_expiration:
        expiration_data = [
            [create_paragraph("Item Description", header_style), 
             create_paragraph("Expiration Date", header_style)]
        ]
        for item in near_expiration[:10]:  # Limit to 10 rows
            expiration_data.append([
                create_paragraph(sval(item.description)),
                create_paragraph(sval(item.expiration)),
            ])
        expiration_table = Table(expiration_data, colWidths=[250, 150])
        expiration_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#FEF3C7")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#92400E")),
            ("ALIGN", (0, 0), (-1, -1), "LEFT"),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#D1D5DB")),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))
        elements.append(expiration_table)
    else:
        elements.append(Paragraph("No items near expiration.", styles["Normal"]))
    elements.append(Spacer(1, 12))
    
    # === MOST BORROWED EQUIPMENT ===
    elements.append(Paragraph("Most Borrowed Equipment (Last 30 Days)", heading_style))
    if most_borrowed:
        borrowed_data = [
            [create_paragraph("Equipment", header_style), 
             create_paragraph("Borrow Count", header_style)]
        ]
        for equipment, count in most_borrowed:
            borrowed_data.append([
                create_paragraph(sval(equipment.description)),
                create_paragraph(sval(count)),
            ])
        borrowed_table = Table(borrowed_data, colWidths=[250, 100])
        borrowed_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#DCFCE7")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#166534")),
            ("ALIGN", (0, 0), (-1, -1), "LEFT"),
            ("ALIGN", (1, 0), (-1, -1), "CENTER"),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#D1D5DB")),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))
        elements.append(borrowed_table)
    else:
        elements.append(Paragraph("No borrowing records found.", styles["Normal"]))
    elements.append(Spacer(1, 12))
    
    # === TOP CONSUMED ITEMS ===
    elements.append(Paragraph("Top Consumed Items (All Time)", heading_style))
    if top_consumed:
        consumed_data = [
            [create_paragraph("Item Description", header_style), 
             create_paragraph("Units Consumed", header_style)]
        ]
        for item in top_consumed:
            consumed_data.append([
                create_paragraph(sval(item.description)),
                create_paragraph(sval(item.units_consumed)),
            ])
        consumed_table = Table(consumed_data, colWidths=[250, 100])
        consumed_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E9D5FF")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#6B21A8")),
            ("ALIGN", (0, 0), (-1, -1), "LEFT"),
            ("ALIGN", (1, 0), (-1, -1), "CENTER"),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#D1D5DB")),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))
        elements.append(consumed_table)
    else:
        elements.append(Paragraph("No consumption records found.", styles["Normal"]))
    elements.append(Spacer(1, 12))
    
    # PAGE BREAK
    elements.append(PageBreak())
    
    # === ISSUES & NOTES TRACKING ===
    elements.append(Paragraph("Student Issues & Notes Tracking", heading_style))
    
    issues_stats_data = [
        [create_paragraph("Total Issues", header_style), create_paragraph(str(len(all_notes)), cell_style)],
        [create_paragraph("Pending Issues", header_style), create_paragraph(str(len(pending_notes)), cell_style)],
        [create_paragraph("Resolved Issues", header_style), create_paragraph(str(len(resolved_notes)), cell_style)],
        [create_paragraph("Resolution Rate", header_style), 
         create_paragraph(f"{(len(resolved_notes) / (len(all_notes) or 1)) * 100:.1f}%", cell_style)],
    ]
    issues_stats_table = Table(issues_stats_data, colWidths=[200, 100])
    issues_stats_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F3F4F6")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#111827")),
        ("ALIGN", (0, 0), (-1, -1), "LEFT"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#FAFAFA")]),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#D1D5DB")),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    elements.append(issues_stats_table)
    elements.append(Spacer(1, 12))
    
    # Issues by type
    if issues_by_type:
        elements.append(Paragraph("Issues by Type", heading_style))
        type_data = [
            [create_paragraph("Issue Type", header_style), 
             create_paragraph("Count", header_style)]
        ]
        for issue_type, count in sorted(issues_by_type.items()):
            type_data.append([
                create_paragraph(sval(issue_type)),
                create_paragraph(sval(count)),
            ])
        type_table = Table(type_data, colWidths=[250, 100])
        type_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F3F4F6")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#111827")),
            ("ALIGN", (0, 0), (-1, -1), "LEFT"),
            ("ALIGN", (1, 0), (-1, -1), "CENTER"),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#D1D5DB")),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))
        elements.append(type_table)
        elements.append(Spacer(1, 12))
    
    # === EQUIPMENT MAINTENANCE TRACKING ===
    if session.get('role') in ['admin', 'tech']:
        elements.append(PageBreak())
        elements.append(Paragraph("Equipment Maintenance Tracking", heading_style))
        
        maintenance_stats_data = [
            [create_paragraph("Total Maintenance Records", header_style), create_paragraph(str(len(all_maintenance)), cell_style)],
            [create_paragraph("Completed", header_style), create_paragraph(str(len(completed_maintenance)), cell_style)],
            [create_paragraph("Scheduled", header_style), create_paragraph(str(len(scheduled_maintenance)), cell_style)],
            [create_paragraph("Overdue", header_style), create_paragraph(str(len(overdue_maintenance)), cell_style)],
            [create_paragraph("Completion Rate", header_style), create_paragraph(f"{maintenance_completion_rate}%", cell_style)],
            [create_paragraph("Total Maintenance Cost", header_style), create_paragraph(f"₱{total_maintenance_cost:,.2f}", cell_style)],
            [create_paragraph("Completed (Last 30 Days)", header_style), create_paragraph(str(len(recent_completed)), cell_style)],
        ]
        maintenance_stats_table = Table(maintenance_stats_data, colWidths=[250, 150])
        maintenance_stats_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#ECFEFF")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#164E63")),
            ("ALIGN", (0, 0), (-1, -1), "LEFT"),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#FAFAFA")]),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#D1D5DB")),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        elements.append(maintenance_stats_table)
        elements.append(Spacer(1, 12))
        
        # Maintenance by type
        if maintenance_by_type:
            elements.append(Paragraph("Maintenance by Type", heading_style))
            maint_type_data = [
                [create_paragraph("Maintenance Type", header_style), 
                 create_paragraph("Count", header_style)]
            ]
            for maint_type, count in sorted(maintenance_by_type.items()):
                maint_type_data.append([
                    create_paragraph(maint_type.capitalize()),
                    create_paragraph(str(count)),
                ])
            maint_type_table = Table(maint_type_data, colWidths=[250, 100])
            maint_type_table.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#ECFEFF")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#164E63")),
                ("ALIGN", (0, 0), (-1, -1), "LEFT"),
                ("ALIGN", (1, 0), (-1, -1), "CENTER"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#D1D5DB")),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]))
            elements.append(maint_type_table)
            elements.append(Spacer(1, 12))
        
        # Recent maintenance records
        if recent_maintenance:
            elements.append(Paragraph("Recent Maintenance (Last 30 Days)", heading_style))
            recent_maint_data = [
                [create_paragraph("Equipment", header_style),
                 create_paragraph("Type", header_style),
                 create_paragraph("Scheduled", header_style),
                 create_paragraph("Status", header_style),
                 create_paragraph("Cost", header_style)]
            ]
            for m in recent_maintenance[:15]:  # Limit to 15 records
                equipment_desc = m.equipment.description if m.equipment else 'Unknown'
                recent_maint_data.append([
                    create_paragraph(equipment_desc),
                    create_paragraph(m.maintenance_type.capitalize()),
                    create_paragraph(str(m.scheduled_date)),
                    create_paragraph(m.status.capitalize()),
                    create_paragraph(f"₱{m.cost:,.2f}" if m.cost else "N/A"),
                ])
            recent_maint_table = Table(recent_maint_data, colWidths=[180, 80, 80, 80, 80])
            recent_maint_table.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#ECFEFF")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#164E63")),
                ("ALIGN", (0, 0), (-1, -1), "LEFT"),
                ("ALIGN", (1, 0), (-1, -1), "CENTER"),
                ("FONTSIZE", (0, 0), (-1, -1), 7),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#D1D5DB")),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]))
            elements.append(recent_maint_table)
            elements.append(Spacer(1, 12))
    
    # === USAGE SUMMARY ===
    elements.append(Paragraph("30-Day Usage Summary", heading_style))
    usage_summary_data = [
        [create_paragraph("Metric", header_style), create_paragraph("Value", header_style)],
        [create_paragraph("Equipment Borrowing Events", cell_style), create_paragraph(str(len(recent_borrows)), cell_style)],
        [create_paragraph("Consumable Usage Events", cell_style), create_paragraph(str(len(recent_usage)), cell_style)],
        [create_paragraph("Total Units Consumed", cell_style), create_paragraph(str(total_units_consumed_30d), cell_style)],
    ]
    usage_summary_table = Table(usage_summary_data, colWidths=[250, 100])
    usage_summary_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F3F4F6")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#111827")),
        ("ALIGN", (0, 0), (-1, -1), "LEFT"),
        ("ALIGN", (1, 0), (-1, -1), "CENTER"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#FAFAFA")]),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#D1D5DB")),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    elements.append(usage_summary_table)
    
    # Build the PDF document
    doc.build(elements)
    buffer.seek(0)
    
    filename = f"analytics_report_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.pdf"
    return send_file(
        buffer,
        mimetype="application/pdf",
        as_attachment=True,
        download_name=filename
    )

@app.route('/backup')
def backup_database():
    if session.get('role') != 'admin':
        return redirect(url_for('dashboard'))
    
    db_path = os.path.join(basedir, "instance", "database.db")
    if os.path.exists(db_path):
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        return send_file(db_path, as_attachment=True, download_name=f"backup_cmt_inventory_{timestamp}.db")
    else:
        return "Database file not found", 404

# ========== EQUIPMENT MAINTENANCE ROUTES ==========
@app.route('/maintenance')
def maintenance():
    if session.get('role') not in ['admin', 'tech']:
        return redirect(url_for('dashboard'))
    
    from datetime import date
    
    q = request.args.get('q', '').strip()
    sort = request.args.get('sort', 'scheduled_date')
    direction = request.args.get('dir', 'desc').lower()
    direction = 'desc' if direction == 'desc' else 'asc'
    status_filter = request.args.get('status', 'all')  # all, scheduled, completed, overdue
    type_filter = request.args.get('type', 'all')  # all, calibration, repair, preventive, inspection
    
    sortable_fields = {
        'equipment', 'maintenance_type', 'scheduled_date', 'completed_date', 
        'performed_by', 'cost', 'status', 'created_at'
    }
    if sort not in sortable_fields:
        sort = 'scheduled_date'
    
    # Build query with joins
    query = EquipmentMaintenance.query.outerjoin(Equipment)
    
    # Search filter
    if q:
        like = f"%{q}%"
        query = query.filter(or_(
            Equipment.description.ilike(like),
            EquipmentMaintenance.maintenance_type.ilike(like),
            EquipmentMaintenance.performed_by.ilike(like),
            EquipmentMaintenance.notes.ilike(like),
        ))
    
    # Status filter
    if status_filter != 'all':
        query = query.filter(EquipmentMaintenance.status == status_filter)
    
    # Type filter
    if type_filter != 'all':
        query = query.filter(EquipmentMaintenance.maintenance_type == type_filter)
    
    # Sorting
    if sort == 'equipment':
        sort_col = Equipment.description
    else:
        sort_col = getattr(EquipmentMaintenance, sort)
    
    query = query.order_by(sort_col.desc() if direction == 'desc' else sort_col.asc())
    
    records = query.all()
    
    # Update overdue status for scheduled items past due date
    today = date.today()
    for record in records:
        if record.status == 'scheduled' and record.scheduled_date < today:
            record.status = 'overdue'
    db.session.commit()
    
    return render_template('maintenance.html', 
                         records=records, 
                         q=q, 
                         sort=sort, 
                         dir=direction,
                         status_filter=status_filter,
                         type_filter=type_filter)

@app.route('/maintenance/add', methods=['GET', 'POST'])
def add_maintenance():
    if session.get('role') not in ['admin', 'tech']:
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        from datetime import datetime
        
        scheduled_date = request.form.get('scheduled_date')
        
        record = EquipmentMaintenance(
            equipment_id=request.form['equipment_id'],
            maintenance_type=request.form['maintenance_type'],
            scheduled_date=datetime.strptime(scheduled_date, '%Y-%m-%d').date(),
            performed_by=request.form.get('performed_by'),
            notes=request.form.get('notes'),
            cost=float(request.form.get('cost', 0.0) or 0.0),
            status='scheduled',
            created_by=session['user_id']
        )
        db.session.add(record)
        db.session.commit()
        return redirect(url_for('maintenance'))
    
    equipment_list = Equipment.query.order_by(Equipment.description).all()
    return render_template('add_maintenance.html', equipment=equipment_list)

@app.route('/maintenance/edit/<int:id>', methods=['GET', 'POST'])
def edit_maintenance(id):
    if session.get('role') not in ['admin', 'tech']:
        return redirect(url_for('dashboard'))
    
    record = EquipmentMaintenance.query.get_or_404(id)
    
    if request.method == 'POST':
        from datetime import datetime
        
        scheduled_date = request.form.get('scheduled_date')
        completed_date = request.form.get('completed_date')
        
        record.equipment_id = request.form['equipment_id']
        record.maintenance_type = request.form['maintenance_type']
        record.scheduled_date = datetime.strptime(scheduled_date, '%Y-%m-%d').date()
        
        if completed_date:
            record.completed_date = datetime.strptime(completed_date, '%Y-%m-%d').date()
            record.status = 'completed'
        else:
            record.completed_date = None
            # Update status based on scheduled date
            from datetime import date
            if record.scheduled_date < date.today():
                record.status = 'overdue'
            else:
                record.status = 'scheduled'
        
        record.performed_by = request.form.get('performed_by')
        record.notes = request.form.get('notes')
        record.cost = float(request.form.get('cost', 0.0) or 0.0)
        
        db.session.commit()
        return redirect(url_for('maintenance'))
    
    equipment_list = Equipment.query.order_by(Equipment.description).all()
    return render_template('edit_maintenance.html', record=record, equipment=equipment_list)

@app.route('/maintenance/complete/<int:id>', methods=['POST'])
def complete_maintenance(id):
    if session.get('role') not in ['admin', 'tech']:
        return redirect(url_for('dashboard'))
    
    from datetime import date
    
    record = EquipmentMaintenance.query.get_or_404(id)
    record.status = 'completed'
    record.completed_date = date.today()
    
    # Optionally update performed_by if provided
    performed_by = request.form.get('performed_by')
    if performed_by:
        record.performed_by = performed_by
    
    db.session.commit()
    return redirect(url_for('maintenance'))

@app.route('/maintenance/delete/<int:id>', methods=['POST'])
def delete_maintenance(id):
    if session.get('role') not in ['admin', 'tech']:
        return redirect(url_for('dashboard'))
    
    record = EquipmentMaintenance.query.get_or_404(id)
    db.session.delete(record)
    db.session.commit()
    return redirect(url_for('maintenance'))


# ==================== BARCODE FUNCTIONS ====================

def generate_barcode_string(prefix, item_id):
    """Generate a unique barcode string for an item."""
    random_suffix = uuid.uuid4().hex[:4].upper()
    return f"{prefix}-{item_id:04d}-{random_suffix}"

def ensure_equipment_barcode(equipment):
    """Ensure equipment has a barcode, generate one if missing."""
    if not equipment.barcode:
        equipment.barcode = generate_barcode_string("EQ", equipment.id)
        db.session.commit()
    return equipment.barcode

def ensure_consumable_barcode(consumable):
    """Ensure consumable has a barcode, generate one if missing."""
    if not consumable.barcode:
        consumable.barcode = generate_barcode_string("CON", consumable.id)
        db.session.commit()
    return consumable.barcode


# ==================== BARCODE ROUTES ====================

@app.route('/barcode/equipment/<int:id>')
def get_equipment_barcode(id):
    """Generate and return barcode image for equipment."""
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    equipment = Equipment.query.get_or_404(id)
    barcode_value = ensure_equipment_barcode(equipment)
    
    # Generate barcode image
    CODE128 = barcode.get_barcode_class('code128')
    buffer = io.BytesIO()
    
    # Create barcode with ImageWriter for PNG output
    ean = CODE128(barcode_value, writer=ImageWriter())
    ean.write(buffer, options={
        'module_width': 0.4,
        'module_height': 15.0,
        'font_size': 10,
        'text_distance': 5.0,
        'quiet_zone': 6.5
    })
    
    buffer.seek(0)
    return send_file(buffer, mimetype='image/png', as_attachment=False)


@app.route('/barcode/equipment/<int:id>/svg')
def get_equipment_barcode_svg(id):
    """Generate and return barcode SVG for equipment."""
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    equipment = Equipment.query.get_or_404(id)
    barcode_value = ensure_equipment_barcode(equipment)
    
    # Generate barcode SVG
    CODE128 = barcode.get_barcode_class('code128')
    buffer = io.BytesIO()
    
    ean = CODE128(barcode_value, writer=SVGWriter())
    ean.write(buffer, options={
        'module_width': 0.4,
        'module_height': 15.0,
        'font_size': 10,
        'text_distance': 5.0,
        'quiet_zone': 6.5
    })
    
    buffer.seek(0)
    return send_file(buffer, mimetype='image/svg+xml', as_attachment=False)


@app.route('/barcode/consumable/<int:id>')
def get_consumable_barcode(id):
    """Generate and return barcode image for consumable."""
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    consumable = Consumable.query.get_or_404(id)
    barcode_value = ensure_consumable_barcode(consumable)
    
    # Generate barcode image
    CODE128 = barcode.get_barcode_class('code128')
    buffer = io.BytesIO()
    
    ean = CODE128(barcode_value, writer=ImageWriter())
    ean.write(buffer, options={
        'module_width': 0.4,
        'module_height': 15.0,
        'font_size': 10,
        'text_distance': 5.0,
        'quiet_zone': 6.5
    })
    
    buffer.seek(0)
    return send_file(buffer, mimetype='image/png', as_attachment=False)


@app.route('/barcode/consumable/<int:id>/svg')
def get_consumable_barcode_svg(id):
    """Generate and return barcode SVG for consumable."""
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    consumable = Consumable.query.get_or_404(id)
    barcode_value = ensure_consumable_barcode(consumable)
    
    # Generate barcode SVG
    CODE128 = barcode.get_barcode_class('code128')
    buffer = io.BytesIO()
    
    ean = CODE128(barcode_value, writer=SVGWriter())
    ean.write(buffer, options={
        'module_width': 0.4,
        'module_height': 15.0,
        'font_size': 10,
        'text_distance': 5.0,
        'quiet_zone': 6.5
    })
    
    buffer.seek(0)
    return send_file(buffer, mimetype='image/svg+xml', as_attachment=False)


@app.route('/barcode/lookup', methods=['GET'])
def barcode_lookup():
    """Look up an item by its barcode value."""
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    
    barcode_value = request.args.get('code', '').strip()
    
    if not barcode_value:
        return jsonify({'error': 'No barcode provided'}), 400
    
    # Try to find in equipment
    equipment = Equipment.query.filter_by(barcode=barcode_value).first()
    if equipment:
        return jsonify({
            'found': True,
            'type': 'equipment',
            'id': equipment.id,
            'description': equipment.description,
            'barcode': equipment.barcode,
            'url': url_for('edit_equipment', id=equipment.id),
            'borrow_url': url_for('borrow_equipment_row', id=equipment.id)
        })
    
    # Try to find in consumables
    consumable = Consumable.query.filter_by(barcode=barcode_value).first()
    if consumable:
        return jsonify({
            'found': True,
            'type': 'consumable',
            'id': consumable.id,
            'description': consumable.description,
            'barcode': consumable.barcode,
            'url': url_for('edit_consumable', id=consumable.id),
            'use_url': url_for('use_consumable_row', id=consumable.id)
        })
    
    return jsonify({
        'found': False,
        'message': f'No item found with barcode: {barcode_value}'
    })


@app.route('/barcode/equipment/<int:id>/regenerate', methods=['POST'])
def regenerate_equipment_barcode(id):
    """Regenerate barcode for equipment."""
    if session.get('role') not in ['admin', 'tech']:
        return jsonify({'error': 'Unauthorized'}), 403
    
    equipment = Equipment.query.get_or_404(id)
    equipment.barcode = generate_barcode_string("EQ", equipment.id)
    db.session.commit()
    
    return jsonify({
        'success': True,
        'barcode': equipment.barcode,
        'barcode_url': url_for('get_equipment_barcode', id=equipment.id)
    })


@app.route('/barcode/consumable/<int:id>/regenerate', methods=['POST'])
def regenerate_consumable_barcode(id):
    """Regenerate barcode for consumable."""
    if session.get('role') not in ['admin', 'tech']:
        return jsonify({'error': 'Unauthorized'}), 403
    
    consumable = Consumable.query.get_or_404(id)
    consumable.barcode = generate_barcode_string("CON", consumable.id)
    db.session.commit()
    
    return jsonify({
        'success': True,
        'barcode': consumable.barcode,
        'barcode_url': url_for('get_consumable_barcode', id=consumable.id)
    })


@app.route('/barcode/print/equipment/<int:id>')
def print_equipment_barcode(id):
    """Render printable barcode page for equipment."""
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    equipment = Equipment.query.get_or_404(id)
    ensure_equipment_barcode(equipment)
    
    return render_template('print_barcode.html', 
                           item=equipment, 
                           item_type='equipment',
                           barcode_url=url_for('get_equipment_barcode', id=id))


@app.route('/barcode/print/consumable/<int:id>')
def print_consumable_barcode(id):
    """Render printable barcode page for consumable."""
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    consumable = Consumable.query.get_or_404(id)
    ensure_consumable_barcode(consumable)
    
    return render_template('print_barcode.html', 
                           item=consumable, 
                           item_type='consumable',
                           barcode_url=url_for('get_consumable_barcode', id=id))


if __name__ == '__main__':
    # Use 0.0.0.0 to be accessible from other devices if needed, 
    # but strictly localhost is safer for a standalone app.
    app.run(debug=True, host='0.0.0.0', port=5000)