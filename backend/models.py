# models.py - Updated to import from database.py instead of app.py
from database import db  # Import from the new database.py file
from datetime import datetime

class Customer(db.Model):
    __tablename__ = 'customers'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    address = db.Column(db.Text)
    phone = db.Column(db.String(50))
    email = db.Column(db.String(200))
    status = db.Column(db.String(50), default='Active')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    jobs = db.relationship("Job", back_populates="customer", lazy=True)
    quotations = db.relationship("Quotation", back_populates="customer", lazy=True, cascade="all, delete-orphan")
    form_data = db.relationship("CustomerFormData", back_populates="customer", lazy=True, cascade="all, delete-orphan")
    form_submissions = db.relationship("FormSubmission", back_populates="customer", lazy=True)

    def __repr__(self):
        return f'<Customer {self.name}>'


class Job(db.Model):
    __tablename__ = 'jobs'

    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey('customers.id'), nullable=False)

    # Basic job info
    job_reference = db.Column(db.String(100), unique=True)
    job_name = db.Column(db.String(200))
    type = db.Column(db.String(100), nullable=False)
    stage = db.Column(db.String(50), nullable=False, default='Lead')
    priority = db.Column(db.String(20), default='Medium')

    # Pricing
    quote_price = db.Column(db.Numeric(10, 2))
    agreed_price = db.Column(db.Numeric(10, 2))
    deposit_amount = db.Column(db.Numeric(10, 2))

    # Dates
    delivery_date = db.Column(db.DateTime)
    measure_date = db.Column(db.DateTime)
    completion_date = db.Column(db.DateTime)
    deposit_due_date = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Additional info
    installation_address = db.Column(db.Text)
    notes = db.Column(db.Text)

    # Team assignments - using strings for now to avoid foreign key issues
    salesperson_name = db.Column(db.String(100))
    assigned_team_name = db.Column(db.String(100))
    primary_fitter_name = db.Column(db.String(100))

    # Additional fields for the new job system
    assigned_team_id = db.Column(db.Integer, db.ForeignKey('teams.id'), nullable=True)
    primary_fitter_id = db.Column(db.Integer, db.ForeignKey('fitters.id'), nullable=True)
    salesperson_id = db.Column(db.Integer, db.ForeignKey('salespeople.id'), nullable=True)
    
    # Tags as simple string (comma-separated)
    tags = db.Column(db.Text)
    
    # Boolean flags
    has_counting_sheet = db.Column(db.Boolean, default=False)
    has_schedule = db.Column(db.Boolean, default=False)
    has_invoice = db.Column(db.Boolean, default=False)

    # Links
    quote_id = db.Column(db.Integer, db.ForeignKey('quotations.id'), nullable=True)

    # Relationships
    customer = db.relationship("Customer", back_populates="jobs")
    quotation = db.relationship("Quotation", foreign_keys=[quote_id], back_populates="job", uselist=False)
    assigned_team = db.relationship("Team", foreign_keys=[assigned_team_id])
    primary_fitter = db.relationship("Fitter", foreign_keys=[primary_fitter_id])
    salesperson = db.relationship("Salesperson", foreign_keys=[salesperson_id])
    
    # Other relationships (create these models as needed)
    documents = db.relationship("JobDocument", back_populates="job", lazy=True, cascade="all, delete-orphan")
    checklists = db.relationship("JobChecklist", back_populates="job", lazy=True, cascade="all, delete-orphan")
    schedule_items = db.relationship("ScheduleItem", back_populates="job", lazy=True, cascade="all, delete-orphan")
    rooms = db.relationship("Room", back_populates="job", lazy=True, cascade="all, delete-orphan")
    form_links = db.relationship("JobFormLink", back_populates="job", lazy=True, cascade="all, delete-orphan")
    job_notes = db.relationship("JobNote", back_populates="job", lazy=True, cascade="all, delete-orphan")
    invoices = db.relationship("Invoice", back_populates="job", lazy=True, cascade="all, delete-orphan")

    def __repr__(self):
        return f'<Job {self.job_reference or self.id}: {self.job_name or self.type}>'


# Keep all your other models exactly as they are, just change the first line:
# from app import db  # OLD
# to:
# from database import db  # NEW

class Team(db.Model):
    __tablename__ = 'teams'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    specialty = db.Column(db.String(100), nullable=True)
    active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    members = db.relationship('Fitter', back_populates='team', lazy=True)


class Fitter(db.Model):
    __tablename__ = 'fitters'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    team_id = db.Column(db.Integer, db.ForeignKey('teams.id'), nullable=True)
    skills = db.Column(db.Text, nullable=True)
    active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    team = db.relationship('Team', back_populates='members')


class Salesperson(db.Model):
    __tablename__ = 'salespeople'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    email = db.Column(db.String(120), nullable=True)
    phone = db.Column(db.String(20), nullable=True)
    active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class JobDocument(db.Model):
    __tablename__ = 'job_documents'

    id = db.Column(db.Integer, primary_key=True)
    job_id = db.Column(db.Integer, db.ForeignKey('jobs.id'), nullable=False)
    filename = db.Column(db.String(255), nullable=False)
    original_filename = db.Column(db.String(255), nullable=False)
    file_path = db.Column(db.String(500), nullable=False)
    file_size = db.Column(db.Integer, nullable=True)
    mime_type = db.Column(db.String(100), nullable=True)
    category = db.Column(db.String(50), nullable=True)
    uploaded_by = db.Column(db.String(200), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    job = db.relationship("Job", back_populates="documents")


class JobChecklist(db.Model):
    __tablename__ = 'job_checklists'

    id = db.Column(db.Integer, primary_key=True)
    job_id = db.Column(db.Integer, db.ForeignKey('jobs.id'), nullable=False)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(20), default='Not Started')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    job = db.relationship("Job", back_populates="checklists")
    items = db.relationship('ChecklistItem', back_populates='checklist', lazy=True, cascade='all, delete-orphan')


class ChecklistItem(db.Model):
    __tablename__ = 'checklist_items'

    id = db.Column(db.Integer, primary_key=True)
    checklist_id = db.Column(db.Integer, db.ForeignKey('job_checklists.id'), nullable=False)
    text = db.Column(db.String(500), nullable=False)
    completed = db.Column(db.Boolean, default=False)
    completed_at = db.Column(db.DateTime, nullable=True)
    completed_by = db.Column(db.String(200), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    order_index = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    checklist = db.relationship('JobChecklist', back_populates='items')


class ScheduleItem(db.Model):
    __tablename__ = 'schedule_items'

    id = db.Column(db.Integer, primary_key=True)
    job_id = db.Column(db.Integer, db.ForeignKey('jobs.id'), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    start_date = db.Column(db.DateTime, nullable=False)
    end_date = db.Column(db.DateTime, nullable=True)
    all_day = db.Column(db.Boolean, default=False)
    status = db.Column(db.String(20), default='Scheduled')
    assigned_team_id = db.Column(db.Integer, db.ForeignKey('teams.id'), nullable=True)
    assigned_fitter_id = db.Column(db.Integer, db.ForeignKey('fitters.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    job = db.relationship("Job", back_populates="schedule_items")
    assigned_team = db.relationship("Team")
    assigned_fitter = db.relationship("Fitter")


class Room(db.Model):
    __tablename__ = 'rooms'

    id = db.Column(db.Integer, primary_key=True)
    job_id = db.Column(db.Integer, db.ForeignKey('jobs.id'), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    room_type = db.Column(db.String(50), nullable=False)
    measurements = db.Column(db.Text, nullable=True)
    notes = db.Column(db.Text, nullable=True)
    order_index = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    job = db.relationship("Job", back_populates="rooms")
    appliances = db.relationship('RoomAppliance', back_populates='room', lazy=True, cascade='all, delete-orphan')


class RoomAppliance(db.Model):
    __tablename__ = 'room_appliances'

    id = db.Column(db.Integer, primary_key=True)
    room_id = db.Column(db.Integer, db.ForeignKey('rooms.id'), nullable=False)
    appliance_type = db.Column(db.String(100), nullable=False)
    brand = db.Column(db.String(100), nullable=True)
    model = db.Column(db.String(100), nullable=True)
    specifications = db.Column(db.Text, nullable=True)
    installation_notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    room = db.relationship('Room', back_populates='appliances')


class JobFormLink(db.Model):
    __tablename__ = 'job_form_links'

    id = db.Column(db.Integer, primary_key=True)
    job_id = db.Column(db.Integer, db.ForeignKey('jobs.id'), nullable=False)
    form_submission_id = db.Column(db.Integer, db.ForeignKey('form_submissions.id'), nullable=False)
    linked_at = db.Column(db.DateTime, default=datetime.utcnow)
    linked_by = db.Column(db.String(200), nullable=True)

    job = db.relationship('Job', back_populates='form_links')
    form_submission = db.relationship('FormSubmission', back_populates='job_links')


class JobNote(db.Model):
    __tablename__ = 'job_notes'

    id = db.Column(db.Integer, primary_key=True)
    job_id = db.Column(db.Integer, db.ForeignKey('jobs.id'), nullable=False)
    content = db.Column(db.Text, nullable=False)
    note_type = db.Column(db.String(50), default='general')
    author = db.Column(db.String(200), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    job = db.relationship('Job', back_populates='job_notes')


class Quotation(db.Model):
    __tablename__ = 'quotations'

    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey('customers.id'), nullable=False)
    reference_number = db.Column(db.String(50), unique=True, nullable=True)
    total = db.Column(db.Numeric(10, 2), nullable=False)
    status = db.Column(db.String(20), default='Draft')
    valid_until = db.Column(db.Date, nullable=True)
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    customer = db.relationship("Customer", back_populates="quotations")
    items = db.relationship('QuotationItem', back_populates='quotation', lazy=True, cascade="all, delete-orphan")
    job = db.relationship("Job", back_populates="quotation", uselist=False)


class Invoice(db.Model):
    __tablename__ = 'invoices'

    id = db.Column(db.Integer, primary_key=True)
    job_id = db.Column(db.Integer, db.ForeignKey('jobs.id'), nullable=False)
    invoice_number = db.Column(db.String(50), unique=True, nullable=False)
    amount = db.Column(db.Numeric(10, 2), nullable=False)
    status = db.Column(db.String(20), default='Draft')
    due_date = db.Column(db.Date, nullable=True)
    paid_date = db.Column(db.Date, nullable=True)
    payment_method = db.Column(db.String(50), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    job = db.relationship("Job", back_populates="invoices")


class FormSubmission(db.Model):
    __tablename__ = 'form_submissions'

    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey('customers.id'), nullable=True)
    form_data = db.Column(db.Text, nullable=False)
    source = db.Column(db.String(100), nullable=True)
    submitted_at = db.Column(db.DateTime, default=datetime.utcnow)
    processed = db.Column(db.Boolean, default=False)
    processed_at = db.Column(db.DateTime, nullable=True)

    customer = db.relationship("Customer", back_populates="form_submissions")
    job_links = db.relationship('JobFormLink', back_populates='form_submission', lazy=True, cascade='all, delete-orphan')


class QuotationItem(db.Model):
    __tablename__ = 'quotation_items'

    id = db.Column(db.Integer, primary_key=True)
    quotation_id = db.Column(db.Integer, db.ForeignKey('quotations.id'), nullable=False)
    item = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=True)
    color = db.Column(db.String(50), nullable=True)
    amount = db.Column(db.Float, nullable=False)

    quotation = db.relationship('Quotation', back_populates='items')

    def __repr__(self):
        return f'<QuotationItem {self.item} (Quotation {self.quotation_id})>'


class CustomerFormData(db.Model):
    __tablename__ = 'customer_form_data'

    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey('customers.id'), nullable=False)
    form_data = db.Column(db.Text, nullable=False)
    token_used = db.Column(db.String(64), nullable=False)
    submitted_at = db.Column(db.DateTime, default=datetime.utcnow)

    customer = db.relationship("Customer", back_populates="form_data")

    def __repr__(self):
        return f'<CustomerFormData {self.id} for Customer {self.customer_id}>'