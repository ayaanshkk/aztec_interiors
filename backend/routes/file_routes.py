from flask import request, jsonify, send_file, Blueprint, current_app, redirect, Response
from werkzeug.utils import secure_filename
from datetime import datetime
from sqlalchemy import text, or_
import os
import uuid 
import requests
import cloudinary
import cloudinary.uploader
import cloudinary.api

from ..utils.file_utils import allowed_file
from .auth_helpers import token_required, require_tenant
from ..db import SessionLocal

file_bp = Blueprint('file_routes', __name__)

# ==========================================
# Cloudinary Configuration
# ==========================================

def get_cloudinary_config():
    """Get Cloudinary configuration from environment variables"""
    cloud_name = os.environ.get('CLOUDINARY_CLOUD_NAME') or os.getenv('CLOUDINARY_CLOUD_NAME')
    api_key = os.environ.get('CLOUDINARY_API_KEY') or os.getenv('CLOUDINARY_API_KEY')
    api_secret = os.environ.get('CLOUDINARY_API_SECRET') or os.getenv('CLOUDINARY_API_SECRET')
    
    if not all([cloud_name, api_key, api_secret]):
        return None
    
    return {
        'cloud_name': cloud_name,
        'api_key': api_key,
        'api_secret': api_secret
    }


def ensure_cloudinary_configured():
    """Ensure Cloudinary is configured before upload operations"""
    config = get_cloudinary_config()
    
    if not config:
        error_msg = "Cloudinary configuration is missing. Please set CLOUDINARY_CLOUD_NAME, CLOUDINARY_API_KEY, and CLOUDINARY_API_SECRET environment variables."
        if hasattr(current_app, 'logger'):
            current_app.logger.error(error_msg)
        raise ValueError(error_msg)
    
    cloudinary.config(
        cloud_name=config['cloud_name'],
        api_key=config['api_key'],
        api_secret=config['api_secret'],
        secure=True
    )
    
    if hasattr(current_app, 'logger'):
        current_app.logger.info(f"Cloudinary configured with cloud_name: {config['cloud_name']}")
    
    return True


def upload_file_to_cloudinary(file, filename, client_id, document_category='drawing'):
    """Upload file to Cloudinary and return the URL and public_id"""
    try:
        ensure_cloudinary_configured()
        
        # Create folder structure in Cloudinary
        folder = f"streemlyne/{document_category}/{client_id}"
        
        # Reset file pointer to beginning
        file.seek(0)
        
        # Determine resource type
        file_extension = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
        mime_type = file.mimetype if hasattr(file, 'mimetype') else ''
        
        current_app.logger.info(f"Uploading: {filename}, extension: {file_extension}, mime: {mime_type}")
        
        # Determine resource type
        if file_extension in ['pdf', 'xlsx', 'xls', 'csv', 'doc', 'docx', 'txt', 'zip'] or \
           'pdf' in mime_type.lower() or 'spreadsheet' in mime_type.lower() or \
           'excel' in mime_type.lower() or 'document' in mime_type.lower():
            resource_type = 'raw'
        elif file_extension in ['png', 'jpg', 'jpeg', 'gif', 'webp', 'svg', 'bmp'] or \
             'image' in mime_type.lower():
            resource_type = 'image'
        else:
            resource_type = 'raw'
        
        current_app.logger.info(f"Uploading {filename} as resource_type='{resource_type}'")
        
        # Upload to Cloudinary
        upload_params = {
            'folder': folder,
            'public_id': filename.rsplit('.', 1)[0],
            'resource_type': resource_type,
            'overwrite': False,
            'unique_filename': True
        }
        
        upload_result = cloudinary.uploader.upload(file, **upload_params)
        
        cloudinary_url = upload_result['secure_url']
        public_id = upload_result['public_id']
        
        current_app.logger.info(f"File uploaded to Cloudinary: {public_id}")
        
        return cloudinary_url, public_id
        
    except ValueError as ve:
        current_app.logger.error(f"Cloudinary configuration error: {ve}")
        raise
    except Exception as e:
        current_app.logger.error(f"Error uploading to Cloudinary: {e}", exc_info=True)
        raise Exception(f"Failed to upload file to Cloudinary: {str(e)}")


def delete_file_from_cloudinary(storage_path):
    """Delete a file from Cloudinary"""
    try:
        ensure_cloudinary_configured()
        
        public_id = storage_path
        
        if storage_path and 'cloudinary.com' in storage_path:
            # Extract public_id from URL
            parts = storage_path.split('/upload/')
            if len(parts) > 1:
                path_after_upload = parts[1]
                if path_after_upload.startswith('v') and '/' in path_after_upload:
                    path_after_upload = '/'.join(path_after_upload.split('/')[1:])
                if 'fl_' in path_after_upload:
                    path_parts = path_after_upload.split('/')
                    path_after_upload = '/'.join([p for p in path_parts if not p.startswith('fl_')])
                public_id = path_after_upload.rsplit('.', 1)[0] if '.' in path_after_upload else path_after_upload
        
        current_app.logger.info(f"Deleting from Cloudinary: {public_id}")
        
        # Try different resource types
        result = cloudinary.uploader.destroy(public_id, resource_type='raw')
        
        if result.get('result') not in ['ok', 'not found']:
            result = cloudinary.uploader.destroy(public_id, resource_type='image')
        
        if result.get('result') not in ['ok', 'not found']:
            result = cloudinary.uploader.destroy(public_id, resource_type='video')
        
        success = result.get('result') in ['ok', 'not found']
        
        if success:
            current_app.logger.info(f"File deleted from Cloudinary: {public_id}")
        else:
            current_app.logger.warning(f"Could not delete from Cloudinary: {public_id}")
        
        return success
        
    except ValueError as ve:
        current_app.logger.error(f"Cloudinary configuration error: {ve}")
        return False
    except Exception as e:
        current_app.logger.error(f"Error deleting from Cloudinary: {e}", exc_info=True)
        return False


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
                    'storage_path': doc.storage_path,
                    'document_category': doc.document_category,
                    'category': doc.document_category,  # Backward compatibility
                    'mime_type': doc.mime_type,
                    'uploaded_by': doc.uploaded_by,
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
            
            # Upload to Cloudinary
            cloudinary_url, public_id = upload_file_to_cloudinary(
                file, unique_filename, client_id, document_category
            )
            
            # Get uploaded_by
            uploaded_by = 'System'
            if hasattr(request, 'current_user') and request.current_user:
                if hasattr(request.current_user, 'full_name'):
                    uploaded_by = request.current_user.full_name
                elif hasattr(request.current_user, 'username'):
                    uploaded_by = request.current_user.username
            
            # Determine MIME type
            mime_type = file.mimetype if hasattr(file, 'mimetype') else 'application/octet-stream'
            
            # Create database record
            insert_query = text("""
                INSERT INTO "StreemLyne_MT"."Customer_Documents"
                (client_id, project_id, opportunity_id, property_id,
                 file_name, file_url, storage_path, document_category,
                 mime_type, uploaded_by)
                VALUES (:client_id, :project_id, :opportunity_id, :property_id,
                        :file_name, :file_url, :storage_path, :category,
                        :mime_type, :uploaded_by)
                RETURNING id
            """)
            
            result = session.execute(insert_query, {
                'client_id': int(client_id),
                'project_id': int(project_id) if project_id else None,
                'opportunity_id': int(opportunity_id) if opportunity_id else None,
                'property_id': int(property_id) if property_id else None,
                'file_name': filename,
                'file_url': cloudinary_url,
                'storage_path': cloudinary_url,
                'category': document_category,
                'mime_type': mime_type,
                'uploaded_by': uploaded_by
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
                    'file_url': cloudinary_url,
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
                'mime_type': document.mime_type,
                'uploaded_by': document.uploaded_by,
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
            # Delete from Cloudinary
            if document.storage_path:
                delete_file_from_cloudinary(document.storage_path)
            
            # Delete from database
            delete_query = text("""
                DELETE FROM "StreemLyne_MT"."Customer_Documents"
                WHERE id = :doc_id
            """)
            
            session.execute(delete_query, {'doc_id': document_id})
            session.commit()
            
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
    """Serve document from Cloudinary"""
    session = SessionLocal()
    try:
        # Look up document by filename
        query = text("""
            SELECT * FROM "StreemLyne_MT"."Customer_Documents"
            WHERE file_name LIKE :filename
               OR file_url LIKE :filename
               OR storage_path LIKE :filename
            LIMIT 1
        """)
        
        document = session.execute(query, {
            'filename': f'%{filename}%'
        }).fetchone()
        
        if not document:
            return jsonify({'error': 'File not found'}), 404
        
        cloudinary_url = document.file_url or document.storage_path
        
        # Check if it's a PDF
        is_pdf = '.pdf' in cloudinary_url.lower() or document.mime_type == 'application/pdf'
        
        if is_pdf:
            # Fetch PDF and serve with inline disposition
            response = requests.get(cloudinary_url, timeout=30)
            
            if response.status_code == 200:
                return Response(
                    response.content,
                    mimetype='application/pdf',
                    headers={
                        'Content-Disposition': f'inline; filename="{document.file_name}"',
                        'Content-Type': 'application/pdf',
                        'Cache-Control': 'public, max-age=3600'
                    }
                )
            else:
                return jsonify({'error': 'Failed to fetch PDF'}), 500
        else:
            # Redirect to Cloudinary for other files
            return redirect(cloudinary_url)
        
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
            AND (document_category IN ('pdf', 'image', 'drawing') OR document_category IS NULL)
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
        current_app.logger.error(f"Error fetching drawings: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@file_bp.route('/files/drawings/<int:drawing_id>', methods=['GET', 'PATCH', 'DELETE'])
@token_required
@require_tenant
def handle_single_drawing_compat(drawing_id, tenant_id, employee_id):
    """Backward compatibility for single drawing operations"""
    return handle_single_document(drawing_id, tenant_id, employee_id)


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
def handle_single_form_compat(form_id, tenant_id, employee_id):
    """Backward compatibility for single form operations"""
    return handle_single_document(form_id, tenant_id, employee_id)


@file_bp.route('/files/forms/view/<path:filename>', methods=['GET'])
def view_form_compat(filename):
    """Backward compatibility for viewing forms"""
    return view_document(filename)