import os
import io
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, session, send_file
from models import db, User, Equipment, Consumable, BorrowLog, UsageLog, StudentNote
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy import or_, func

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
      previous_month_stock = balance_stock + units_consumed
    """
    # Normalize row-level nonnegatives first
    normalize_row_nonnegatives(row)
    
    # Calculate balance_stock for this specific row
    row_balance_stock = _clamp_nonneg(_to_int(row.items_out, 0) + _to_int(row.items_on_stock, 0))
    
    # Calculate previous_month_stock for this specific row
    row_previous_month_stock = _clamp_nonneg(row_balance_stock + _to_int(row.units_consumed, 0))
    
    # Assign the calculated values to the row
    row.balance_stock = row_balance_stock
    row.previous_month_stock = row_previous_month_stock

def recalc_group_by_description(description: str):
    """
    Calculate row-level balance_stock and previous_month_stock for each row
    with the given description independently.
    """
    if not description:
        return
    rows = Consumable.query.filter(Consumable.description == description).all()
    if not rows:
        return

    # Calculate values independently for each row
    for row in rows:
        recalc_row_level_values(row)
    
    # Caller is responsible for committing

def recalc_all_description_groups():
    descriptions = [d[0] for d in db.session.query(Consumable.description).distinct().all()]
    for desc in descriptions:
        recalc_group_by_description(desc)
    db.session.commit()

def recalc_single_row(row: Consumable):
    """
    Convenience function to recalculate values for a single row.
    """
    recalc_row_level_values(row)

def consume_from_group(description: str, quantity: int):
    """
    Reduce items_on_stock across the group FIFO by expiration date.
    Returns the remaining quantity that could not be fulfilled (0 if fully applied).
    """
    remaining = _clamp_nonneg(quantity)
    if remaining == 0:
        return 0

    rows = (Consumable.query
            .filter(Consumable.description == description)
            .all())
    # Sort rows by expiration heuristic (soonest usable first)
    rows.sort(key=lambda r: _expiration_sort_key(r.expiration))

    for r in rows:
        on = _clamp_nonneg(r.items_on_stock)
        if on <= 0:
            continue
        take = min(on, remaining)
        r.items_on_stock = on - take
        remaining -= take
        if remaining == 0:
            break
    return remaining

# Ensure DB + default admin user exist and seed
with app.app_context():
    os.makedirs(os.path.join(basedir, "instance"), exist_ok=True)
    db.create_all()

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

    # After seeding, enforce group-level constraints across all descriptions
    recalc_all_description_groups()

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
    return render_template('dashboard.html', role=session['role'])

# Update equipment function for bulk borrowing calculation
@app.route('/equipment')
def equipment():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    q = request.args.get('q', '').strip()
    sort = request.args.get('sort', 'description')
    direction = request.args.get('dir', 'asc').lower()
    direction = 'desc' if direction == 'desc' else 'asc'

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

    return render_template('equipment.html', items=items, q=q, sort=sort, dir=direction)

@app.route('/consumables')
def consumables():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    q = request.args.get('q', '').strip()
    sort = request.args.get('sort', 'description')
    direction = request.args.get('dir', 'asc').lower()
    direction = 'desc' if direction == 'desc' else 'asc'

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

    sort_col = getattr(Consumable, sort)
    if direction == 'desc':
        query = query.order_by(sort_col.desc())
    else:
        query = query.order_by(sort_col.asc())

    items = query.all()
    return render_template('consumables.html', items=items, q=q, sort=sort, dir=direction)

@app.route('/consumables/export/pdf')
def export_consumables_pdf():
    """
    Export the current consumables view (respecting q, sort, dir)
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
    meta = Paragraph(
        f"Generated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')} "
        f"| Search: '{q or ''}' | Sort: {sort} {direction.upper()}",
        styles["Normal"],
    )

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
    Export the current equipment view (respecting q, sort, dir)
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
    elements.append(Paragraph(
        f"Generated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')} "
        f"| Search: '{q or ''}' | Sort: {sort} {direction.upper()}",
        styles["Normal"],
    ))
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
        description = c.description or ""

        # Log usage with new field names
        log = UsageLog(
            user_name=request.form['user_name'],
            user_type=request.form['user_type'],
            section_course=request.form['section_course'],
            purpose=request.form['purpose'],
            consumable_id=consumable_id,
            quantity_used=quantity_used
        )
        db.session.add(log)

        # Rest of the logic remains the same...
        c.units_consumed = _to_int(c.units_consumed, 0) + quantity_used
        remaining = consume_from_group(description, quantity_used)
        recalc_group_by_description(description)

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

# Update use_consumable_row function
@app.route('/consumables/use/<int:id>', methods=['GET', 'POST'])
def use_consumable_row(id):
    if session.get('role') not in ['tech', 'admin']:
        return redirect(url_for('dashboard'))
    
    c = Consumable.query.get_or_404(id)
    
    if request.method == 'POST':
        quantity_used = _clamp_nonneg(request.form['quantity'])

        if quantity_used > 0:
            # Log usage with new field names
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

            # Reduce items_on_stock from the group FIFO
            description = c.description or ""
            consume_from_group(description, quantity_used)

            # Recalc description group to enforce constraints
            recalc_group_by_description(description)

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
                log.consumable.items_on_stock = _to_int(log.consumable.items_on_stock, 0) + quantity_returned
                
                # Store the returned quantity for tracking
                log.quantity_returned = quantity_returned
            
            # Optional: create a student note for issues
            note_type = (request.form.get('note_type') or '').strip().lower()
            note_description = (request.form.get('description') or '').strip()

            if note_type and note_type != 'none' and note_description:
                note = StudentNote(
                    person_name=log.user_name,
                    person_number=log.user_type,  # or appropriate ID field
                    person_type=log.user_type,
                    section_course=log.section_course,
                    note_type=note_type,
                    description=note_description,
                    consumable_id=log.consumable_id,
                    equipment_id=None,
                    created_by=session['user_id']
                )
                db.session.add(note)
            
            # Recalculate group constraints
            recalc_group_by_description(log.consumable.description)
        
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

                    # Update consumable stock
                    c.units_consumed = _to_int(c.units_consumed, 0) + quantity_used
                    description = c.description or ""
                    remaining = consume_from_group(description, quantity_used)
                    recalc_group_by_description(description)
    
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
        is_returnable = request.form.get('returnable_type') == 'returnable'
        
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
        db.session.flush()  # ensure consumable has an id

        # Enforce description-level constraints
        recalc_group_by_description(consumable.description)

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
        old_desc = consumable.description

        # Convert returnable type to boolean
        is_returnable = request.form.get('returnable_type') == 'returnable'

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

        # Recalc for both old and new description if changed
        if (old_desc or "") != (consumable.description or ""):
            recalc_group_by_description(old_desc)
        recalc_group_by_description(consumable.description)

        db.session.commit()
        return redirect(url_for('consumables'))
    
    return render_template('edit_consumable.html', consumable=consumable)

# Delete Consumable
@app.route('/consumables/delete/<int:id>', methods=['POST'])
def delete_consumable(id):
    if session.get('role') not in ['admin', 'tech']:
        return redirect(url_for('dashboard'))
    
    consumable = Consumable.query.get_or_404(id)
    desc = consumable.description  # keep for optional group recalculation

    # Clean up dependent rows to avoid FK issues (if constraints are enforced)
    UsageLog.query.filter_by(consumable_id=consumable.id).delete(synchronize_session=False)
    StudentNote.query.filter_by(consumable_id=consumable.id).delete(synchronize_session=False)

    db.session.delete(consumable)
    db.session.commit()

    recalc_group_by_description(desc)
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
            created_by=session['user_id']
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

    # Updated sortable fields
    sortable_fields = {
        'person_name', 'person_type', 'section_course',
        'note_type', 'description', 'related_item', 'reported_by', 'created_at'
    }
    if sort not in sortable_fields:
        sort = 'created_at'

    # Build query with joins for related item and reporter
    query = (StudentNote.query
             .outerjoin(Equipment, StudentNote.equipment_id == Equipment.id)
             .outerjoin(Consumable, StudentNote.consumable_id == Consumable.id)
             .join(User, StudentNote.created_by == User.id))

    # COALESCE to pick the related item's description (equipment first, else consumable)
    related_item_col = func.coalesce(Equipment.description, Consumable.description)
    reported_by_col = User.username

    if q:
        like = f"%{q}%"
        query = query.filter(or_(
            StudentNote.person_name.ilike(like),
            StudentNote.person_type.ilike(like),
            StudentNote.section_course.ilike(like),
            StudentNote.note_type.ilike(like),
            StudentNote.description.ilike(like),
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

    return render_template('student_notes.html', notes=notes, q=q, sort=sort, dir=direction)

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
    
    # Low stock items (10% threshold)
    low_stock_consumables = (db.session.query(Consumable)
                           .filter(Consumable.items_on_stock <= (Consumable.previous_month_stock * 0.1))
                           .filter(Consumable.previous_month_stock.isnot(None))
                           .all())
    
    # Most borrowed equipment (top 5)
    most_borrowed = (db.session.query(Equipment, func.count(BorrowLog.id).label('borrow_count'))
                    .join(BorrowLog)
                    .group_by(Equipment.id)
                    .order_by(func.count(BorrowLog.id).desc())
                    .limit(5)
                    .all())
    
    # Near expiration consumables (within 30 days or already expired)
    from datetime import datetime, timedelta
    current_date = datetime.now().date()
    near_expiry_date = current_date + timedelta(days=30)
    
    near_expiration = []
    for c in Consumable.query.all():
        if c.expiration and c.expiration != 'N/A':
            try:
                exp_date = datetime.strptime(c.expiration, '%Y-%m-%d').date()
                if exp_date <= near_expiry_date:
                    near_expiration.append(c)
            except ValueError:
                continue
    
    # Top consumed items (top 5)
    top_consumed = (db.session.query(Consumable)
                   .filter(Consumable.units_consumed > 0)
                   .order_by(Consumable.units_consumed.desc())
                   .limit(5)
                   .all())
    
    
    return render_template('analytics.html',
                         low_stock=low_stock_consumables,
                         most_borrowed=most_borrowed,
                         near_expiration=near_expiration,
                         top_consumed=top_consumed)  # Top 10 most utilized

if __name__ == '__main__':
    app.run(host=0.0.0.0, port=5000, debug=True)