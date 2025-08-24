# init_sample_data.py - Script to create sample data
from app import app
from database import db
from models import Customer, Team, Fitter, Salesperson

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

if __name__ == '__main__':
    create_sample_data()