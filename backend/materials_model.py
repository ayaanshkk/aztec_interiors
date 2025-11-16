from sqlalchemy import Column, String, DateTime, Boolean, Text, ForeignKey, Numeric, Enum
from sqlalchemy.orm import relationship
from datetime import datetime
import uuid
import enum

# Import your Base from models.py
from models import Base

class MaterialStatus(enum.Enum):
    """Material order status options"""
    NOT_ORDERED = "not_ordered"
    ORDERED = "ordered"
    IN_TRANSIT = "in_transit"
    DELIVERED = "delivered"
    DELAYED = "delayed"

class MaterialOrder(Base):
    """
    Tracks material orders for customer projects
    Links to Customer, Project/Job, and User (who ordered)
    """
    __tablename__ = 'material_orders'
    
    # Primary Key
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    
    # Foreign Keys - Link to existing tables
    customer_id = Column(String(36), ForeignKey('customers.id'), nullable=False)
    job_id = Column(String(36), ForeignKey('jobs.id'), nullable=True)  # If you have jobs table
    project_id = Column(Integer, ForeignKey('projects.id'), nullable=True)  # If you have projects table
    ordered_by_user_id = Column(Integer, ForeignKey('users.id'), nullable=True)
    
    # Material Details
    material_description = Column(Text, nullable=False)  # e.g., "Kitchen cabinets - Oak finish"
    supplier_name = Column(String(255), nullable=True)  # e.g., "B&Q", "Howdens"
    supplier_reference = Column(String(100), nullable=True)  # Supplier's order/invoice number
    
    # Status & Dates
    status = Column(Enum(MaterialStatus), default=MaterialStatus.NOT_ORDERED, nullable=False)
    order_date = Column(DateTime, nullable=True)  # When materials were ordered
    expected_delivery_date = Column(DateTime, nullable=True)  # ETA from supplier
    actual_delivery_date = Column(DateTime, nullable=True)  # When actually delivered
    
    # Cost Information (optional but useful for managers)
    estimated_cost = Column(Numeric(10, 2), nullable=True)
    actual_cost = Column(Numeric(10, 2), nullable=True)
    
    # Additional Info
    notes = Column(Text, nullable=True)  # Any special instructions or issues
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    customer = relationship('Customer', backref='material_orders')
    job = relationship('Job', backref='material_orders', foreign_keys=[job_id])
    project = relationship('Project', backref='material_orders', foreign_keys=[project_id])
    ordered_by = relationship('User', backref='material_orders_placed')
    
    def __repr__(self):
        return f'<MaterialOrder {self.id} - Customer: {self.customer_id} - Status: {self.status.value}>'
    
    def to_dict(self):
        """Convert to dictionary for API responses"""
        return {
            'id': self.id,
            'customer_id': self.customer_id,
            'customer_name': self.customer.name if self.customer else None,
            'job_id': self.job_id,
            'project_id': self.project_id,
            'material_description': self.material_description,
            'supplier_name': self.supplier_name,
            'supplier_reference': self.supplier_reference,
            'status': self.status.value,
            'order_date': self.order_date.isoformat() if self.order_date else None,
            'expected_delivery_date': self.expected_delivery_date.isoformat() if self.expected_delivery_date else None,
            'actual_delivery_date': self.actual_delivery_date.isoformat() if self.actual_delivery_date else None,
            'estimated_cost': float(self.estimated_cost) if self.estimated_cost else None,
            'actual_cost': float(self.actual_cost) if self.actual_cost else None,
            'ordered_by': self.ordered_by.username if self.ordered_by else None,
            'notes': self.notes,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }
    
    @property
    def is_modification_safe(self):
        """
        Returns True if materials haven't been ordered yet
        This tells managers if customer modifications are still possible
        """
        return self.status == MaterialStatus.NOT_ORDERED
    
    @property
    def delivery_status_summary(self):
        """Quick summary for managers to check project timeline"""
        if self.status == MaterialStatus.NOT_ORDERED:
            return "Materials not yet ordered - modifications possible"
        elif self.status == MaterialStatus.ORDERED:
            eta = self.expected_delivery_date.strftime('%d %b %Y') if self.expected_delivery_date else "TBD"
            return f"Ordered - Expected delivery: {eta}"
        elif self.status == MaterialStatus.IN_TRANSIT:
            eta = self.expected_delivery_date.strftime('%d %b %Y') if self.expected_delivery_date else "TBD"
            return f"In transit - ETA: {eta}"
        elif self.status == MaterialStatus.DELIVERED:
            delivered = self.actual_delivery_date.strftime('%d %b %Y') if self.actual_delivery_date else "Unknown"
            return f"Delivered on {delivered}"
        elif self.status == MaterialStatus.DELAYED:
            return "⚠️ DELAYED - Check with supplier"
        return "Unknown status"


class MaterialChangeLog(Base):
    """
    Audit trail for material order changes
    Useful for tracking who made changes and when
    """
    __tablename__ = 'material_change_logs'
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    material_order_id = Column(String(36), ForeignKey('material_orders.id'), nullable=False)
    changed_by_user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    
    change_type = Column(String(50), nullable=False)  # e.g., "status_change", "date_update"
    old_value = Column(Text, nullable=True)
    new_value = Column(Text, nullable=True)
    change_description = Column(Text, nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    material_order = relationship('MaterialOrder', backref='change_logs')
    changed_by = relationship('User', backref='material_changes_made')
    
    def __repr__(self):
        return f'<MaterialChangeLog {self.id} - Order: {self.material_order_id}>'
    
    def to_dict(self):
        return {
            'id': self.id,
            'material_order_id': self.material_order_id,
            'changed_by': self.changed_by.username if self.changed_by else None,
            'change_type': self.change_type,
            'old_value': self.old_value,
            'new_value': self.new_value,
            'change_description': self.change_description,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


# ============================================
# SQL MIGRATION SCRIPT
# Run this to create the tables in your database
# ============================================

SQL_MIGRATION = """
-- Create material_orders table
CREATE TABLE material_orders (
    id VARCHAR(36) PRIMARY KEY,
    customer_id VARCHAR(36) NOT NULL,
    job_id VARCHAR(36),
    project_id INT,
    ordered_by_user_id INT,
    material_description TEXT NOT NULL,
    supplier_name VARCHAR(255),
    supplier_reference VARCHAR(100),
    status ENUM('not_ordered', 'ordered', 'in_transit', 'delivered', 'delayed') DEFAULT 'not_ordered' NOT NULL,
    order_date DATETIME,
    expected_delivery_date DATETIME,
    actual_delivery_date DATETIME,
    estimated_cost DECIMAL(10, 2),
    actual_cost DECIMAL(10, 2),
    notes TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    
    FOREIGN KEY (customer_id) REFERENCES customers(id) ON DELETE CASCADE,
    FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE SET NULL,
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE SET NULL,
    FOREIGN KEY (ordered_by_user_id) REFERENCES users(id) ON DELETE SET NULL,
    
    INDEX idx_customer (customer_id),
    INDEX idx_status (status),
    INDEX idx_order_date (order_date),
    INDEX idx_delivery_date (expected_delivery_date)
);

-- Create material_change_logs table
CREATE TABLE material_change_logs (
    id VARCHAR(36) PRIMARY KEY,
    material_order_id VARCHAR(36) NOT NULL,
    changed_by_user_id INT NOT NULL,
    change_type VARCHAR(50) NOT NULL,
    old_value TEXT,
    new_value TEXT,
    change_description TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    
    FOREIGN KEY (material_order_id) REFERENCES material_orders(id) ON DELETE CASCADE,
    FOREIGN KEY (changed_by_user_id) REFERENCES users(id) ON DELETE CASCADE,
    
    INDEX idx_material_order (material_order_id),
    INDEX idx_created_at (created_at)
);
"""

if __name__ == "__main__":
    print("Material Tracking Models Defined!")
    print("\nNext steps:")
    print("1. Add these models to your models.py file")
    print("2. Run the SQL migration script to create tables")
    print("3. Implement the API routes (see materials_routes.py)")
    print("4. Create the frontend UI components")