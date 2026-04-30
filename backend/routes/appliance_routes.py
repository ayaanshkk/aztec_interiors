# routes/appliance_routes.py (Simplified - Single Table)
from flask import Blueprint, request, jsonify, current_app
from sqlalchemy import text
from ..db import SessionLocal
from .auth_helpers import token_required, require_tenant

from datetime import datetime
import json
import pandas as pd
from werkzeug.utils import secure_filename
import os
import threading

appliance_bp = Blueprint('appliances', __name__)

def serialize_product(product_row):
    """Serialize product row to dictionary"""
    return {
        'id': product_row.appliance_id,
        'model_code': product_row.model_code,
        'name': product_row.name,
        'description': product_row.description,
        'series': product_row.series,
        'brand_name': product_row.brand_name,
        'category_name': product_row.category_name,
        'pricing': {
            'base_price': float(product_row.base_price) if product_row.base_price else None,
            'low_tier_price': float(product_row.low_tier_price) if product_row.low_tier_price else None,
            'mid_tier_price': float(product_row.mid_tier_price) if product_row.mid_tier_price else None,
            'high_tier_price': float(product_row.high_tier_price) if product_row.high_tier_price else None,
        },
        'dimensions': product_row.dimensions if product_row.dimensions else {},
        'weight': float(product_row.weight) if product_row.weight else None,
        'color_options': product_row.color_options if product_row.color_options else [],
        'pack_name': product_row.pack_name,
        'notes': product_row.notes,
        'energy_rating': product_row.energy_rating,
        'warranty_years': product_row.warranty_years,
        'active': product_row.active,
        'in_stock': product_row.in_stock,
        'lead_time_weeks': product_row.lead_time_weeks,
        'created_at': product_row.created_at.isoformat() if product_row.created_at else None,
        'updated_at': product_row.updated_at.isoformat() if product_row.updated_at else None,
    }


def safe_read_csv(file_path, **kwargs):
    """Safely read CSV with support for both old and new pandas versions"""
    try:
        return pd.read_csv(file_path, **kwargs, on_bad_lines='skip')
    except TypeError:
        kwargs_old = {k: v for k, v in kwargs.items() if k not in ['on_bad_lines']}
        return pd.read_csv(file_path, **kwargs_old, error_bad_lines=False, warn_bad_lines=False)


def process_import_file(app, import_id, file_path, import_type, tenant_id):
    """Process import file in background thread"""
    with app.app_context():
        session = SessionLocal()
        
        try:
            app.logger.info(f"Starting import processing for {import_id}: {file_path}")

            if not os.path.exists(file_path):
                update_query = text("""
                    UPDATE "StreemLyne_MT"."Data_Imports"
                    SET status = 'failed', error_log = :error_log, completed_at = :completed_at
                    WHERE import_id = :import_id
                """)
                session.execute(update_query, {
                    'error_log': f"File not found: {file_path}",
                    'completed_at': datetime.utcnow(),
                    'import_id': import_id
                })
                session.commit()
                session.close()
                return

            processed_count = 0
            failed_count = 0
            error_log = []

            if import_type == 'appliance_matrix':
                
                # Sniff for brand
                if file_path.endswith(('.xlsx', '.xls')):
                    df_sniff = pd.read_excel(file_path, header=None)
                else:
                    df_sniff = safe_read_csv(file_path, header=None, encoding='utf-8')

                brand_name = "Unknown"
                brands_to_check = ['Bosch', 'Neff', 'Siemens']
                for r_idx, row in df_sniff.head(5).iterrows():
                    for c_idx, cell in row.items():
                        if isinstance(cell, str):
                            for brand in brands_to_check:
                                if brand.lower() in cell.lower():
                                    brand_name = brand
                                    break
                    if brand_name != "Unknown":
                        break

                # Reload DataFrame with correct header
                if file_path.endswith(('.xlsx', '.xls')):
                    df = pd.read_excel(file_path, header=4)
                else:
                    df = safe_read_csv(file_path, header=4, encoding='utf-8')

                # Process rows
                for index, row in df.iterrows():
                    try:
                        category_name = str(row.iloc[0]).strip()
                        if pd.isna(category_name) or category_name == '':
                            continue

                        # Helper to process entry
                        def process_entry(model_codes_str, series, price, tier):
                            entry_count = 0
                            if pd.isna(model_codes_str) or str(model_codes_str).strip() == '':
                                return 0
                            
                            model_codes = [mc.strip() for mc in str(model_codes_str).split('/') if mc.strip()]
                            
                            for model_code in model_codes:
                                # Check if product exists
                                product_query = text("""
                                    SELECT appliance_id FROM "StreemLyne_MT"."Appliance_Master"
                                    WHERE model_code = :model_code AND tenant_id = :tenant_id
                                """)
                                product = session.execute(product_query, {
                                    'model_code': model_code,
                                    'tenant_id': str(tenant_id)
                                }).fetchone()
                                
                                numeric_price = pd.to_numeric(price, errors='coerce')
                                
                                if not product:
                                    # Insert new product
                                    insert_product = text("""
                                        INSERT INTO "StreemLyne_MT"."Appliance_Master"
                                        (tenant_id, model_code, name, brand_name, category_name, series,
                                         base_price, low_tier_price, mid_tier_price, high_tier_price, active, in_stock)
                                        VALUES (:tenant_id, :model_code, :name, :brand_name, :category_name, :series,
                                                :base_price, :low_price, :mid_price, :high_price, true, true)
                                    """)
                                    session.execute(insert_product, {
                                        'tenant_id': str(tenant_id),
                                        'model_code': model_code,
                                        'name': category_name,
                                        'brand_name': brand_name,
                                        'category_name': category_name,
                                        'series': str(series) if pd.notna(series) else None,
                                        'base_price': numeric_price if pd.notna(numeric_price) else None,
                                        'low_price': numeric_price if tier == 'low' and pd.notna(numeric_price) else None,
                                        'mid_price': numeric_price if tier == 'mid' and pd.notna(numeric_price) else None,
                                        'high_price': numeric_price if tier == 'high' and pd.notna(numeric_price) else None
                                    })
                                else:
                                    # Update existing product
                                    update_parts = [
                                        "brand_name = :brand_name",
                                        "category_name = :category_name",
                                        "name = :name"
                                    ]
                                    params = {
                                        'appliance_id': product.appliance_id,
                                        'brand_name': brand_name,
                                        'category_name': category_name,
                                        'name': category_name
                                    }
                                    
                                    if pd.notna(series):
                                        update_parts.append("series = :series")
                                        params['series'] = str(series)
                                    
                                    if pd.notna(numeric_price):
                                        if tier == 'low':
                                            update_parts.append("low_tier_price = :price")
                                        elif tier == 'mid':
                                            update_parts.append("mid_tier_price = :price")
                                        elif tier == 'high':
                                            update_parts.append("high_tier_price = :price")
                                        params['price'] = numeric_price
                                        
                                        update_parts.append("""
                                            base_price = CASE 
                                                WHEN base_price IS NULL OR :price < base_price 
                                                THEN :price 
                                                ELSE base_price 
                                            END
                                        """)
                                    
                                    update_query = text(f"""
                                        UPDATE "StreemLyne_MT"."Appliance_Master"
                                        SET {', '.join(update_parts)}
                                        WHERE appliance_id = :appliance_id
                                    """)
                                    session.execute(update_query, params)
                                
                                entry_count += 1
                            return entry_count

                        # Process LOW, MID, HIGH tiers
                        processed_count += process_entry(row.iloc[1], row.iloc[2], row.iloc[3], 'low')
                        processed_count += process_entry(row.iloc[5], row.iloc[6], row.iloc[7], 'mid')
                        processed_count += process_entry(row.iloc[9], row.iloc[10], row.iloc[11], 'high')
                        
                        session.commit()

                    except Exception as row_e:
                        session.rollback()
                        failed_count += 1
                        error_log.append(f"Row {index + 6}: {str(row_e)}")
                        app.logger.error(f"Error processing row {index + 6}: {row_e}")

            # Update import status
            update_query = text("""
                UPDATE "StreemLyne_MT"."Data_Imports"
                SET status = 'completed',
                    records_processed = :processed,
                    records_failed = :failed,
                    error_log = :error_log,
                    completed_at = :completed_at
                WHERE import_id = :import_id
            """)
            session.execute(update_query, {
                'processed': processed_count,
                'failed': failed_count,
                'error_log': "\n".join(error_log) if error_log else None,
                'completed_at': datetime.utcnow(),
                'import_id': import_id
            })
            session.commit()
            app.logger.info(f"Import {import_id} completed: {processed_count} processed, {failed_count} failed")
            
        except Exception as e:
            session.rollback()
            update_query = text("""
                UPDATE "StreemLyne_MT"."Data_Imports"
                SET status = 'failed', error_log = :error_log, completed_at = :completed_at
                WHERE import_id = :import_id
            """)
            session.execute(update_query, {
                'error_log': f"Fatal Error: {str(e)}",
                'completed_at': datetime.utcnow(),
                'import_id': import_id
            })
            session.commit()
            app.logger.exception(f"Fatal error in import {import_id}: {e}")
        
        finally:
            session.close()


# Product endpoints
@appliance_bp.route('/products', methods=['GET'])
@token_required
@require_tenant
def get_products(tenant_id, employee_id):
    """Get all products with filtering and search"""
    session = SessionLocal()
    try:
        search = request.args.get('search', '')
        brand_name = request.args.get('brand_name')
        category_name = request.args.get('category_name')
        series = request.args.get('series')
        tier = request.args.get('tier')
        active_only = request.args.get('active_only', 'true').lower() == 'true'
        page = request.args.get('page', 1, type=int)
        per_page = min(request.args.get('per_page', 50, type=int), 100)
        offset = (page - 1) * per_page
        
        # Build WHERE conditions
        where_conditions = ["tenant_id = :tenant_id"]
        params = {'tenant_id': str(tenant_id)}
        
        if active_only:
            where_conditions.append("active = true")
        
        if search:
            where_conditions.append("""
                (name ILIKE :search OR model_code ILIKE :search OR series ILIKE :search OR brand_name ILIKE :search)
            """)
            params['search'] = f"%{search}%"
        
        if brand_name:
            where_conditions.append("brand_name = :brand_name")
            params['brand_name'] = brand_name
        
        if category_name:
            where_conditions.append("category_name = :category_name")
            params['category_name'] = category_name
        
        if series:
            where_conditions.append("series ILIKE :series")
            params['series'] = f"%{series}%"
        
        if tier == 'low':
            where_conditions.append("low_tier_price IS NOT NULL")
        elif tier == 'mid':
            where_conditions.append("mid_tier_price IS NOT NULL")
        elif tier == 'high':
            where_conditions.append("high_tier_price IS NOT NULL")
        
        where_clause = " AND ".join(where_conditions)
        
        # Count total
        count_query = text(f"""
            SELECT COUNT(*) as total
            FROM "StreemLyne_MT"."Appliance_Master"
            WHERE {where_clause}
        """)
        total = session.execute(count_query, params).fetchone().total
        
        # Get products
        query = text(f"""
            SELECT *
            FROM "StreemLyne_MT"."Appliance_Master"
            WHERE {where_clause}
            ORDER BY brand_name, series, model_code
            LIMIT :limit OFFSET :offset
        """)
        
        params['limit'] = per_page
        params['offset'] = offset
        
        result = session.execute(query, params)
        products = result.fetchall()
        
        return jsonify({
            'products': [serialize_product(p) for p in products],
            'pagination': {
                'page': page,
                'per_page': per_page,
                'total': total,
                'pages': (total + per_page - 1) // per_page,
                'has_next': offset + per_page < total,
                'has_prev': page > 1
            }
        })
    except Exception as e:
        current_app.logger.error(f"Error fetching products: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@appliance_bp.route('/products/<int:product_id>', methods=['GET'])
@token_required
@require_tenant
def get_product(product_id, tenant_id, employee_id):
    """Get a specific product by ID"""
    session = SessionLocal()
    try:
        query = text("""
            SELECT * FROM "StreemLyne_MT"."Appliance_Master"
            WHERE appliance_id = :product_id AND tenant_id = :tenant_id
        """)
        
        product = session.execute(query, {
            'product_id': product_id,
            'tenant_id': str(tenant_id)
        }).fetchone()
        
        if not product:
            return jsonify({'error': 'Product not found'}), 404
            
        return jsonify(serialize_product(product))
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@appliance_bp.route('/products', methods=['POST'])
@token_required
@require_tenant
def create_product(tenant_id, employee_id):
    """Create a new product"""
    session = SessionLocal()
    try:
        data = request.get_json()
        
        required_fields = ['model_code', 'name', 'brand_name', 'category_name']
        for field in required_fields:
            if not data.get(field):
                return jsonify({'error': f'{field} is required'}), 400
        
        # Check if model code exists
        check_query = text("""
            SELECT appliance_id FROM "StreemLyne_MT"."Appliance_Master"
            WHERE model_code = :model_code AND tenant_id = :tenant_id
        """)
        existing = session.execute(check_query, {
            'model_code': data['model_code'],
            'tenant_id': str(tenant_id)
        }).fetchone()
        
        if existing:
            return jsonify({'error': 'Model code already exists'}), 400
        
        insert_query = text("""
            INSERT INTO "StreemLyne_MT"."Appliance_Master"
            (tenant_id, model_code, name, description, brand_name, category_name, series,
             base_price, low_tier_price, mid_tier_price, high_tier_price,
             dimensions, weight, color_options, pack_name, notes, energy_rating,
             warranty_years, active, in_stock, lead_time_weeks)
            VALUES (:tenant_id, :model_code, :name, :description, :brand_name, :category_name, :series,
                    :base_price, :low_tier_price, :mid_tier_price, :high_tier_price,
                    :dimensions, :weight, :color_options, :pack_name, :notes, :energy_rating,
                    :warranty_years, :active, :in_stock, :lead_time_weeks)
            RETURNING appliance_id
        """)
        
        result = session.execute(insert_query, {
            'tenant_id': str(tenant_id),
            'model_code': data['model_code'],
            'name': data['name'],
            'description': data.get('description'),
            'brand_name': data['brand_name'],
            'category_name': data['category_name'],
            'series': data.get('series'),
            'base_price': data.get('base_price'),
            'low_tier_price': data.get('low_tier_price'),
            'mid_tier_price': data.get('mid_tier_price'),
            'high_tier_price': data.get('high_tier_price'),
            'dimensions': json.dumps(data.get('dimensions', {})),
            'weight': data.get('weight'),
            'color_options': json.dumps(data.get('color_options', [])),
            'pack_name': data.get('pack_name'),
            'notes': data.get('notes'),
            'energy_rating': data.get('energy_rating'),
            'warranty_years': data.get('warranty_years'),
            'active': data.get('active', True),
            'in_stock': data.get('in_stock', True),
            'lead_time_weeks': data.get('lead_time_weeks')
        })
        
        product_id = result.fetchone().appliance_id
        session.commit()
        
        return get_product(product_id, tenant_id, employee_id)
        
    except Exception as e:
        session.rollback()
        current_app.logger.exception(f"Error creating product: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@appliance_bp.route('/products/<int:product_id>', methods=['PUT'])
@token_required
@require_tenant
def update_product(product_id, tenant_id, employee_id):
    """Update an existing product"""
    session = SessionLocal()
    try:
        data = request.get_json()
        
        update_fields = []
        params = {'product_id': product_id, 'tenant_id': str(tenant_id)}
        
        updatable = {
            'name': 'name', 'description': 'description', 'series': 'series',
            'brand_name': 'brand_name', 'category_name': 'category_name',
            'base_price': 'base_price', 'low_tier_price': 'low_tier_price',
            'mid_tier_price': 'mid_tier_price', 'high_tier_price': 'high_tier_price',
            'weight': 'weight', 'pack_name': 'pack_name', 'notes': 'notes',
            'energy_rating': 'energy_rating', 'warranty_years': 'warranty_years',
            'active': 'active', 'in_stock': 'in_stock', 'lead_time_weeks': 'lead_time_weeks'
        }
        
        for key, col in updatable.items():
            if key in data:
                update_fields.append(f"{col} = :{key}")
                params[key] = data[key]
        
        if 'dimensions' in data:
            update_fields.append("dimensions = :dimensions")
            params['dimensions'] = json.dumps(data['dimensions'])
        
        if 'color_options' in data:
            update_fields.append("color_options = :color_options")
            params['color_options'] = json.dumps(data['color_options'])
        
        if not update_fields:
            return jsonify({'error': 'No fields to update'}), 400
        
        update_query = text(f"""
            UPDATE "StreemLyne_MT"."Appliance_Master"
            SET {', '.join(update_fields)}
            WHERE appliance_id = :product_id AND tenant_id = :tenant_id
            RETURNING appliance_id
        """)
        
        result = session.execute(update_query, params)
        updated = result.fetchone()
        
        if not updated:
            return jsonify({'error': 'Product not found'}), 404
        
        session.commit()
        
        return get_product(product_id, tenant_id, employee_id)
        
    except Exception as e:
        session.rollback()
        current_app.logger.exception(f"Error updating product: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@appliance_bp.route('/products/<int:product_id>', methods=['DELETE'])
@token_required
@require_tenant
def delete_product(product_id, tenant_id, employee_id):
    """Delete a product (soft delete)"""
    session = SessionLocal()
    try:
        query = text("""
            UPDATE "StreemLyne_MT"."Appliance_Master"
            SET active = false
            WHERE appliance_id = :product_id AND tenant_id = :tenant_id
            RETURNING appliance_id
        """)
        
        result = session.execute(query, {
            'product_id': product_id,
            'tenant_id': str(tenant_id)
        })
        
        if not result.fetchone():
            return jsonify({'error': 'Product not found'}), 404
        
        session.commit()
        return jsonify({'message': 'Product deactivated successfully'})
        
    except Exception as e:
        session.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


# Get unique brands
@appliance_bp.route('/brands', methods=['GET'])
@token_required
@require_tenant
def get_brands(tenant_id, employee_id):
    """Get unique brand names"""
    session = SessionLocal()
    try:
        query = text("""
            SELECT DISTINCT brand_name, COUNT(*) as product_count
            FROM "StreemLyne_MT"."Appliance_Master"
            WHERE tenant_id = :tenant_id AND active = true
            GROUP BY brand_name
            ORDER BY brand_name
        """)
        
        brands = session.execute(query, {'tenant_id': str(tenant_id)}).fetchall()
        
        return jsonify([{
            'name': b.brand_name,
            'product_count': b.product_count
        } for b in brands])
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


# Get unique categories
@appliance_bp.route('/categories', methods=['GET'])
@token_required
@require_tenant
def get_categories(tenant_id, employee_id):
    """Get unique category names"""
    session = SessionLocal()
    try:
        query = text("""
            SELECT DISTINCT category_name, COUNT(*) as product_count
            FROM "StreemLyne_MT"."Appliance_Master"
            WHERE tenant_id = :tenant_id AND active = true
            GROUP BY category_name
            ORDER BY category_name
        """)
        
        categories = session.execute(query, {'tenant_id': str(tenant_id)}).fetchall()
        
        return jsonify([{
            'name': c.category_name,
            'product_count': c.product_count
        } for c in categories])
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@appliance_bp.route('/products/search', methods=['GET'])
@token_required
@require_tenant
def search_products(tenant_id, employee_id):
    """Search products with autocomplete support"""
    session = SessionLocal()
    try:
        query_text = request.args.get('q', '')
        limit = min(request.args.get('limit', 10, type=int), 50)
        
        if len(query_text) < 2:
            return jsonify([])
        
        query = text("""
            SELECT *
            FROM "StreemLyne_MT"."Appliance_Master"
            WHERE tenant_id = :tenant_id
                AND active = true
                AND (name ILIKE :search OR model_code ILIKE :search OR series ILIKE :search OR brand_name ILIKE :search)
            ORDER BY brand_name, series, model_code
            LIMIT :limit
        """)
        
        products = session.execute(query, {
            'tenant_id': str(tenant_id),
            'search': f"%{query_text}%",
            'limit': limit
        }).fetchall()
        
        return jsonify([{
            'id': p.appliance_id,
            'model_code': p.model_code,
            'name': p.name,
            'brand_name': p.brand_name,
            'series': p.series,
            'base_price': float(p.base_price) if p.base_price else None,
            'category_name': p.category_name
        } for p in products])
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@appliance_bp.route('/import/upload', methods=['POST'])
@token_required
@require_tenant
def upload_import_file(tenant_id, employee_id):
    """Upload file for data import"""
    session = SessionLocal()
    try:
        if 'file' not in request.files:
            return jsonify({'error': 'No file provided'}), 400
        
        file = request.files['file']
        import_type = request.form.get('import_type', 'appliance_matrix')
        
        if file.filename == '':
            return jsonify({'error': 'No file selected'}), 400
        
        if not file.filename.lower().endswith(('.xlsx', '.xls', '.csv')):
            return jsonify({'error': 'Invalid file type'}), 400
        
        filename = secure_filename(file.filename)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"{timestamp}_{filename}"
        
        upload_folder = current_app.config.get('UPLOAD_FOLDER', 'uploads')
        os.makedirs(upload_folder, exist_ok=True)
        file_path = os.path.join(upload_folder, filename)
        file.save(file_path)
        
        insert_query = text("""
            INSERT INTO "StreemLyne_MT"."Data_Imports"
            (tenant_id, filename, import_type, imported_by, status)
            VALUES (:tenant_id, :filename, :import_type, :imported_by, 'pending')
            RETURNING import_id
        """)
        
        result = session.execute(insert_query, {
            'tenant_id': str(tenant_id),
            'filename': filename,
            'import_type': import_type,
            'imported_by': str(employee_id)
        })
        
        import_id = result.fetchone().import_id
        session.commit()

        worker_thread = threading.Thread(
            target=process_import_file,
            args=(current_app._get_current_object(), import_id, file_path, import_type, tenant_id)
        )
        worker_thread.daemon = True
        worker_thread.start()

        return jsonify({
            'import_id': import_id,
            'filename': filename,
            'message': 'File uploaded. Processing started.'
        }), 201
        
    except Exception as e:
        session.rollback()
        current_app.logger.exception(f"Error uploading import file: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@appliance_bp.route('/import/<int:import_id>/status', methods=['GET'])
@token_required
@require_tenant
def get_import_status(import_id, tenant_id, employee_id):
    """Get status of data import"""
    session = SessionLocal()
    try:
        query = text("""
            SELECT * FROM "StreemLyne_MT"."Data_Imports"
            WHERE import_id = :import_id AND tenant_id = :tenant_id
        """)
        
        import_record = session.execute(query, {
            'import_id': import_id,
            'tenant_id': str(tenant_id)
        }).fetchone()
        
        if not import_record:
            return jsonify({'error': 'Import record not found'}), 404
            
        return jsonify({
            'id': import_record.import_id,
            'filename': import_record.filename,
            'import_type': import_record.import_type,
            'status': import_record.status,
            'records_processed': import_record.records_processed,
            'records_failed': import_record.records_failed,
            'error_log': import_record.error_log,
            'created_at': import_record.created_at.isoformat(),
            'completed_at': import_record.completed_at.isoformat() if import_record.completed_at else None
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()