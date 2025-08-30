# models.py - Updated to import from database.py instead of app.py
import uuid
from database import db  # Import from the new database.py file
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
import jwt
import secrets

class User(db.Model):
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    
    # Profile information
    first_name = db.Column(db.String(50), nullable=False)
    last_name = db.Column(db.String(50), nullable=False)
    phone = db.Column(db.String(20))
    
    # Role and permissions
    role = db.Column(db.String(20), default='user')  # admin, manager, user
    department = db.Column(db.String(50))
    
    # Account status
    is_active = db.Column(db.Boolean, default=True)
    is_verified = db.Column(db.Boolean, default=False)
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_login = db.Column(db.DateTime)
    
    # Password reset
    reset_token = db.Column(db.String(100))
    reset_token_expires = db.Column(db.DateTime)
    
    # Email verification
    verification_token = db.Column(db.String(100))
    
    def __repr__(self):
        return f'<User {self.email}>'
    
    def set_password(self, password):
        """Hash and set password"""
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        """Check if provided password matches hash"""
        return check_password_hash(self.password_hash, password)
    
    def get_full_name(self):
        """Get user's full name"""
        return f"{self.first_name} {self.last_name}"
    
    def generate_reset_token(self):
        """Generate password reset token"""
        self.reset_token = secrets.token_urlsafe(32)
        self.reset_token_expires = datetime.utcnow() + timedelta(hours=1)
        return self.reset_token
    
    def generate_verification_token(self):
        """Generate email verification token"""
        self.verification_token = secrets.token_urlsafe(32)
        return self.verification_token
    
    def generate_jwt_token(self, secret_key):
        """Generate JWT token for authentication"""
        payload = {
            'user_id': self.id,
            'email': self.email,
            'role': self.role,
            'exp': datetime.utcnow() + timedelta(days=7),  # Token expires in 7 days
            'iat': datetime.utcnow()
        }
        return jwt.encode(payload, secret_key, algorithm='HS256')
    
    @staticmethod
    def verify_jwt_token(token, secret_key):
        """Verify JWT token and return user"""
        try:
            payload = jwt.decode(token, secret_key, algorithms=['HS256'])
            user = User.query.get(payload['user_id'])
            return user if user and user.is_active else None
        except jwt.ExpiredSignatureError:
            return None
        except jwt.InvalidTokenError:
            return None
    
    def to_dict(self):
        """Convert user to dictionary for JSON response"""
        return {
            'id': self.id,
            'email': self.email,
            'first_name': self.first_name,
            'last_name': self.last_name,
            'full_name': self.get_full_name(),
            'phone': self.phone,
            'role': self.role,
            'department': self.department,
            'is_active': self.is_active,
            'is_verified': self.is_verified,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'last_login': self.last_login.isoformat() if self.last_login else None
        }


class LoginAttempt(db.Model):
    __tablename__ = 'login_attempts'
    
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), nullable=False, index=True)
    ip_address = db.Column(db.String(45), nullable=False)
    success = db.Column(db.Boolean, default=False)
    attempted_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f'<LoginAttempt {self.email} - {"Success" if self.success else "Failed"}>'


class Session(db.Model):
    __tablename__ = 'user_sessions'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    session_token = db.Column(db.String(255), unique=True, nullable=False)
    ip_address = db.Column(db.String(45))
    user_agent = db.Column(db.Text)
    expires_at = db.Column(db.DateTime, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    user = db.relationship('User', backref='sessions')
    
    def is_expired(self):
        return datetime.utcnow() > self.expires_at
    

class Customer(db.Model):
    __tablename__ = 'customers'

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    date_of_measure = db.Column(db.Date)
    name = db.Column(db.String(200), nullable=False)
    address = db.Column(db.Text)
    postcode = db.Column(db.String(20))
    phone = db.Column(db.String(50))
    email = db.Column(db.String(200))
    contact_made = db.Column(db.Enum('Yes', 'No', 'Unknown', name='contact_made_enum'), default='Unknown')
    preferred_contact_method = db.Column(db.Enum('Phone', 'Email', 'WhatsApp', name='preferred_contact_enum'))
    marketing_opt_in = db.Column(db.Boolean, default=False)
    notes = db.Column(db.Text)
    
    # Audit fields
    created_by = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_by = db.Column(db.String(200))
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Status field for backward compatibility
    status = db.Column(db.String(50), default='Active')

    # Relationships
    jobs = db.relationship("Job", back_populates="customer", lazy=True)
    quotations = db.relationship("Quotation", back_populates="customer", lazy=True, cascade="all, delete-orphan")
    form_data = db.relationship("CustomerFormData", back_populates="customer", lazy=True, cascade="all, delete-orphan")
    form_submissions = db.relationship("FormSubmission", back_populates="customer", lazy=True)

    def extract_postcode_from_address(self):
        """Extract postcode from address using simple pattern matching"""
        if not self.address:
            return None
        
        import re
        # UK postcode pattern (basic)
        postcode_pattern = r'\b[A-Z]{1,2}[0-9][A-Z0-9]? ?[0-9][A-Z]{2}\b'
        match = re.search(postcode_pattern, self.address.upper())
        return match.group(0) if match else None

    def save(self):
        """Save customer and auto-extract postcode if not provided"""
        if not self.postcode and self.address:
            self.postcode = self.extract_postcode_from_address()
        db.session.add(self)
        db.session.commit()

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
    # ADD THIS LINE - the missing relationship that ProductQuoteItem is looking for
    product_items = db.relationship('ProductQuoteItem', back_populates='quotation', lazy=True, cascade="all, delete-orphan")
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
    
class ApplianceCategory(db.Model):
    __tablename__ = 'appliance_categories'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    description = db.Column(db.Text)
    active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    products = db.relationship('Product', back_populates='category', lazy=True)
    
    def __repr__(self):
        return f'<ApplianceCategory {self.name}>'


class Brand(db.Model):
    __tablename__ = 'brands'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    logo_url = db.Column(db.String(255))
    website = db.Column(db.String(255))
    active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    products = db.relationship('Product', back_populates='brand', lazy=True)
    
    def __repr__(self):
        return f'<Brand {self.name}>'


class Product(db.Model):
    __tablename__ = 'products'
    
    id = db.Column(db.Integer, primary_key=True)
    brand_id = db.Column(db.Integer, db.ForeignKey('brands.id'), nullable=False)
    category_id = db.Column(db.Integer, db.ForeignKey('appliance_categories.id'), nullable=False)
    
    # Product details
    model_code = db.Column(db.String(100), nullable=False, unique=True)
    series = db.Column(db.String(100))
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    
    # Pricing
    base_price = db.Column(db.Numeric(10, 2))
    low_tier_price = db.Column(db.Numeric(10, 2))
    mid_tier_price = db.Column(db.Numeric(10, 2))
    high_tier_price = db.Column(db.Numeric(10, 2))
    
    # Physical attributes
    dimensions = db.Column(db.Text)  # JSON string: {"width": 60, "height": 85, "depth": 60}
    weight = db.Column(db.Numeric(8, 2))
    color_options = db.Column(db.Text)  # JSON array of available colors
    
    # Additional fields
    pack_name = db.Column(db.String(200))  # For bundled products
    notes = db.Column(db.Text)
    energy_rating = db.Column(db.String(10))
    warranty_years = db.Column(db.Integer)
    
    # Status
    active = db.Column(db.Boolean, default=True)
    in_stock = db.Column(db.Boolean, default=True)
    lead_time_weeks = db.Column(db.Integer)
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    brand = db.relationship('Brand', back_populates='products')
    category = db.relationship('ApplianceCategory', back_populates='products')
    quote_items = db.relationship('ProductQuoteItem', back_populates='product', lazy=True)
    
    def __repr__(self):
        return f'<Product {self.brand.name if self.brand else "Unknown"} {self.model_code}>'
    
    def get_price_for_tier(self, tier='mid'):
        """Get price based on tier (low/mid/high)"""
        tier_map = {
            'low': self.low_tier_price or self.base_price,
            'mid': self.mid_tier_price or self.base_price,
            'high': self.high_tier_price or self.base_price
        }
        return tier_map.get(tier.lower(), self.base_price)
    
    def get_dimensions_dict(self):
        """Parse dimensions JSON string"""
        if self.dimensions:
            try:
                import json
                return json.loads(self.dimensions)
            except:
                return {}
        return {}
    
    def get_color_options_list(self):
        """Parse color options JSON string"""
        if self.color_options:
            try:
                import json
                return json.loads(self.color_options)
            except:
                return []
        return []


class ProductQuoteItem(db.Model):
    __tablename__ = 'product_quote_items'
    
    id = db.Column(db.Integer, primary_key=True)
    quotation_id = db.Column(db.Integer, db.ForeignKey('quotations.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)
    
    # Quote-specific details
    quantity = db.Column(db.Integer, default=1)
    quoted_price = db.Column(db.Numeric(10, 2), nullable=False)  # Can override product price
    tier_used = db.Column(db.String(10))  # low/mid/high
    selected_color = db.Column(db.String(50))
    custom_notes = db.Column(db.Text)
    
    # Line totals
    line_total = db.Column(db.Numeric(10, 2))
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    quotation = db.relationship('Quotation', back_populates='product_items')
    product = db.relationship('Product', back_populates='quote_items')
    
    def __repr__(self):
        return f'<ProductQuoteItem {self.product.model_code if self.product else "Unknown"} x{self.quantity}>'
    
    def calculate_line_total(self):
        """Calculate and update line total"""
        self.line_total = self.quoted_price * self.quantity
        return self.line_total


class DataImport(db.Model):
    __tablename__ = 'data_imports'
    
    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(255), nullable=False)
    import_type = db.Column(db.String(50), nullable=False)  # 'appliance_matrix', 'kbb_pricelist'
    status = db.Column(db.String(20), default='processing')  # processing, completed, failed
    records_processed = db.Column(db.Integer, default=0)
    records_failed = db.Column(db.Integer, default=0)
    error_log = db.Column(db.Text)
    imported_by = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    completed_at = db.Column(db.DateTime)
    
    def __repr__(self):
        return f'<DataImport {self.filename} ({self.status})>'