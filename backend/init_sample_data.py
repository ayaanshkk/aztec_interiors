# migration_script.py - Database migration to update Customer model
import uuid
from datetime import datetime
from app import app
from database import db
from models import Customer, Fitter, Salesperson, Team
from flask import Flask
import os

def migrate_customer_table():
    """
    Migration script to update existing Customer table to new schema.
    Run this script to migrate your existing data.
    """
    
    # Create Flask app context
    app = Flask(__name__)
    basedir = os.path.abspath(os.path.dirname(__file__))
    app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{os.path.join(basedir, "database.db")}'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    
    db.init_app(app)
    
    with app.app_context():
        try:
            # Add new columns to existing table
            # Note: You might need to run these SQL commands directly depending on your database
            
            print("Starting Customer table migration...")
            
            # Add new columns (adjust SQL syntax based on your database - PostgreSQL, MySQL, SQLite)
            migration_sql = """
            -- Add new columns
            ALTER TABLE customers ADD COLUMN IF NOT EXISTS date_of_measure DATE;
            ALTER TABLE customers ADD COLUMN IF NOT EXISTS postcode VARCHAR(20);
            ALTER TABLE customers ADD COLUMN IF NOT EXISTS contact_made VARCHAR(20) DEFAULT 'Unknown';
            ALTER TABLE customers ADD COLUMN IF NOT EXISTS preferred_contact_method VARCHAR(20);
            ALTER TABLE customers ADD COLUMN IF NOT EXISTS marketing_opt_in BOOLEAN DEFAULT FALSE;
            ALTER TABLE customers ADD COLUMN IF NOT EXISTS notes TEXT;
            ALTER TABLE customers ADD COLUMN IF NOT EXISTS created_by VARCHAR(200);
            ALTER TABLE customers ADD COLUMN IF NOT EXISTS updated_by VARCHAR(200);
            ALTER TABLE customers ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP;
            
            -- Update ID column to use UUIDs for new records (existing integer IDs will remain)
            -- You might want to create a new UUID column and gradually migrate
            ALTER TABLE customers ADD COLUMN IF NOT EXISTS uuid_id VARCHAR(36);
            """
            
            # Execute the migration
            db.engine.execute(migration_sql)
            
            # Update existing records with UUIDs and default values
            customers = Customer.query.all()
            for customer in customers:
                if not hasattr(customer, 'uuid_id') or not customer.uuid_id:
                    customer.uuid_id = str(uuid.uuid4())
                if not hasattr(customer, 'created_by') or not customer.created_by:
                    customer.created_by = 'Migration'
                if not hasattr(customer, 'contact_made') or not customer.contact_made:
                    customer.contact_made = 'Unknown'
                
                # Try to extract postcode from existing address
                if customer.address and not (hasattr(customer, 'postcode') and customer.postcode):
                    import re
                    postcode_pattern = r'\b[A-Z]{1,2}[0-9][A-Z0-9]? ?[0-9][A-Z]{2}\b'
                    match = re.search(postcode_pattern, customer.address.upper())
                    if match:
                        customer.postcode = match.group(0)
            
            db.session.commit()
            print("Migration completed successfully!")
            
            # Print summary
            total_customers = Customer.query.count()
            print(f"Total customers in database: {total_customers}")
            
        except Exception as e:
            print(f"Migration failed: {e}")
            db.session.rollback()

def create_form_token_table():
    """
    Create a new table to store form tokens for existing customers
    """
    create_table_sql = """
    CREATE TABLE IF NOT EXISTS form_tokens (
        id INTEGER PRIMARY KEY AUTO_INCREMENT,
        customer_id VARCHAR(36) NOT NULL,
        token VARCHAR(255) NOT NULL UNIQUE,
        form_type VARCHAR(50) NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        used_at TIMESTAMP NULL,
        expires_at TIMESTAMP NULL,
        is_active BOOLEAN DEFAULT TRUE,
        FOREIGN KEY (customer_id) REFERENCES customers(id)
    );
    
    CREATE INDEX idx_form_tokens_token ON form_tokens(token);
    CREATE INDEX idx_form_tokens_customer_id ON form_tokens(customer_id);
    """
    
    try:
        db.engine.execute(create_table_sql)
        print("Form tokens table created successfully!")
    except Exception as e:
        print(f"Failed to create form tokens table: {e}")

def create_sample_data():
    """Create sample data for testing"""
    with app.app_context():
        # Create tables
        db.create_all()
        
        # Check if data already exists
        if Customer.query.first():
            print("Sample data already exists")
            return
        
        # Create sample customers
        customers = [
            Customer(
                name="John Smith",
                email="john.smith@email.com",
                phone="01234 567890",
                address="123 Main Street, London, SW1A 1AA"
            ),
            Customer(
                name="Sarah Johnson",
                email="sarah.johnson@email.com",
                phone="01234 567891",
                address="456 Oak Avenue, Manchester, M1 1AA"
            ),
            Customer(
                name="Mike Wilson",
                email="mike.wilson@email.com",
                phone="01234 567892",
                address="789 Pine Road, Birmingham, B1 1AA"
            )
        ]
        
        for customer in customers:
            db.session.add(customer)
        
        # Create sample teams
        teams = [
            Team(name="Kitchen Team A", specialty="Kitchen", active=True),
            Team(name="Bedroom Team B", specialty="Bedroom", active=True),
            Team(name="General Fitting Team", specialty="General", active=True)
        ]
        
        for team in teams:
            db.session.add(team)
        
        db.session.flush()  # Get team IDs
        
        # Create sample fitters
        fitters = [
            Fitter(name="Dave Matthews", team_id=teams[0].id, active=True),
            Fitter(name="Tom Harris", team_id=teams[1].id, active=True),
            Fitter(name="Steve Brown", team_id=teams[2].id, active=True),
            Fitter(name="James Wilson", team_id=teams[0].id, active=True)
        ]
        
        for fitter in fitters:
            db.session.add(fitter)
        
        # Create sample salespeople
        salespeople = [
            Salesperson(name="John Smith", email="john@company.com", active=True),
            Salesperson(name="Sarah Johnson", email="sarah@company.com", active=True),
            Salesperson(name="Mike Wilson", email="mike@company.com", active=True)
        ]
        
        for person in salespeople:
            db.session.add(person)
        
        # Commit all changes
        db.session.commit()
        print("Sample data created successfully!")
        print(f"Created {len(customers)} customers")
        print(f"Created {len(teams)} teams")
        print(f"Created {len(fitters)} fitters")
        print(f"Created {len(salespeople)} salespeople")

if __name__ == "__main__":
    print("Customer Database Migration Tool")
    print("=" * 40)
    
    choice = input("Choose migration option:\n1. Migrate Customer table\n2. Create Form Tokens table\n3. Both\nEnter choice (1-3): ")
    
    if choice in ['1', '3']:
        migrate_customer_table()
    
    if choice in ['2', '3']:
        create_form_token_table()
    
    print("\nMigration completed!")
    print("\nNext steps:")
    print("1. Update your models.py with the new Customer model")
    print("2. Update your routes with the new customer endpoints")
    print("3. Replace your frontend components with the new versions")
    print("4. Test the new workflow: Create customer -> Generate form link -> Submit form")
    create_sample_data()