from flask import Blueprint, request, jsonify, current_app, send_file
from ..models import Customer, CustomerFormData, User, ApprovalNotification
import secrets
import string
import json
from datetime import datetime, timedelta
from io import BytesIO
from fpdf import FPDF
from ..db import SessionLocal # Required for database access
from functools import wraps
from sqlalchemy.orm import joinedload 
from .notification_routes import create_activity_notification


form_bp = Blueprint("form", __name__)

# In-memory storage for form tokens (for production use Redis/DB)
form_tokens = {}

def generate_secure_token(length=32):
    alphabet = string.ascii_letters + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(length))

# Token authentication decorator (Relies on User.verify_jwt_token which handles its session)
def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        # Allow OPTIONS requests without authentication
        if request.method == 'OPTIONS':
            return f(*args, **kwargs)
        
        token = None
        
        if 'Authorization' in request.headers:
            auth_header = request.headers['Authorization']
            try:
                token = auth_header.split(" ")[1]
            except IndexError:
                return jsonify({'error': 'Invalid token format'}), 401
            
        if not token:
            return jsonify({'error': 'Token is missing'}), 401
        
        # --- FIX: Session must be active for verify_jwt_token if it queries the DB ---
        session = SessionLocal() 
        try:
            # We assume User.verify_jwt_token needs a session or relies on Model.query being replaced
            # Note: The logic in the full auth_routes handles session passing to User.verify_jwt_token.
            # If User.verify_jwt_token is a static method that needs a session, the logic inside 
            # auth_routes.py is the primary fix. For this helper, we ensure a session exists around it.
            current_user = User.verify_jwt_token(token, current_app.config['SECRET_KEY'], session=session)
            if not current_user:
                return jsonify({'error': 'Token is invalid or expired'}), 401
            
            request.current_user = current_user
            
        except Exception as e:
            session.rollback()
            return jsonify({'error': 'Token verification failed'}), 401
        finally:
            session.close()
        # --------------------------------------------------------------------------
        
        return f(*args, **kwargs)
    
    return decorated

# Manager-only decorator
def manager_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not hasattr(request, 'current_user'):
            return jsonify({'error': 'Authentication required'}), 401
        
        if request.current_user.role not in ['Manager', 'HR']:
            return jsonify({'error': 'Manager or HR access required'}), 403
        
        return f(*args, **kwargs)
    
    return decorated

# ------------------------------------------------------------------------
# NEW CUSTOMER ROUTE: Fetch List of Customers for the Dropdown
# ------------------------------------------------------------------------

@form_bp.route('/customers', methods=['GET', 'OPTIONS'])
@token_required
def get_all_customers():
    """
    Retrieves a list of all customers, typically for selection in a dropdown.
    """
    if request.method == 'OPTIONS':
        return jsonify({}), 200

    session = SessionLocal() # Start session for read operation
    try:
        # Fetch all customers (Already correct)
        customers = session.query(Customer).all()
        
        # Manually convert to the required simple JSON format for the frontend dropdown
        customer_list = [
            {
                'id': c.id,
                'name': c.name,
                'address': c.address,
                'phone': c.phone,
                'email': c.email
            }
            for c in customers
        ]

        return jsonify(customer_list), 200

    except Exception as e:
        session.rollback()
        current_app.logger.exception(f"Error fetching all customers: {e}")
        return jsonify({'error': 'Failed to fetch customer list'}), 500
    finally:
        session.close() # Close session

# ------------------------------------------------------------------------
# APPROVAL SYSTEM ROUTES
# ------------------------------------------------------------------------

@form_bp.route('/approvals/pending', methods=['GET', 'OPTIONS'])
@token_required
@manager_required
def get_pending_approvals():
    """Get all pending approvals (for managers) (FIXED QUERIES)"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    session = SessionLocal() # 👈 START SESSION FOR READ
    try:
        # FIXED QUERY: Use session.query(Model)
        pending_submissions = session.query(CustomerFormData).filter_by(
            approval_status='pending'
        ).order_by(CustomerFormData.submitted_at.desc()).all()
        
        all_pending = []
        
        for submission in pending_submissions:
            form_data = json.loads(submission.form_data)
            
            # FIXED QUERY: Use session.get() for related models
            creator = session.get(User, submission.created_by) if hasattr(submission, 'created_by') and submission.created_by else None
            customer = session.get(Customer, submission.customer_id)
            
            doc_type = 'form'
            if form_data.get('is_invoice'):
                doc_type = 'invoice'
            elif form_data.get('is_receipt'):
                doc_type = 'receipt'
            elif form_data.get('form_type') in ['kitchen', 'bedroom']:
                doc_type = 'checklist'
            
            pending_item = {
                'id': submission.id,
                'type': doc_type,
                'invoice_number': form_data.get('invoiceNumber'),
                'receipt_number': form_data.get('receiptType'),
                'customer_name': customer.name if customer else form_data.get('customerName', 'N/A'),
                'total_amount': form_data.get('totalAmount') or form_data.get('paidAmount'),
                'created_by': creator.full_name if creator else 'Unknown',
                'created_at': submission.submitted_at.isoformat()
            }
            all_pending.append(pending_item)
        
        return jsonify({'success': True, 'data': all_pending}), 200
        
    except Exception as e:
        session.rollback()
        current_app.logger.exception(f"Error fetching pending approvals: {e}")
        return jsonify({'error': 'Failed to fetch pending approvals'}), 500
    finally:
        session.close() # 👈 CLOSE SESSION

@form_bp.route('/approvals/approve', methods=['POST', 'OPTIONS'])
@token_required
@manager_required
def approve_document():
    """Approve a document"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    session = SessionLocal() # 👈 Start session
    try:
        data = request.get_json()
        document_id = data.get('documentId')
        
        if not document_id:
            return jsonify({'error': 'Missing document ID'}), 400
        
        submission = session.get(CustomerFormData, document_id)
        if not submission:
            return jsonify({'error': 'Document not found'}), 404
        
        submission.approval_status = 'approved'
        submission.approved_by = request.current_user.id
        submission.approval_date = datetime.utcnow()
        
        form_data = json.loads(submission.form_data)
        doc_type = 'document'
        if form_data.get('is_invoice'):
            doc_type = 'invoice'
        elif form_data.get('is_receipt'):
            doc_type = 'receipt'
        
        current_app.logger.info(
            f"Document {document_id} ({doc_type}) approved by manager {request.current_user.id}"
        )
        
        session.commit() # 👈 Commit transaction
        
        return jsonify({'success': True, 'message': 'Document approved successfully'}), 200
        
    except Exception as e:
        session.rollback() # 👈 Rollback on error
        current_app.logger.exception(f"Error approving document: {e}")
        return jsonify({'error': 'Failed to approve document'}), 500
    finally:
        session.close() # 👈 Close session

@form_bp.route('/approvals/reject', methods=['POST', 'OPTIONS'])
@token_required
@manager_required
def reject_document():
    """Reject a document"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    session = SessionLocal() # 👈 Start session
    try:
        data = request.get_json()
        document_id = data.get('documentId')
        reason = data.get('reason', '')
        
        if not document_id:
            return jsonify({'error': 'Missing document ID'}), 400
        
        if not reason.strip():
            return jsonify({'error': 'Rejection reason is required'}), 400
        
        submission = session.get(CustomerFormData, document_id)
        if not submission:
            return jsonify({'error': 'Document not found'}), 404
        
        submission.approval_status = 'rejected'
        submission.approved_by = request.current_user.id
        submission.approval_date = datetime.utcnow()
        submission.rejection_reason = reason
        
        form_data = json.loads(submission.form_data)
        doc_type = 'document'
        if form_data.get('is_invoice'):
            doc_type = 'invoice'
        elif form_data.get('is_receipt'):
            doc_type = 'receipt'
        
        current_app.logger.info(
            f"Document {document_id} ({doc_type}) rejected by manager {request.current_user.id}. Reason: {reason}"
        )
        
        session.commit() # 👈 Commit transaction
        
        return jsonify({'success': True, 'message': 'Document rejected'}), 200
        
    except Exception as e:
        session.rollback() # 👈 Rollback on error
        current_app.logger.exception(f"Error rejecting document: {e}")
        return jsonify({'error': 'Failed to reject document'}), 500
    finally:
        session.close() # 👈 Close session

@form_bp.route('/approvals/status/<int:document_id>', methods=['GET', 'OPTIONS'])
@token_required
def get_approval_status(document_id):
    """Get approval status for a specific document (FIXED QUERIES)"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    session = SessionLocal() # 👈 START SESSION FOR READ
    try:
        # FIXED: Replaced Model.query.get() with session.get()
        submission = session.get(CustomerFormData, document_id) 
        if not submission:
            return jsonify({'error': 'Document not found'}), 404
        
        return jsonify({
            'approval_status': submission.approval_status,
            'rejection_reason': submission.rejection_reason,
            'approval_date': submission.approval_date.isoformat() if submission.approval_date else None
        }), 200
        
    except Exception as e:
        current_app.logger.exception(f"Error fetching approval status: {e}")
        return jsonify({'error': 'Failed to fetch approval status'}), 500
    finally:
        session.close() # 👈 CLOSE SESSION

# ------------------------------------------------------------------------
# ROUTE: INVOICE PDF DOWNLOAD (WITH APPROVAL CHECK)
# ------------------------------------------------------------------------

@form_bp.route('/invoices/download-pdf', methods=['POST', 'OPTIONS'])
@token_required
def download_invoice_pdf():
    """Generates a PDF invoice based on data from the frontend."""
    if request.method == 'OPTIONS':
        return jsonify({}), 200
        
    session = SessionLocal() # 👈 START SESSION FOR READ CHECK
    try:
        data = request.get_json(silent=True) or {}
        
        if not data:
            return jsonify({'error': 'Missing invoice data.'}), 400

        # Check approval status (read-only query)
        submission_id = data.get('submission_id')
        if submission_id:
            # FIXED: Replaced Model.query.get() with session.get()
            submission = session.get(CustomerFormData, submission_id) 
            if submission and submission.approval_status != 'approved':
                return jsonify({
                    'error': 'This invoice is not yet approved for download',
                    'status': submission.approval_status
                }), 403

        # ... (PDF generation logic remains the same) ...
        pdf = PDF('P', 'mm', 'A4')
        pdf.doc_title = 'Invoice'
        pdf.alias_nb_pages()
        pdf.add_page()
        pdf.set_auto_page_break(auto=True, margin=35) 
        pdf.set_font('Arial', '', 10)
        
        # ... (Rest of PDF generation code) ...

        HEADER_FILL = (230, 230, 230)
        LINE_COLOR = (0, 0, 0)
        col_width = 190 / 2
        line_height = 6
        
        # Invoice Number and Dates
        pdf.set_x(110)
        pdf.set_fill_color(*HEADER_FILL)
        pdf.set_font('Arial', 'B', 10)
        pdf.cell(40, line_height, 'INVOICE NO:', 1, 0, 'L', 1)
        pdf.set_font('Arial', '', 10)
        pdf.cell(40, line_height, data.get('invoiceNumber', 'N/A'), 1, 1, 'R', 0)
        
        pdf.set_x(110)
        pdf.set_font('Arial', 'B', 10)
        pdf.cell(40, line_height, 'DATE:', 1, 0, 'L', 1)
        pdf.set_font('Arial', '', 10)
        pdf.cell(40, line_height, data.get('invoiceDate', datetime.now().strftime('%Y-%m-%d')), 1, 1, 'R', 0)
        
        pdf.set_x(110)
        pdf.set_font('Arial', 'B', 10)
        pdf.cell(40, line_height, 'DUE DATE:', 1, 0, 'L', 1)
        pdf.set_font('Arial', 'B', 10)
        pdf.cell(40, line_height, data.get('dueDate', 'N/A'), 1, 1, 'R', 0)
        pdf.ln(5)
        
        # Customer Details
        pdf.set_font('Arial', 'B', 10)
        pdf.cell(col_width, line_height, 'BILL TO:', 'T', 1, 'L', 0)
        pdf.set_font('Arial', 'B', 12)
        pdf.cell(0, line_height, data.get('customerName', 'N/A'), 0, 1, 'L', 0)
        pdf.set_font('Arial', '', 10)
        pdf.multi_cell(col_width, line_height, data.get('customerAddress', 'N/A'), 0, 'L', 0)
        pdf.cell(0, line_height, data.get('customerPhone', 'N/A'), 0, 1, 'L', 0)
        pdf.ln(10)
        
        # Line Items Table
        header = ['QTY', 'DESCRIPTION', 'UNIT PRICE', 'AMOUNT']
        widths = [15, 105, 35, 35] 
        pdf.set_fill_color(*HEADER_FILL)
        pdf.set_font('Arial', 'B', 9)
        
        for i, h in enumerate(header):
            align = 'C' if i == 0 else ('R' if i >= 2 else 'L')
            pdf.cell(widths[i], 8, h, 1, 0, align, 1)
        pdf.ln()

        pdf.set_font('Arial', '', 9)
        for item in data.get('items', []):
            description = item.get('description', '')
            amount = item.get('amount', 0)
            x_start = pdf.get_x()
            y_start = pdf.get_y()
            pdf.set_xy(x_start + widths[0], y_start) 
            pdf.multi_cell(widths[1], 5, description, 0, 'L', False, dry_run=True) 
            row_h = pdf.get_y() - y_start
            row_h = max(5, row_h) 
            pdf.set_xy(x_start, y_start) 
            pdf.cell(widths[0], row_h, '1', 1, 0, 'C', 0)
            pdf.multi_cell(widths[1], row_h, description, 1, 'L', 0, False)
            pdf.set_xy(x_start + widths[0] + widths[1], y_start)
            pdf.cell(widths[2], row_h, '', 1, 0, 'R', 0)
            amount_str = f"£{amount:,.2f}"
            pdf.cell(widths[3], row_h, amount_str, 1, 1, 'R', 0)
        
        pdf.ln(5)

        # Totals
        totals_x_start = 105
        pdf.set_font('Arial', '', 10)
        pdf.set_x(totals_x_start)
        pdf.cell(50, line_height, 'Subtotal:', 0, 0, 'R')
        pdf.set_font('Arial', 'B', 10)
        pdf.cell(40, line_height, f"£{data.get('subTotal', 0):,.2f}", 0, 1, 'R')
        
        pdf.set_x(totals_x_start)
        pdf.set_font('Arial', '', 10)
        vat_label = f"VAT ({data.get('vatRate', 0)}%):"
        pdf.cell(50, line_height, vat_label, 0, 0, 'R')
        pdf.set_font('Arial', 'B', 10)
        pdf.cell(40, line_height, f"£{data.get('vatAmount', 0):,.2f}", 0, 1, 'R')
        
        pdf.set_x(totals_x_start)
        pdf.set_fill_color(*HEADER_FILL)
        pdf.set_draw_color(*LINE_COLOR)
        pdf.set_font('Arial', 'B', 12)
        pdf.cell(50, 8, 'TOTAL DUE:', 'T', 0, 'R', 1)
        pdf.cell(40, 8, f"£{data.get('totalAmount', 0):,.2f}", 'T', 1, 'R', 1)
        pdf.ln(10)
        
        # Bank Details
        Y_LIMIT = 297 - 35
        y_safe_start = Y_LIMIT - 30
        if pdf.get_y() > y_safe_start: 
              pdf.set_y(y_safe_start)
        pdf.ln(2) 
        pdf.set_font('Arial', 'B', 10)
        pdf.set_xy(10, pdf.get_y()) 
        pdf.multi_cell(col_width, 5, 'Payment by Bank Transfer:', 0, 'L')
        pdf.set_font('Arial', '', 10)
        pdf.set_xy(10, pdf.get_y()) 
        pdf.multi_cell(col_width, 5, 'Acc Name: Aztec Interiors Leicester LTD | Bank: HSBC\nSort Code: 40-28-06 | Acc No: 43820343', 0, 'L')
        pdf.set_font('Arial', 'I', 9)
        pdf.set_xy(10, pdf.get_y()) 
        pdf.multi_cell(0, 5, 'Please use your name and/or road name as reference.', 0, 'L')


        pdf_output = pdf.output(dest='S')
        pdf_file = BytesIO(pdf_output)
        customer_name = data.get('customerName', 'Customer').replace(' ', '_')
        filename = f"Invoice_{data.get('invoiceNumber', '0000')}_{customer_name}.pdf"
        
        return send_file(pdf_file, mimetype='application/pdf', as_attachment=True, download_name=filename)

    except Exception as e:
        session.rollback() # Rollback the session if needed (only if commit was attempted earlier)
        current_app.logger.exception(f"Invoice PDF generation failed: {e}")
        return jsonify({"error": f"Server failed to generate Invoice PDF: {str(e)}"}), 500
    finally:
        session.close() # 👈 CLOSE SESSION


# ------------------------------------------------------------------------
# ROUTE: INVOICE SAVE (WITH PENDING APPROVAL)
# ------------------------------------------------------------------------

@form_bp.route('/invoices/save', methods=['POST', 'OPTIONS'])
@token_required
def save_invoice():
    """Saves invoice data with pending approval status, notifies managers, and logs activity"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200

    session = SessionLocal()
    try:
        data = request.get_json(silent=True) or {}
        customer_id = data.get('customerId')
        
        if not customer_id:
            return jsonify({'error': 'Missing customer ID'}), 400
            
        customer = session.get(Customer, customer_id)
        if not customer:
            return jsonify({'error': 'Customer not found'}), 404
            
        data['form_type'] = f"invoice_{data.get('invoiceNumber', 'general')}"
        data['is_invoice'] = True

        customer_form_data = CustomerFormData(
            customer_id=customer_id,
            form_data=json.dumps(data),
            token_used=f"INVOICE-{data.get('invoiceNumber', 'N/A')}-{customer_id}-{datetime.utcnow().timestamp()}",
            submitted_at=datetime.utcnow(),
            approval_status='pending',
            created_by=request.current_user.id
        )
        
        session.add(customer_form_data)
        session.flush()
        
        # Create approval notifications for managers
        try:
            managers = session.query(User).filter(
                User.role.in_(['Manager', 'HR']),
                User.is_active == True
            ).all()
            
            for manager in managers:
                notification = ApprovalNotification(
                    user_id=manager.id,
                    document_type='invoice',
                    document_id=customer_form_data.id,
                    status='pending',
                    message=f'New invoice #{data.get("invoiceNumber", "N/A")} from {request.current_user.full_name} requires approval. Customer: {customer.name}, Amount: £{data.get("totalAmount", 0):,.2f}',
                    created_at=datetime.utcnow(),
                    is_read=False
                )
                session.add(notification)
            
        except Exception as e:
            current_app.logger.error(f"Error creating approval notifications: {e}")
        
        # 🔔 CREATE ACTIVITY NOTIFICATION (for general staff awareness)
        user_name = request.current_user.full_name if hasattr(request.current_user, 'full_name') else request.current_user.username
        
        notification_message = f"💰 New Invoice #{data.get('invoiceNumber', 'N/A')} created by {user_name} for {customer.name} - Amount: £{data.get('totalAmount', 0):,.2f} (Pending Approval)"
        
        create_activity_notification(
            session=session,
            message=notification_message,
            customer_id=customer_id,
            moved_by=user_name
        )
        
        session.commit()

        return jsonify({
            "success": True,
            "message": f"Invoice ({data.get('invoiceNumber', 'N/A')}) saved and sent for approval!",
            "form_submission_id": customer_form_data.id,
            "approval_status": "pending"
        }), 200

    except Exception as e:
        session.rollback()
        current_app.logger.exception(f"Error saving invoice: {e}")
        return jsonify({"error": f"Failed to save invoice: {str(e)}"}), 500
    finally:
        session.close()
    
# ------------------------------------------------------------------------
# ROUTE: RECEIPT PDF DOWNLOAD
# ------------------------------------------------------------------------

@form_bp.route('/receipts/download-pdf', methods=['POST', 'OPTIONS'])
def download_receipt_pdf():
    # ... (PDF generation logic remains the same) ...
    if request.method == 'OPTIONS':
        return jsonify({}), 200
        
    try:
        data = request.get_json(silent=True) or {}
        
        if not data:
            return jsonify({'error': 'Missing receipt data.'}), 400

        pdf = PDF('P', 'mm', 'A4')
        pdf.doc_title = 'Official Receipt'
        pdf.alias_nb_pages()
        pdf.add_page()
        pdf.set_auto_page_break(auto=True, margin=30) 
        
        # Colors for Gray Theme
        HEADER_FILL = (230, 230, 230)
        TOTAL_FILL = (200, 200, 200)

        pdf.set_font('Arial', '', 10)

        # --- 1. Customer and Date Details ---
        pdf.set_fill_color(*HEADER_FILL)
        pdf.set_draw_color(0, 0, 0)
        col_width = 190 / 2
        line_height = 7
        
        pdf.set_font('Arial', 'B', 12)
        pdf.cell(col_width, line_height, 'Customer Details', 'T', 0, 'L', 1)
        pdf.cell(col_width, line_height, 'Date', 'T', 1, 'R', 1)
        pdf.set_font('Arial', '', 10)
        
        # Row 1: Name and Date
        pdf.set_font('Arial', 'B', 10)
        pdf.cell(30, line_height, 'Name:', 0, 0, 'L')
        pdf.set_font('Arial', '', 10)
        pdf.cell(col_width - 30, line_height, data.get('customerName', 'N/A'), 0, 0, 'L')
        pdf.set_font('Arial', '', 10)
        pdf.cell(col_width, line_height, data.get('receiptDate', datetime.now().strftime('%d/%m/%Y')), 0, 1, 'R')
        
        # Row 2: Address
        pdf.set_font('Arial', 'B', 10)
        pdf.cell(30, line_height, 'Address:', 0, 0, 'L')
        pdf.set_font('Arial', '', 10)
        pdf.multi_cell(col_width - 30, line_height, data.get('customerAddress', 'N/A'), 0, 'L', 0)
        
        # Row 3: Phone
        y_after_address = pdf.get_y()
        pdf.set_font('Arial', 'B', 10)
        pdf.set_xy(10, y_after_address)
        pdf.cell(30, line_height, 'Phone:', 'B', 0, 'L')
        pdf.set_font('Arial', '', 10)
        pdf.cell(col_width - 30, line_height, data.get('customerPhone', 'N/A'), 'B', 1, 'L')
        pdf.ln(5)

        # --- 2. Payment Confirmation Message ---
        pdf.set_font('Arial', '', 11)
        pdf.multi_cell(0, 6, f"Confirmation of payment received by BACS for {data.get('paymentDescription', 'your Kitchen/Bedroom Cabinetry')}", 0, 'L')
        pdf.ln(5)

        # --- 3. Paid Amount (Highlight) ---
        pdf.set_fill_color(*TOTAL_FILL)
        pdf.set_font('Arial', 'B', 14)
        
        paid_amount_str = f"£{data.get('paidAmount', 0):,.2f}"

        pdf.cell(col_width, 10, 'Paid:', 1, 0, 'L', 1)
        pdf.set_font('Arial', 'B', 16)
        pdf.cell(col_width, 10, paid_amount_str, 1, 1, 'R', 1)
        pdf.ln(5)

        # --- 4. Summary Details ---
        pdf.set_font('Arial', 'B', 11)
        
        # Paid to Date
        paid_to_date_str = f"£{data.get('totalPaidToDate', 0):,.2f}"
        pdf.cell(col_width, 7, 'Paid to date:', 'T', 0, 'L')
        pdf.set_font('Arial', '', 11)
        pdf.cell(col_width, 7, paid_to_date_str, 'T', 1, 'R')

        # Balance to Pay
        balance_str = f"£{data.get('balanceToPay', 0):,.2f}"
        pdf.set_font('Arial', 'B', 12)
        pdf.cell(col_width, 8, 'Balance to Pay:', 'T', 0, 'L')
        pdf.set_font('Arial', 'B', 12)
        pdf.cell(col_width, 8, balance_str, 'T', 1, 'R')
        pdf.ln(10)

        # --- 5. Signature ---
        pdf.set_font('Arial', '', 11)
        pdf.cell(0, 5, 'Many Thanks', 0, 1, 'L')
        pdf.ln(5)
        pdf.set_font('Arial', 'I', 12)
        pdf.cell(0, 5, 'Shahida Macci', 0, 1, 'L')

        # --- 6. Return the PDF ---
        pdf_output = pdf.output(dest='S')
        pdf_file = BytesIO(pdf_output)

        customer_name = data.get('customerName', 'Customer').replace(' ', '_')
        date_str = data.get('receiptDate', datetime.now().strftime('%Y-%m-%d'))
        filename = f"Receipt_{data.get('receiptType', 'Payment').title()}_{customer_name}_{date_str}.pdf"
        
        return send_file(
            pdf_file,
            mimetype='application/pdf',
            as_attachment=True,
            download_name=filename
        )

    except Exception as e:
            current_app.logger.exception(f"Receipt PDF generation failed: {e}")
            return jsonify({"error": f"Server failed to generate Receipt PDF: {str(e)}"}), 500


# ------------------------------------------------------------------------
# ROUTE: RECEIPT SAVE (Saves Receipt Data as a Form Submission)
# ------------------------------------------------------------------------

@form_bp.route('/receipts/save', methods=['POST', 'OPTIONS'])
@token_required
def save_receipt():
    """Saves receipt data with pending approval status, notifies managers, and logs activity"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200

    session = SessionLocal()
    try:
        data = request.get_json(silent=True) or {}
        customer_id = data.get('customerId')
        
        if not customer_id:
            return jsonify({'error': 'Missing customer ID'}), 400
            
        customer = session.get(Customer, customer_id)
        if not customer:
            return jsonify({'error': 'Customer not found, cannot save receipt'}), 404
            
        data['form_type'] = f"receipt_{data.get('receiptType', 'general')}"
        data['is_receipt'] = True

        customer_form_data = CustomerFormData(
            customer_id=customer_id,
            form_data=json.dumps(data),
            token_used=f"RECEIPT-{data.get('receiptType', '').upper()}-{customer_id}-{datetime.utcnow().timestamp()}",
            submitted_at=datetime.utcnow(),
            approval_status='pending',
            created_by=request.current_user.id
        )
        
        session.add(customer_form_data)
        session.flush()
        
        # Create approval notifications for managers
        try:
            managers = session.query(User).filter(
                User.role.in_(['Manager', 'HR']),
                User.is_active == True
            ).all()
            
            for manager in managers:
                notification = ApprovalNotification(
                    user_id=manager.id,
                    document_type='receipt',
                    document_id=customer_form_data.id,
                    status='pending',
                    message=f'New receipt ({data.get("receiptType", "Payment")}) from {request.current_user.full_name} requires approval. Customer: {customer.name}, Amount: £{data.get("paidAmount", 0):,.2f}',
                    created_at=datetime.utcnow(),
                    is_read=False
                )
                session.add(notification)
            
        except Exception as e:
            current_app.logger.error(f"Error creating approval notifications: {e}")
        
        # 🔔 CREATE ACTIVITY NOTIFICATION (for general staff awareness)
        user_name = request.current_user.full_name if hasattr(request.current_user, 'full_name') else request.current_user.username
        
        notification_message = f"🧾 New Receipt ({data.get('receiptType', 'Payment')}) created by {user_name} for {customer.name} - Amount: £{data.get('paidAmount', 0):,.2f} (Pending Approval)"
        
        create_activity_notification(
            session=session,
            message=notification_message,
            customer_id=customer_id,
            moved_by=user_name
        )
        
        session.commit()

        return jsonify({
            "success": True,
            "message": f"Receipt ({data.get('receiptType', 'Payment').title()}) saved and sent for approval!",
            "form_submission_id": customer_form_data.id,
            "approval_status": "pending"
        }), 200

    except Exception as e:
        session.rollback()
        current_app.logger.exception(f"Error saving receipt: {e}")
        return jsonify({"error": f"Failed to save receipt: {str(e)}"}), 500
    finally:
        session.close()


# ------------------------------------------------------------------------
# REMAINING ORIGINAL ROUTES (Checklist PDF, Checklist Save, Tokens, Delete)
# ------------------------------------------------------------------------

@form_bp.route('/checklists/download-pdf', methods=['POST', 'OPTIONS'])
def download_checklist_pdf():
    # ... (PDF generation logic remains the same) ...
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    try:
        data = request.get_json(silent=True) or {}
        
        if not data or not data.get('items'):
            return jsonify({'error': 'Missing form data for PDF generation.'}), 400

        pdf = PDF('P', 'mm', 'A4')
        pdf.doc_title = 'Remedial Checklist'
        pdf.alias_nb_pages()
        pdf.add_page()
        pdf.set_auto_page_break(auto=True, margin=15)
        pdf.set_font('Arial', '', 10)
        
        # Colors for Gray Theme
        HEADER_FILL_LIGHT = (230, 230, 230)
        HEADER_FILL_DARK = (200, 200, 200)

        # --- 1. Customer and Fitter Details ---
        pdf.set_fill_color(*HEADER_FILL_LIGHT)
        pdf.set_draw_color(0, 0, 0)
        col_width = 190 / 2
        line_height = 6

        pdf.set_font('Arial', 'B', 10)
        pdf.cell(col_width, line_height, 'CUSTOMER NAME:', 1, 0, 'L', 1)
        pdf.set_font('Arial', '', 10)
        pdf.cell(col_width, line_height, data.get('customerName', 'N/A'), 1, 1, 'L', 0)
        
        pdf.set_font('Arial', 'B', 10)
        pdf.cell(col_width, line_height, 'CUSTOMER ADDRESS:', 1, 0, 'L', 1)
        pdf.set_font('Arial', '', 10)
        start_x = pdf.get_x()
        start_y = pdf.get_y()
        pdf.multi_cell(col_width, line_height, data.get('customerAddress', 'N/A'), 'LRT', 'L', 0)
        end_y = pdf.get_y()
        
        pdf.set_xy(10, end_y - line_height)
        pdf.cell(col_width, line_height, '', 'B', 0, 'L')
        pdf.set_y(end_y)

        pdf.set_font('Arial', 'B', 10)
        pdf.cell(col_width, line_height, 'CUSTOMER TEL NO.:', 1, 0, 'L', 1)
        pdf.set_font('Arial', '', 10)
        pdf.cell(col_width, line_height, data.get('customerPhone', 'N/A'), 1, 1, 'L', 0)

        pdf.set_font('Arial', 'B', 10)
        pdf.cell(col_width, line_height, 'DATE:', 1, 0, 'L', 1)
        pdf.set_font('Arial', '', 10)
        pdf.cell(col_width, line_height, data.get('date', 'N/A'), 1, 1, 'L', 0)

        pdf.set_font('Arial', 'B', 10)
        pdf.cell(col_width, line_height, 'FITTERS:', 1, 0, 'L', 1)
        pdf.set_font('Arial', '', 10)
        pdf.cell(col_width, line_height, data.get('fitters', 'N/A'), 1, 1, 'L', 0)
        
        pdf.ln(10)
        
        # --- 2. Checklist Items Table ---
        pdf.set_font('Arial', 'B', 10)
        pdf.cell(0, 5, 'Items Required for Remedial Action', 0, 1, 'L')
        pdf.ln(1)
        
        header = ['NO', 'ITEM', 'REMEDIAL ACTION', 'COLOUR', 'SIZE', 'QTY']
        widths = [10, 50, 60, 25, 25, 20]
        
        pdf.set_fill_color(*HEADER_FILL_DARK)
        pdf.set_font('Arial', 'B', 9)
        
        for i, h in enumerate(header):
            pdf.cell(widths[i], 7, h, 1, 0, 'C', 1)
        pdf.ln()

        pdf.set_font('Arial', '', 9)
        pdf.set_fill_color(255, 255, 255)
        
        for index, item in enumerate(data.get('items', [])):
            if not item.get('item') and not item.get('remedialAction'):
                continue
            
            row_data = [
                str(index + 1),
                item.get('item', ''),
                item.get('remedialAction', ''),
                item.get('colour', ''),
                item.get('size', ''),
                str(item.get('qty', '')),
            ]
            
            max_height = 5
            
            x_start = pdf.get_x()
            y_start = pdf.get_y()

            pdf.set_xy(x_start + widths[0], y_start)
            pdf.multi_cell(widths[1], 4, row_data[1], 0, 'L', 0, False)
            h_item = pdf.get_y() - y_start
            
            pdf.set_xy(x_start + widths[0] + widths[1], y_start)
            pdf.multi_cell(widths[2], 4, row_data[2], 0, 'L', 0, False)
            h_action = pdf.get_y() - y_start

            row_h = max(max_height, h_item, h_action)
            pdf.set_xy(x_start, y_start)

            for i, txt in enumerate(row_data):
                align = 'C' if i == 0 or i >= 3 else 'L'
                
                if i in [1, 2]:
                    x = pdf.get_x()
                    y = pdf.get_y()
                    pdf.cell(widths[i], row_h, '', 1, 0, align, 0)
                    pdf.set_xy(x + widths[i], y)
                else:
                    pdf.cell(widths[i], row_h, txt, 1, 0, align, 0)
            
            pdf.set_xy(x_start + widths[0], y_start)
            pdf.multi_cell(widths[1], 4, row_data[1], 0, 'L', 0, False)
            
            pdf.set_xy(x_start + widths[0] + widths[1], y_start)
            pdf.multi_cell(widths[2], 4, row_data[2], 0, 'L', 0, False)

            pdf.set_y(y_start + row_h)
        
        pdf_output = pdf.output(dest='S')
        pdf_file = BytesIO(pdf_output)

        customer_name = data.get('customerName', 'Customer').replace(' ', '_')
        date_str = data.get('date', datetime.now().strftime('%Y-%m-%d'))
        filename = f"Remedial_Checklist_{customer_name}_{date_str}.pdf"
        
        return send_file(
            pdf_file,
            mimetype='application/pdf',
            as_attachment=True,
            download_name=filename
        )

    except Exception as e:
        current_app.logger.exception(f"PDF generation failed on server (fpdf2): {e}")
        return jsonify({"error": f"Server failed to generate PDF: {str(e)}"}), 500
    
# ===========================================================================
# UPDATED CHECKLIST SAVE ROUTE (with activity logging)
# ===========================================================================

@form_bp.route('/checklists/save', methods=['POST', 'OPTIONS'])
@token_required
def save_checklist():
    """Handles POST requests to save internal staff checklists with activity logging."""
    if request.method == 'OPTIONS':
        return jsonify({}), 200

    session = SessionLocal()
    try:
        data = request.get_json(silent=True) or {}
        checklist_type = data.get('checklistType', 'unknown')
        customer_id = data.get('customerId')
        customer_name = data.get('customerName', 'N/A')
        fitters = data.get('fitters', 'Unknown')

        customer = session.get(Customer, customer_id)
        if not customer:
            return jsonify({'error': 'Customer not found, cannot save checklist'}), 404
            
        customer_form_data = CustomerFormData(
            customer_id=customer_id,
            form_data=json.dumps(data),
            token_used='',
            submitted_at=datetime.utcnow(),
            created_by=request.current_user.id
        )
        
        session.add(customer_form_data)
        session.flush()  # Get the ID before committing
        
        # 🔔 CREATE ACTIVITY NOTIFICATION
        user_name = request.current_user.full_name if hasattr(request.current_user, 'full_name') else request.current_user.username
        
        notification_message = f"📋 New {checklist_type.title()} Checklist created by {user_name} for customer: {customer_name}"
        if fitters and fitters != 'Unknown':
            notification_message += f" (Fitters: {fitters})"
        
        create_activity_notification(
            session=session,
            message=notification_message,
            customer_id=customer_id,
            moved_by=user_name
        )
        
        session.commit()
        
        current_app.logger.info(f"Staff checklist '{checklist_type}' saved for customer {customer_id} ({customer_name}). ID: {customer_form_data.id}")

        return jsonify({
            "success": True,
            "message": f"{checklist_type.title()} Checklist saved successfully!",
            "form_submission_id": customer_form_data.id
        }), 200

    except Exception as e:
        session.rollback()
        current_app.logger.exception(f"Error saving internal checklist: {e}")
        return jsonify({"error": f"Failed to save checklist: {str(e)}"}), 500
    finally:
        session.close()


@form_bp.route('/customers/<customer_id>/generate-form-link', methods=['POST', 'OPTIONS'])
def generate_customer_form_link(customer_id):
    """Generate form link for specific customer (In-memory token generation)"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200

    session = SessionLocal() # 👈 Start session to fix Customer.query.get error
    try:
        # FIX: Replaced Customer.query.get with session.get(Customer, ...)
        customer = session.get(Customer, customer_id)
        if not customer:
            return jsonify({
                'success': False,
                'error': 'Customer not found'
            }), 404

        data = request.get_json(silent=True) or {}
        form_type = data.get('formType', 'bedroom')

        token = generate_secure_token()
        expiration = datetime.now() + timedelta(hours=24)
        
        form_tokens[token] = {
            'customer_id': customer_id,
            'form_type': form_type,
            'created_at': datetime.now(),
            'expires_at': expiration,
            'used': False
        }
        
        current_app.logger.debug(f"Generated token {token} for customer {customer_id}, expires {expiration}")

        return jsonify({
            'success': True,
            'token': token,
            'form_type': form_type,
            'expires_at': expiration.isoformat(),
            'message': f'{form_type.title()} form link generated successfully'
        }), 200

    except Exception as e:
        current_app.logger.exception(f"Failed to generate form link for customer {customer_id}")
        return jsonify({
            'success': False,
            'error': f'Failed to generate form link: {str(e)}'
        }), 500
    finally:
        session.close() # 👈 Close session


@form_bp.route('/validate-form-token/<token>', methods=['GET', 'OPTIONS'])
def validate_form_token(token):
    # ... (Token validation logic remains the same) ...
    if request.method == 'OPTIONS':
        return jsonify({}), 200

    try:
        current_app.logger.debug(f"Validating token: {token}")
        if token not in form_tokens:
            return jsonify({'valid': False, 'error': 'Invalid token'}), 404

        token_data = form_tokens[token]

        if datetime.now() > token_data['expires_at']:
            del form_tokens[token]
            return jsonify({'valid': False, 'error': 'Token has expired'}), 410

        if token_data['used']:
            return jsonify({'valid': False, 'error': 'Token has already been used'}), 410

        return jsonify({
            'valid': True,
            'expires_at': token_data['expires_at'].isoformat(),
            'customer_id': token_data.get('customer_id'),
            'form_type': token_data.get('form_type')
        }), 200

    except Exception as e:
        current_app.logger.exception("Token validation failed")
        return jsonify({'valid': False, 'error': f'Validation failed: {str(e)}'}), 500


@form_bp.route('/submit-customer-form', methods=['POST', 'OPTIONS'])
def submit_customer_form():
    """Submit form - creates only ONE submission record"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200

    session = SessionLocal() # 👈 Start session
    try:
        data = request.get_json(silent=True) or {}
        token = data.get('token')
        form_data = data.get('formData', {})

        if not form_data:
            return jsonify({'success': False, 'error': 'Missing form data'}), 400

        customer_id = None
        
        # --- 1. Handle Token Validation & Usage ---
        if token:
            current_app.logger.debug(f"Processing token-based submission with token: {token}")
            
            if token not in form_tokens:
                return jsonify({'success': False, 'error': 'Invalid or expired token'}), 400

            token_data = form_tokens[token]
            
            if datetime.now() > token_data['expires_at']:
                del form_tokens[token]
                return jsonify({'success': False, 'error': 'Token has expired'}), 410
                
            if token_data['used']:
                return jsonify({'success': False, 'error': 'Token has already been used'}), 410

            customer_id = token_data.get('customer_id')
            
            if customer_id:
                customer = session.get(Customer, customer_id) # Use session.get()
                if not customer:
                    return jsonify({'success': False, 'error': 'Associated customer not found'}), 404
                
                form_tokens[token]['used'] = True
                current_app.logger.info(f"Token {token} marked as used for customer {customer_id}")
        
        # --- 2. Handle Direct Customer ID or New Customer Creation ---
        if not customer_id:
            customer_id = form_data.get('customer_id') or request.args.get('customerId')
            
            if customer_id:
                customer = session.get(Customer, customer_id) # Use session.get()
                if not customer:
                    return jsonify({'success': False, 'error': 'Specified customer not found'}), 404
            else:
                # Create NEW customer
                customer_name = (form_data.get('customer_name') or '').strip()
                customer_address = (form_data.get('customer_address') or '').strip()
                
                if not customer_name or not customer_address:
                    return jsonify({
                        'success': False,
                        'error': 'Customer name and address are required for new customer creation'
                    }), 400
                
                customer = Customer(
                    name=customer_name,
                    phone=(form_data.get('customer_phone') or '').strip(),
                    address=customer_address,
                    status='New Lead',
                    created_by='Form Submission'
                )
                session.add(customer)
                session.flush() # Flush to get customer ID
                customer_id = customer.id
                current_app.logger.info(f"Created new customer {customer_id} from form submission")

        # --- 3. Save Form Submission ---       
        project_id_from_data = form_data.get('project_id')
        
        customer_form_data = CustomerFormData(
            customer_id=customer_id,
            # **PASS THE VALUE (which is likely None in this case)**
            project_id=project_id_from_data, 
            form_data=json.dumps(form_data),
            token_used=token or '',
            submitted_at=datetime.utcnow()
        )
        session.add(customer_form_data)
        session.commit() # 👈 Commit transaction
        
        final_customer = session.get(Customer, customer_id)
        customer_name = final_customer.name if final_customer else 'Customer'
        
        current_app.logger.info(f"Single form submission created for customer {customer_id}")

        return jsonify({
            'success': True,
            'customer_id': customer_id,
            'form_submission_id': customer_form_data.id,
            'message': f'Form submitted successfully for {customer_name}'
        }), 201

    except Exception as e:
        session.rollback() # 👈 Rollback on error
        current_app.logger.exception(f"Database error during form submission for customer {customer_id}")
        return jsonify({'success': False, 'error': f'Form submission failed: {str(e)}'}), 500
    finally:
        session.close() # 👈 Close session


@form_bp.route('/generate-form-link', methods=['POST', 'OPTIONS'])
def generate_form_link():
    """Legacy endpoint - generates token not tied to specific customer (In-memory token generation)"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200

    try:
        token = generate_secure_token()
        expiration = datetime.now() + timedelta(hours=24)
        form_tokens[token] = {
            'created_at': datetime.now(),
            'expires_at': expiration,
            'used': False
        }
        current_app.logger.debug(f"Generated legacy token {token} expires {expiration}")

        return jsonify({
            'success': True,
            'token': token,
            'expires_at': expiration.isoformat(),
            'message': 'Form link generated successfully'
        }), 200

    except Exception as e:
        current_app.logger.exception("Failed to generate form link")
        return jsonify({
            'success': False,
            'error': f'Failed to generate form link: {str(e)}'
        }), 500


@form_bp.route('/cleanup-expired-tokens', methods=['POST', 'OPTIONS'])
def cleanup_expired_tokens():
    # ... (Cleanup logic remains the same as it doesn't touch the DB) ...
    if request.method == 'OPTIONS':
        return jsonify({}), 200

    try:
        current_time = datetime.now()
        expired_tokens = [t for t, d in form_tokens.items() if current_time > d['expires_at']]
        for t in expired_tokens:
            del form_tokens[t]
        return jsonify({
            'success': True,
            'cleaned_tokens': len(expired_tokens),
            'remaining_tokens': len(form_tokens)
        }), 200
    except Exception as e:
        current_app.logger.exception("Cleanup failed")
        return jsonify({'success': False, 'error': f'Cleanup failed: {str(e)}'}), 500


@form_bp.route('/form-submissions/<int:submission_id>', methods=['DELETE'])
@token_required
def delete_form_submission(submission_id):
    """
    Delete a form submission and its related approval notifications.
    Fixed to ensure related notifications are deleted within the transaction.
    """
    session = SessionLocal() # 👈 Start session
    try:
        # Get the form submission using the active session
        submission = session.get(CustomerFormData, submission_id)
        if not submission:
            return jsonify({'error': 'Form submission not found'}), 404
        
        # Delete related approval notifications (Cascade might handle this, but explicit delete is safer)
        # Note: If the model has cascade='all, delete-orphan' defined, this line might be redundant
        # or cause issues if the session delete happens first. We'll rely on the model or explicit delete.
        session.query(ApprovalNotification).filter_by(document_id=submission_id).delete(synchronize_session='fetch')

        # Now safely delete the form submission
        session.delete(submission)
        session.commit() # 👈 Commit transaction
        
        return jsonify({
            'message': 'Form submission deleted successfully',
            'id': submission_id
        }), 200
        
    except Exception as e:
        session.rollback() # 👈 Rollback on error
        current_app.logger.exception(f"Failed to delete form submission {submission_id}: {e}")
        return jsonify({
            'error': f'Failed to delete form submission: {str(e)}'
        }), 500
    finally:
        session.close() # 👈 Close session

@form_bp.route('/form-submissions/<int:submission_id>', methods=['GET', 'OPTIONS'])
@token_required
def get_form_submission(submission_id):
    """Get a single form submission by ID"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    session = SessionLocal()
    try:
        submission = session.get(CustomerFormData, submission_id)
        if not submission:
            return jsonify({'error': 'Form submission not found'}), 404
        
        # Check permissions - only allow viewing if:
        # 1. User is Manager/HR/Sales (can view all)
        # 2. User is the creator
        # 3. User is Production (can view all)
        user_role = request.current_user.role
        allowed_roles = ['Manager', 'HR', 'Production', 'Sales']
        is_creator = submission.created_by == request.current_user.id
        
        if user_role not in allowed_roles and not is_creator:
            return jsonify({'error': 'You do not have permission to view this form'}), 403
        
        # Parse the form_data JSON string
        form_data = json.loads(submission.form_data)
        
        # Get customer info
        customer = session.get(Customer, submission.customer_id)
        
        return jsonify({
            'id': submission.id,
            'customer_id': submission.customer_id,
            'customer_name': customer.name if customer else 'N/A',
            'form_data': form_data,
            'submitted_at': submission.submitted_at.isoformat() if submission.submitted_at else None,
            'updated_at': submission.updated_at.isoformat() if submission.updated_at else None,
            'approval_status': submission.approval_status,
            'created_by': submission.created_by
        }), 200
        
    except Exception as e:
        session.rollback()
        current_app.logger.exception(f"Error fetching form submission {submission_id}: {e}")
        return jsonify({'error': f'Failed to fetch form submission: {str(e)}'}), 500
    finally:
        session.close()

# ===========================================================================
# UPDATED FORM SUBMISSION UPDATE ROUTE (with detailed checklist change tracking)
# ===========================================================================

@form_bp.route('/form-submissions/<int:submission_id>', methods=['PUT', 'OPTIONS'])
@token_required
def update_form_submission(submission_id):
    """Update an existing form submission with detailed change tracking and notifications"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200

    session = SessionLocal()
    try:
        data = request.get_json(silent=True) or {}
        updated_form_data = data.get('formData')
        
        if not updated_form_data:
            return jsonify({'error': 'Missing form data'}), 400

        submission = session.get(CustomerFormData, submission_id)
        if not submission:
            return jsonify({'error': 'Form submission not found'}), 404

        # Check permissions
        user_role = request.current_user.role
        allowed_roles = ['Manager', 'HR', 'Production', 'Sales']
        is_creator = submission.created_by == request.current_user.id
        
        if user_role not in allowed_roles and not is_creator:
            return jsonify({'error': 'You do not have permission to edit this form'}), 403

        # Get old data for comparison
        old_form_data = json.loads(submission.form_data)
        
        # Update the form data
        submission.form_data = json.dumps(updated_form_data)
        submission.updated_at = datetime.utcnow()
        
        # 🔔 CREATE ACTIVITY NOTIFICATION WITH DETAILED CHANGE TRACKING
        user_name = request.current_user.full_name if hasattr(request.current_user, 'full_name') else request.current_user.username
        
        # Get customer info
        customer = session.get(Customer, submission.customer_id)
        customer_name = customer.name if customer else old_form_data.get('customerName', 'N/A')
        
        # Determine what type of form was updated and detect changes
        notification_message = ""
        
        if old_form_data.get('is_invoice'):
            form_type = f"Invoice #{old_form_data.get('invoiceNumber', 'N/A')}"
            notification_message = f"✏️ {form_type} updated by {user_name} for {customer_name}"
            
        elif old_form_data.get('is_receipt'):
            form_type = f"Receipt ({old_form_data.get('receiptType', 'Payment')})"
            notification_message = f"✏️ {form_type} updated by {user_name} for {customer_name}"
            
        elif old_form_data.get('checklistType'):
            # DETAILED CHECKLIST CHANGE TRACKING
            checklist_type = old_form_data.get('checklistType', '').title()
            form_type = f"{checklist_type} Checklist"
            
            # Detect specific changes
            changes = detect_checklist_changes(old_form_data, updated_form_data)
            
            if changes:
                # Create detailed notification with changes
                # For the main notification message, show first 2-3 changes
                changes_preview = " | ".join(changes[:2])
                if len(changes) > 2:
                    changes_preview += f" (+{len(changes) - 2} more changes)"
                
                notification_message = f"✏️ {form_type} edited by {user_name} for {customer_name}. Changes: {changes_preview}"
            else:
                notification_message = f"✏️ {form_type} updated by {user_name} for {customer_name}"
        else:
            notification_message = f"✏️ Form updated by {user_name} for {customer_name}"
        
        create_activity_notification(
            session=session,
            message=notification_message,
            customer_id=submission.customer_id,
            moved_by=user_name
        )
        
        session.commit()

        current_app.logger.info(f"Form submission {submission_id} updated by user {request.current_user.id}")

        return jsonify({
            'success': True,
            'message': 'Form updated successfully',
            'form_submission_id': submission.id
        }), 200

    except Exception as e:
        session.rollback()
        current_app.logger.exception(f"Error updating form submission {submission_id}: {e}")
        return jsonify({'error': f'Failed to update form: {str(e)}'}), 500
    finally:
        session.close()

# ============================================================================
# HELPER FUNCTION: Detect Checklist Changes
# ============================================================================

def detect_checklist_changes(old_data, new_data):
    """
    Compare old and new checklist data and return a human-readable description of changes.
    Returns a list of change descriptions.
    """
    changes = []
    
    # Check basic field changes
    field_labels = {
        'customerName': 'Customer Name',
        'customerAddress': 'Customer Address',
        'customerPhone': 'Customer Phone',
        'date': 'Date',
        'fitters': 'Fitters'
    }
    
    for field, label in field_labels.items():
        old_val = str(old_data.get(field, '')).strip()
        new_val = str(new_data.get(field, '')).strip()
        if old_val != new_val and (old_val or new_val):  # Only report if values are different and not both empty
            if old_val and new_val:
                changes.append(f"{label} changed from '{old_val}' to '{new_val}'")
            elif new_val:
                changes.append(f"{label} added: '{new_val}'")
            else:
                changes.append(f"{label} removed")
    
    # Check items changes
    old_items = old_data.get('items', [])
    new_items = new_data.get('items', [])
    
    # Filter out empty items for accurate counting
    def is_non_empty_item(item):
        return any([
            item.get('item', '').strip(),
            item.get('remedialAction', '').strip(),
            item.get('colour', '').strip(),
            item.get('size', '').strip(),
            str(item.get('qty', '')).strip()
        ])
    
    old_non_empty = [item for item in old_items if is_non_empty_item(item)]
    new_non_empty = [item for item in new_items if is_non_empty_item(item)]
    
    # Report additions/removals
    if len(new_non_empty) > len(old_non_empty):
        diff = len(new_non_empty) - len(old_non_empty)
        changes.append(f"➕ Added {diff} new item{'' if diff == 1 else 's'}")
    elif len(new_non_empty) < len(old_non_empty):
        diff = len(old_non_empty) - len(new_non_empty)
        changes.append(f"➖ Removed {diff} item{'' if diff == 1 else 's'}")
    
    # Check for modifications in existing items (compare by position)
    min_length = min(len(old_items), len(new_items))
    modifications_count = 0
    detailed_modifications = []
    
    for i in range(min_length):
        old_item = old_items[i]
        new_item = new_items[i]
        
        # Skip if both items are empty
        if not is_non_empty_item(old_item) and not is_non_empty_item(new_item):
            continue
        
        item_changes = []
        
        # Check each field
        if str(old_item.get('item', '')).strip() != str(new_item.get('item', '')).strip():
            item_changes.append("item name")
        if str(old_item.get('remedialAction', '')).strip() != str(new_item.get('remedialAction', '')).strip():
            item_changes.append("remedial action")
        if str(old_item.get('colour', '')).strip() != str(new_item.get('colour', '')).strip():
            item_changes.append("colour")
        if str(old_item.get('size', '')).strip() != str(new_item.get('size', '')).strip():
            item_changes.append("size")
        if str(old_item.get('qty', '')).strip() != str(new_item.get('qty', '')).strip():
            item_changes.append("quantity")
        
        if item_changes:
            modifications_count += 1
            item_name = new_item.get('item', '').strip() or old_item.get('item', '').strip() or f"Item #{i+1}"
            # Limit item name length for readability
            if len(item_name) > 30:
                item_name = item_name[:27] + "..."
            detailed_modifications.append(f"• {item_name}: {', '.join(item_changes)}")
    
    # Add modification summary
    if modifications_count > 0:
        changes.append(f"✏️ Modified {modifications_count} item{'' if modifications_count == 1 else 's'}")
        # Add detailed modifications (limit to first 3 for notification clarity)
        changes.extend(detailed_modifications[:3])
        if len(detailed_modifications) > 3:
            changes.append(f"... and {len(detailed_modifications) - 3} more changes")
    
    return changes
