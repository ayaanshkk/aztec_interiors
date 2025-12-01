# from flask import Blueprint, request, jsonify
# from datetime import datetime
# from ..models import CustomerFormData, User, Customer, ApprovalNotification
# from flask import current_app
# from functools import wraps # Moved to the top
# import json

# from ..db import SessionLocal # 👈 NEW IMPORT: Necessary for database access

# approvals_bp = Blueprint('approvals', __name__)

# # Token authentication decorator (Assuming this implementation is temporary/mock)
# def token_required(f):
#     @wraps(f)
#     def decorated(*args, **kwargs):
#         # Allow OPTIONS requests without authentication (for CORS)
#         if request.method == 'OPTIONS':
#             return jsonify({}), 200
        
#         # --- Mock Token Logic ---
#         # NOTE: This decorator implementation relies on external logic (User.verify_jwt_token)
#         # It's assumed functional for now, as it's not the source of the AttributeError.
        
#         token = None
        
#         if 'Authorization' in request.headers:
#             auth_header = request.headers['Authorization']
#             try:
#                 token = auth_header.split(" ")[1]
#             except IndexError:
#                 return jsonify({'error': 'Invalid token format'}), 401
        
#         if not token:
#             return jsonify({'error': 'Token is missing'}), 401
        
#         try:
#             # WARNING: User.verify_jwt_token is NOT fixed here, assuming it does not rely on Model.query
#             current_user = User.verify_jwt_token(token, current_app.config['SECRET_KEY'])
#             if not current_user:
#                 return jsonify({'error': 'Token is invalid or expired'}), 401
            
#             request.current_user = current_user
            
#         except Exception as e:
#             return jsonify({'error': 'Token verification failed'}), 401
        
#         return f(*args, **kwargs)
    
#     return decorated

# # Manager-only decorator
# def manager_required(f):
#     @wraps(f)
#     @token_required
#     def decorated(*args, **kwargs):
#         if not hasattr(request, 'current_user'):
#             return jsonify({'error': 'Authentication required'}), 401
        
#         if request.current_user.role not in ['Manager', 'HR']:
#             return jsonify({'error': 'Manager or HR access required'}), 403
        
#         return f(*args, **kwargs)
    
#     return decorated

# # Get all pending approvals (for managers)
# @approvals_bp.route('/approvals/pending', methods=['GET', 'OPTIONS'])
# @token_required
# @manager_required
# def get_pending_approvals():
#     if request.method == 'OPTIONS':
#         return jsonify({}), 200
    
#     session = SessionLocal() # 👈 START SESSION
#     try:
#         # FIXED QUERY: Use session.query(Model)
#         pending_submissions = session.query(CustomerFormData).filter_by(
#             approval_status='pending'
#         ).order_by(CustomerFormData.submitted_at.desc()).all()
        
#         all_pending = []
        
#         for submission in pending_submissions:
#             form_data = json.loads(submission.form_data)
            
#             # FIXED QUERY: Use session.get() or session.query() for related models
#             creator = session.get(User, submission.created_by) if submission.created_by else None
#             customer = session.get(Customer, submission.customer_id)
            
#             doc_type = 'form'
#             if form_data.get('is_invoice'):
#                 doc_type = 'invoice'
#             elif form_data.get('is_receipt'):
#                 doc_type = 'receipt'
#             elif form_data.get('form_type') in ['kitchen', 'bedroom']:
#                 doc_type = 'checklist'
            
#             pending_item = {
#                 'id': submission.id,
#                 'type': doc_type,
#                 'invoice_number': form_data.get('invoiceNumber'),
#                 'receipt_number': form_data.get('receiptType'),
#                 'customer_name': customer.name if customer else form_data.get('customerName', 'N/A'),
#                 'total_amount': form_data.get('totalAmount') or form_data.get('paidAmount'),
#                 'created_by': creator.get_full_name() if creator else 'Unknown',
#                 'created_at': submission.submitted_at.isoformat()
#             }
#             all_pending.append(pending_item)
        
#         return jsonify({'success': True, 'data': all_pending}), 200
        
#     except Exception as e:
#         # No rollback needed as this is a read operation, but good practice to handle it.
#         session.rollback() 
#         current_app.logger.exception(f"Error fetching pending approvals: {e}")
#         return jsonify({'error': 'Failed to fetch pending approvals'}), 500
#     finally:
#         session.close() # 👈 CLOSE SESSION

# # Approve a document
# @approvals_bp.route('/approvals/approve', methods=['POST', 'OPTIONS'])
# @token_required
# @manager_required
# def approve_document():
#     if request.method == 'OPTIONS':
#         return jsonify({}), 200
    
#     session = SessionLocal() # 👈 Start session
#     try:
#         data = request.get_json()
#         document_id = data.get('documentId')
        
#         if not document_id:
#             return jsonify({'error': 'Missing document ID'}), 400
        
#         # Use the active session's .get method
#         submission = session.get(CustomerFormData, document_id) 
#         if not submission:
#             return jsonify({'error': 'Document not found'}), 404
        
#         submission.approval_status = 'approved'
#         submission.approved_by = request.current_user.id
#         submission.approval_date = datetime.utcnow()
        
#         form_data = json.loads(submission.form_data)
#         doc_type = 'document'
#         if form_data.get('is_invoice'):
#             doc_type = 'invoice'
#         elif form_data.get('is_receipt'):
#             doc_type = 'receipt'
        
#         current_app.logger.info(
#             f"Document {document_id} ({doc_type}) approved by manager {request.current_user.id}"
#         )
        
#         session.commit() # 👈 Commit transaction
        
#         return jsonify({'success': True, 'message': 'Document approved successfully'}), 200
        
#     except Exception as e:
#         session.rollback() # 👈 Rollback on error
#         current_app.logger.exception(f"Error approving document: {e}")
#         return jsonify({'error': 'Failed to approve document'}), 500
#     finally:
#         session.close() # 👈 Close session

# # Reject a document
# @approvals_bp.route('/approvals/reject', methods=['POST', 'OPTIONS'])
# @token_required
# @manager_required
# def reject_document():
#     if request.method == 'OPTIONS':
#         return jsonify({}), 200
    
#     session = SessionLocal() # 👈 Start session
#     try:
#         data = request.get_json()
#         document_id = data.get('documentId')
#         reason = data.get('reason', '')
        
#         if not document_id:
#             return jsonify({'error': 'Missing document ID'}), 400
        
#         if not reason.strip():
#             return jsonify({'error': 'Rejection reason is required'}), 400
        
#         # Use the active session's .get method
#         submission = session.get(CustomerFormData, document_id) 
#         if not submission:
#             return jsonify({'error': 'Document not found'}), 404
        
#         submission.approval_status = 'rejected'
#         submission.approved_by = request.current_user.id
#         submission.approval_date = datetime.utcnow()
#         submission.rejection_reason = reason
        
#         form_data = json.loads(submission.form_data)
#         doc_type = 'document'
#         if form_data.get('is_invoice'):
#             doc_type = 'invoice'
#         elif form_data.get('is_receipt'):
#             doc_type = 'receipt'
        
#         current_app.logger.info(
#             f"Document {document_id} ({doc_type}) rejected by manager {request.current_user.id}. Reason: {reason}"
#         )
        
#         session.commit() # 👈 Commit transaction
        
#         return jsonify({'success': True, 'message': 'Document rejected'}), 200
        
#     except Exception as e:
#         session.rollback() # 👈 Rollback on error
#         current_app.logger.exception(f"Error rejecting document: {e}")
#         return jsonify({'error': 'Failed to reject document'}), 500
#     finally:
#         session.close() # 👈 Close session