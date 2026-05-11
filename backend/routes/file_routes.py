from flask import request, jsonify, send_file, Blueprint, current_app, redirect, Response
from werkzeug.utils import secure_filename
from datetime import datetime
from sqlalchemy import text, or_
import os
import uuid 
import requests
from ..utils.file_utils import allowed_file
from .auth_helpers import token_required, require_tenant
from ..db import SessionLocal

file_bp = Blueprint('file_routes', __name__)

# ==========================================
# VERCEL BLOB / FILE HANDLING
# ==========================================

def upload_to_vercel_blob(file, filename):
    """Upload file to Vercel Blob via Next.js API"""
    try:
        NEXTJS_URL = os.getenv('NEXT_PUBLIC_FRONTEND_URL', 'http://localhost:3000')
        
        # Prepare file for upload
        files = {'file': (filename, file.stream, file.content_type)}
        
        # Upload to Vercel Blob via Next.js API
        upload_response = requests.post(
            f'{NEXTJS_URL}/api/upload',
            files=files,
            timeout=30
        )
        
        if upload_response.status_code != 200:
            error_data = upload_response.json() if upload_response.text else {}
            raise Exception(f"Vercel Blob upload failed: {error_data.get('error', 'Unknown error')}")
        
        blob_data = upload_response.json()
        return blob_data['url']  # Full Vercel Blob URL
        
    except requests.exceptions.Timeout:
        current_app.logger.error("Timeout uploading to Vercel Blob")
        raise Exception("Upload timeout - please try again")
    except requests.exceptions.RequestException as e:
        current_app.logger.error(f"Request error uploading to Vercel Blob: {e}")
        raise Exception(f"Upload failed: {str(e)}")
    except Exception as e:
        current_app.logger.error(f"Error uploading to Vercel Blob: {e}")
        raise


# ==========================================
# CUSTOMER DOCUMENTS ROUTES (UNIFIED)
# ==========================================

@file_bp.route('/files/documents', methods=['GET', 'POST'])
@token_required
@require_tenant
def handle_customer_documents(tenant_id, employee_id):
    """
    GET: Fetch documents for a customer/project/opportunity
    POST: Upload a document and save metadata
    """
    if request.method == 'GET':
        client_id = request.args.get('client_id') or request.args.get('customer_id')
        project_id = request.args.get('project_id')
        opportunity_id = request.args.get('opportunity_id')
        document_category = request.args.get('category')
        
        if not client_id and not project_id and not opportunity_id:
            return jsonify({'error': 'client_id, project_id, or opportunity_id required'}), 400

        session = SessionLocal()
        try:
            # Build WHERE conditions
            where_conditions = []
            params = {}
            
            if client_id:
                where_conditions.append("client_id = :client_id")
                params['client_id'] = int(client_id)
            
            if project_id:
                where_conditions.append("project_id = :project_id")
                params['project_id'] = int(project_id)
            
            if opportunity_id:
                where_conditions.append("opportunity_id = :opportunity_id")
                params['opportunity_id'] = int(opportunity_id)
            
            if document_category:
                where_conditions.append("document_category = :category")
                params['category'] = document_category
            
            where_clause = " AND ".join(where_conditions)
            
            query = text(f"""
                SELECT * FROM "StreemLyne_MT"."Customer_Documents"
                WHERE {where_clause}
                ORDER BY uploaded_at DESC
            """)
            
            documents = session.execute(query, params).fetchall()
            
            result = []
            for doc in documents:
                result.append({
                    'id': doc.id,
                    'client_id': doc.client_id,
                    'customer_id': doc.client_id,  # Backward compatibility
                    'project_id': doc.project_id,
                    'opportunity_id': doc.opportunity_id,
                    'property_id': doc.property_id,
                    'file_name': doc.file_name,
                    'file_url': doc.file_url,
                    'document_category': doc.document_category,
                    'category': doc.document_category,  # Backward compatibility
                    'mime_type': doc.mime_type if hasattr(doc, 'mime_type') else None,
                    'uploaded_at': doc.uploaded_at.isoformat() if doc.uploaded_at else None
                })
            
            return jsonify(result), 200

        except Exception as e:
            current_app.logger.error(f"Error fetching documents: {e}", exc_info=True)
            return jsonify({'error': f'Failed to fetch documents: {str(e)}'}), 500
        finally:
            session.close()

    # POST - Upload document
    elif request.method == 'POST':
        session = SessionLocal()
        try:
            client_id = request.form.get('client_id') or request.form.get('customer_id')
            project_id = request.form.get('project_id')
            opportunity_id = request.form.get('opportunity_id')
            property_id = request.form.get('property_id')
            document_category = request.form.get('category') or request.form.get('document_category', 'drawing')

            if not client_id:
                return jsonify({'error': 'client_id or customer_id is required'}), 400

            if 'file' not in request.files:
                return jsonify({'error': 'No file part in the request'}), 400

            file = request.files['file']
            if file.filename == '':
                return jsonify({'error': 'No file selected for upload'}), 400

            # Security
            filename = secure_filename(file.filename)
            unique_filename = f"{client_id}_{str(uuid.uuid4())}_{filename}"
            
            # Upload to Vercel Blob
            current_app.logger.info(f"Uploading {filename} to Vercel Blob...")
            file_url = upload_to_vercel_blob(file, unique_filename)
            current_app.logger.info(f"File uploaded: {file_url}")
            
            # Determine MIME type
            mime_type = file.mimetype if hasattr(file, 'mimetype') else 'application/octet-stream'
            
            # Create database record
            insert_query = text("""
                INSERT INTO "StreemLyne_MT"."Customer_Documents"
                (client_id, project_id, opportunity_id, property_id,
                 file_name, file_url, document_category, mime_type)
                VALUES (:client_id, :project_id, :opportunity_id, :property_id,
                        :file_name, :file_url, :category, :mime_type)
                RETURNING id
            """)
            
            result = session.execute(insert_query, {
                'client_id': int(client_id),
                'project_id': int(project_id) if project_id else None,
                'opportunity_id': int(opportunity_id) if opportunity_id else None,
                'property_id': int(property_id) if property_id else None,
                'file_name': filename,
                'file_url': file_url,
                'category': document_category,
                'mime_type': mime_type
            })
            
            doc_id = result.fetchone().id
            session.commit()
            
            current_app.logger.info(f"Document saved for client {client_id}: {filename}")
            
            return jsonify({
                'success': True,
                'message': 'File uploaded successfully',
                'document': {
                    'id': doc_id,
                    'file_name': filename,
                    'file_url': file_url,
                    'document_category': document_category
                }
            }), 201

        except Exception as e:
            session.rollback()
            current_app.logger.error(f"Error uploading document: {e}", exc_info=True)
            return jsonify({'error': f'Upload failed: {str(e)}'}), 500
        finally:
            session.close()


@file_bp.route('/files/documents/<int:document_id>', methods=['GET', 'PATCH', 'DELETE'])
@token_required
@require_tenant
def handle_single_document(document_id, tenant_id, employee_id):
    """Get, update, or delete a specific document"""
    session = SessionLocal()
    try:
        # Get document
        query = text("""
            SELECT * FROM "StreemLyne_MT"."Customer_Documents"
            WHERE id = :doc_id
        """)
        
        document = session.execute(query, {'doc_id': document_id}).fetchone()
        
        if not document:
            return jsonify({'error': 'Document not found'}), 404
        
        # GET
        if request.method == 'GET':
            return jsonify({
                'id': document.id,
                'client_id': document.client_id,
                'project_id': document.project_id,
                'opportunity_id': document.opportunity_id,
                'property_id': document.property_id,
                'file_name': document.file_name,
                'file_url': document.file_url,
                'document_category': document.document_category,
                'mime_type': document.mime_type if hasattr(document, 'mime_type') else None,
                'uploaded_at': document.uploaded_at.isoformat() if document.uploaded_at else None
            }), 200
        
        # PATCH
        elif request.method == 'PATCH':
            data = request.get_json()
            
            update_fields = []
            params = {'doc_id': document_id}
            
            if 'project_id' in data:
                update_fields.append("project_id = :project_id")
                params['project_id'] = data['project_id']
            
            if 'opportunity_id' in data:
                update_fields.append("opportunity_id = :opportunity_id")
                params['opportunity_id'] = data['opportunity_id']
            
            if 'document_category' in data:
                update_fields.append("document_category = :category")
                params['category'] = data['document_category']
            
            if not update_fields:
                return jsonify({'error': 'No fields to update'}), 400
            
            update_query = text(f"""
                UPDATE "StreemLyne_MT"."Customer_Documents"
                SET {', '.join(update_fields)}
                WHERE id = :doc_id
            """)
            
            session.execute(update_query, params)
            session.commit()
            
            return jsonify({
                'success': True,
                'message': 'Document updated successfully'
            }), 200
        
        # DELETE
        elif request.method == 'DELETE':
            # Delete from database (Vercel Blob files persist, managed separately if needed)
            delete_query = text("""
                DELETE FROM "StreemLyne_MT"."Customer_Documents"
                WHERE id = :doc_id
            """)
            
            session.execute(delete_query, {'doc_id': document_id})
            session.commit()
            
            current_app.logger.info(f"Document {document_id} deleted from database")
            
            return jsonify({
                'success': True,
                'message': 'Document deleted successfully'
            }), 200

    except Exception as e:
        session.rollback()
        current_app.logger.error(f"Error handling document {document_id}: {e}", exc_info=True)
        return jsonify({'error': f'Operation failed: {str(e)}'}), 500
    finally:
        session.close()


@file_bp.route('/files/documents/view/<path:filename>', methods=['GET'])
def view_document(filename):
    """Serve document - redirect to Vercel Blob URL"""
    session = SessionLocal()
    try:
        # Look up document by filename
        query = text("""
            SELECT * FROM "StreemLyne_MT"."Customer_Documents"
            WHERE file_name LIKE :filename
               OR file_url LIKE :filename
            LIMIT 1
        """)
        
        document = session.execute(query, {
            'filename': f'%{filename}%'
        }).fetchone()
        
        if not document:
            current_app.logger.error(f"Document not found: {filename}")
            return jsonify({'error': 'Document not found'}), 404
        
        file_url = document.file_url
        
        # Check if it's a valid URL
        if not file_url or not file_url.startswith('https://'):
            current_app.logger.error(f"Invalid file URL: {file_url}")
            return jsonify({
                'error': 'Invalid file URL',
                'message': 'The document URL is not properly configured. Please re-upload the file.'
            }), 500
        
        current_app.logger.info(f"Redirecting to: {file_url}")
        
        # Redirect to Vercel Blob URL
        return redirect(file_url, code=302)
        
    except Exception as e:
        current_app.logger.error(f"Error serving document: {e}", exc_info=True)
        return jsonify({'error': f'Failed to retrieve file: {str(e)}'}), 500
    finally:
        session.close()


# ==========================================
# BACKWARD COMPATIBILITY ROUTES
# ==========================================

@file_bp.route('/files/drawings', methods=['GET'])
@token_required
@require_tenant
def handle_drawings_compat(tenant_id, employee_id):
    """Get customer drawing documents"""
    customer_id = request.args.get('customer_id')
    project_id = request.args.get('project_id')
    
    session = SessionLocal()
    try:
        # Build WHERE conditions properly
        where_conditions = [
            "(document_category IN ('pdf', 'image', 'drawing') OR document_category IS NULL)"
        ]
        params = {'tenant_id': str(tenant_id)}
        
        if customer_id:
            where_conditions.append("cd.client_id = :customer_id")
            params['customer_id'] = int(customer_id)
        elif project_id:
            # If project_id provided, get client_id from project
            where_conditions.append("""
                cd.client_id IN (
                    SELECT client_id FROM "StreemLyne_MT"."Project_Details"
                    WHERE project_id = :project_id AND tenant_id = :tenant_id
                )
            """)
            params['project_id'] = int(project_id)
        else:
            # If no filter, return empty instead of everything
            return jsonify([]), 200
        
        where_clause = " AND ".join(where_conditions)
        
        query = text(f"""
            SELECT 
                cd.id,
                cd.client_id,
                cd.file_name,
                cd.file_url,
                cd.document_category,
                cd.uploaded_at
            FROM "StreemLyne_MT"."Customer_Documents" cd
            INNER JOIN "StreemLyne_MT"."Client_Master" cm 
                ON cd.client_id = cm.client_id 
                AND cm.tenant_id = :tenant_id
            WHERE {where_clause}
            ORDER BY cd.uploaded_at DESC
        """)
        
        docs = session.execute(query, params).fetchall()
        
        result = []
        for doc in docs:
            result.append({
                'id': str(doc.id),
                'customer_id': doc.client_id,
                'filename': doc.file_name,
                'url': doc.file_url,
                'type': doc.document_category or 'other',
                'created_at': doc.uploaded_at.isoformat() if doc.uploaded_at else None
            })
        
        return jsonify(result), 200
        
    except Exception as e:
        current_app.logger.error(f"Error fetching drawings: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@file_bp.route('/files/drawings/<int:drawing_id>', methods=['GET', 'DELETE'])
@token_required
@require_tenant
def handle_single_drawing_compat(tenant_id, employee_id, drawing_id):
    """Legacy endpoint for /files/drawings/<id> - routes to handle_single_document"""
    session = SessionLocal()
    try:
        # Get document
        query = text("""
            SELECT * FROM "StreemLyne_MT"."Customer_Documents"
            WHERE id = :doc_id
        """)
        
        document = session.execute(query, {'doc_id': drawing_id}).fetchone()
        
        if not document:
            return jsonify({'error': 'Document not found'}), 404
        
        # GET
        if request.method == 'GET':
            return jsonify({
                'id': document.id,
                'client_id': document.client_id,
                'project_id': document.project_id,
                'file_name': document.file_name,
                'file_url': document.file_url,
                'document_category': document.document_category,
                'uploaded_at': document.uploaded_at.isoformat() if document.uploaded_at else None
            }), 200
        
        # DELETE
        elif request.method == 'DELETE':
            delete_query = text("""
                DELETE FROM "StreemLyne_MT"."Customer_Documents"
                WHERE id = :doc_id
                RETURNING id
            """)
            
            result = session.execute(delete_query, {'doc_id': drawing_id})
            deleted = result.fetchone()
            
            if not deleted:
                return jsonify({'error': 'Document not found'}), 404
            
            session.commit()
            
            current_app.logger.info(f"Drawing {drawing_id} deleted successfully")
            
            return jsonify({
                'success': True,
                'message': 'Drawing deleted successfully'
            }), 200

    except Exception as e:
        session.rollback()
        current_app.logger.error(f"Error handling drawing {drawing_id}: {e}", exc_info=True)
        return jsonify({'error': f'Operation failed: {str(e)}'}), 500
    finally:
        session.close()


@file_bp.route('/files/drawings/view/<path:filename>', methods=['GET'])
def view_drawing_compat(filename):
    """Backward compatibility for viewing drawings"""
    return view_document(filename)


@file_bp.route('/files/forms', methods=['GET'])
@token_required
@require_tenant
def handle_forms_compat(tenant_id, employee_id):
    """Get customer form documents"""
    customer_id = request.args.get('customer_id')
    
    session = SessionLocal()
    try:
        query = text("""
            SELECT 
                id,
                client_id,
                file_name,
                file_url,
                document_category,
                uploaded_at
            FROM "StreemLyne_MT"."Customer_Documents"
            WHERE (:customer_id IS NULL OR client_id = :customer_id)
            AND document_category IN ('excel', 'pdf', 'csv')
            ORDER BY uploaded_at DESC
        """)
        
        docs = session.execute(query, {
            'customer_id': customer_id
        }).fetchall()
        
        result = []
        for doc in docs:
            result.append({
                'id': str(doc.id),
                'customer_id': doc.client_id,
                'filename': doc.file_name,
                'url': doc.file_url,
                'type': doc.document_category or 'other',
                'created_at': doc.uploaded_at.isoformat() if doc.uploaded_at else None
            })
        
        return jsonify(result), 200
        
    except Exception as e:
        current_app.logger.error(f"Error fetching form documents: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@file_bp.route('/files/forms/<int:form_id>', methods=['GET', 'PATCH', 'DELETE'])
@token_required
@require_tenant
def handle_single_form_compat(tenant_id, employee_id, form_id):
    """Backward compatibility for single form operations"""
    session = SessionLocal()
    try:
        # Get document
        query = text("""
            SELECT * FROM "StreemLyne_MT"."Customer_Documents"
            WHERE id = :doc_id
        """)
        
        document = session.execute(query, {'doc_id': form_id}).fetchone()
        
        if not document:
            return jsonify({'error': 'Document not found'}), 404
        
        # GET
        if request.method == 'GET':
            return jsonify({
                'id': document.id,
                'client_id': document.client_id,
                'file_name': document.file_name,
                'file_url': document.file_url,
                'document_category': document.document_category,
                'uploaded_at': document.uploaded_at.isoformat() if document.uploaded_at else None
            }), 200
        
        # DELETE
        elif request.method == 'DELETE':
            delete_query = text("""
                DELETE FROM "StreemLyne_MT"."Customer_Documents"
                WHERE id = :doc_id
                RETURNING id
            """)
            
            result = session.execute(delete_query, {'doc_id': form_id})
            deleted = result.fetchone()
            
            if not deleted:
                return jsonify({'error': 'Document not found'}), 404
            
            session.commit()
            
            return jsonify({
                'success': True,
                'message': 'Form document deleted successfully'
            }), 200

    except Exception as e:
        session.rollback()
        current_app.logger.error(f"Error handling form document {form_id}: {e}", exc_info=True)
        return jsonify({'error': f'Operation failed: {str(e)}'}), 500
    finally:
        session.close()

@file_bp.route('/files/forms/view/<path:filename>', methods=['GET'])
def view_form_compat(filename):
    """Backward compatibility for viewing forms"""
    return view_document(filename)