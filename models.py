from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(120), nullable=False)
    role = db.Column(db.String(20), nullable=False)  # admin, tech, faculty

class Equipment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    description = db.Column(db.String(200), nullable=False)
    qty = db.Column(db.Integer)
    date_purchased = db.Column(db.String(20))
    serial_number = db.Column(db.String(100))
    brand_name = db.Column(db.String(100))
    model = db.Column(db.String(100))
    remarks = db.Column(db.String(100))
    location = db.Column(db.String(200))

class Consumable(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    balance_stock = db.Column(db.Integer)
    unit = db.Column(db.String(50))
    # Removed test and total columns as requested
    description = db.Column(db.String(200))
    expiration = db.Column(db.String(20))
    lot_number = db.Column(db.String(50))
    date_received = db.Column(db.String(20))
    items_out = db.Column(db.Integer)
    items_on_stock = db.Column(db.Integer)
    previous_month_stock = db.Column(db.Integer)
    units_consumed = db.Column(db.Integer)
    units_expired = db.Column(db.Integer)
    # Added returnable field for powder/liquid items
    is_returnable = db.Column(db.Boolean, default=False, nullable=False)

class BorrowLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    # Changed from student-specific to borrower/user information
    borrower_name = db.Column(db.String(100), nullable=False)
    borrower_type = db.Column(db.String(20), nullable=False)  # 'student' or 'faculty'
    section_course = db.Column(db.String(150), nullable=False)  # Combined section + course
    purpose = db.Column(db.Text, nullable=False)
    equipment_id = db.Column(db.Integer, db.ForeignKey('equipment.id'))
    # Added quantity for bulk borrowing
    quantity_borrowed = db.Column(db.Integer, default=1, nullable=False)
    borrowed_at = db.Column(db.DateTime, default=db.func.current_timestamp())
    returned_at = db.Column(db.DateTime, nullable=True)
    equipment = db.relationship('Equipment', backref='borrow_logs')

class UsageLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    # Changed from student-specific to user information
    user_name = db.Column(db.String(100), nullable=False)
    user_type = db.Column(db.String(20), nullable=False)  # 'student' or 'faculty'
    section_course = db.Column(db.String(150), nullable=False)  # Combined section + course
    purpose = db.Column(db.Text, nullable=False)
    consumable_id = db.Column(db.Integer, db.ForeignKey('consumable.id'))
    quantity_used = db.Column(db.Integer)
    used_at = db.Column(db.DateTime, default=db.func.current_timestamp())
    consumable = db.relationship('Consumable', backref='usage_logs')
    returned_at = db.Column(db.DateTime, nullable=True)


class StudentNote(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    # Updated to use new naming convention
    person_name = db.Column(db.String(100), nullable=False)
    person_number = db.Column(db.String(20), nullable=False)
    person_type = db.Column(db.String(20), nullable=False)  # 'student' or 'faculty'
    section_course = db.Column(db.String(150), nullable=False)
    note_type = db.Column(db.String(20), nullable=False)  # 'lost', 'damaged', 'other'
    description = db.Column(db.Text, nullable=False)
    equipment_id = db.Column(db.Integer, db.ForeignKey('equipment.id'), nullable=True)
    consumable_id = db.Column(db.Integer, db.ForeignKey('consumable.id'), nullable=True)
    created_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=db.func.current_timestamp())
    
    # Relationships
    equipment = db.relationship('Equipment', backref='student_notes')
    consumable = db.relationship('Consumable', backref='student_notes')
    creator = db.relationship('User', backref='created_notes')