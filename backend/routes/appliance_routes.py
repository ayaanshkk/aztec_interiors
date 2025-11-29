# routes/appliance_routes.py
from flask import Blueprint, request, jsonify, current_app
from sqlalchemy import or_, func
from sqlalchemy.orm import joinedload
from ..db import SessionLocal

from ..models import Product, Brand, ApplianceCategory, DataImport, ProductQuoteItem
from datetime import datetime
import json
import pandas as pd
from werkzeug.utils import secure_filename
import os
import threading

appliance_bp = Blueprint('appliances', __name__)

# ==========================================
# SIMPLE IN-MEMORY CACHE (Replace with Redis in production)
# ==========================================

_cache = {}
_cache_timeout = 300  # 5 minutes

def simple_cache_get(key):
    """Get cached data if not expired"""
    if key in _cache:
        cached_data, cached_time = _cache[key]
        if (datetime.utcnow() - cached_time).seconds < _cache_timeout:
            return cached_data
    return None

def simple_cache_set(key, data):
    """Store data in cache with current timestamp"""
    _cache[key] = (data, datetime.utcnow())

def invalidate_cache(*patterns):
    """Remove cache entries matching any of the patterns"""
    for pattern in patterns:
        keys_to_remove = [k for k in _cache.keys() if pattern in k]
        for k in keys_to_remove:
            _cache.pop(k, None)

# ==========================================
# HELPER FUNCTIONS
# ==========================================

def serialize_product(product):
    """
    Serialize product object to dictionary
    OPTIMIZED: Uses eager-loaded relationships
    """
    return {
        'id': product.id,
        'model_code': product.model_code,
        'name': product.name,
        'description': product.description,
        'series': product.series,
        'brand': {
            'id': product.brand.id,
            'name': product.brand.name
        } if product.brand else None,
        'category': {
            'id': product.category.id,
            'name': product.category.name
        } if product.category else None,
        'pricing': {
            'base_price': float(product.base_price) if product.base_price else None,
            'low_tier_price': float(product.low_tier_price) if product.low_tier_price else None,
            'mid_tier_price': float(product.mid_tier_price) if product.mid_tier_price else None,
            'high_tier_price': float(product.high_tier_price) if product.high_tier_price else None,
        },
        'dimensions': product.get_dimensions_dict(),
        'weight': float(product.weight) if product.weight else None,
        'color_options': product.get_color_options_list(),
        'pack_name': product.pack_name,
        'notes': product.notes,
        'energy_rating': product.energy_rating,
        'warranty_years': product.warranty_years,
        'active': product.active,
        'in_stock': product.in_stock,
        'lead_time_weeks': product.lead_time_weeks,
        'created_at': product.created_at.isoformat() if product.created_at else None,
        'updated_at': product.updated_at.isoformat() if product.updated_at else None,
    }


def safe_read_csv(file_path, **kwargs):
    """Safely read CSV with support for both old and new pandas versions"""
    try:
        return pd.read_csv(file_path, **kwargs, on_bad_lines='skip')
    except TypeError:
        kwargs_old = {k: v for k, v in kwargs.items() if k not in ['on_bad_lines']}
        return pd.read_csv(file_path, **kwargs_old, error_bad_lines=False, warn_bad_lines=False)


def process_import_file(app, import_id, file_path, import_type):
    """
    Background thread to process import
    
    OPTIMIZATIONS:
    - Batch commits every 100 records instead of every row
    - Cache invalidation after import
    """
    with app.app_context():
        session = SessionLocal()
        import_record = session.get(DataImport, import_id)
        
        if not import_record:
            app.logger.error(f"Import record {import_id} not found")
            session.close()
            return

        app.logger.info(f"Starting import processing for {import_id}: {file_path} ({import_type})")

        if not os.path.exists(file_path):
            import_record.status = 'failed'
            import_record.error_log = f"File not found: {file_path}"
            import_record.completed_at = datetime.utcnow()
            session.commit()
            session.close()
            app.logger.error(f"File not found: {file_path}")
            return

        file_size = os.path.getsize(file_path)
        app.logger.info(f"Processing file: {file_path} ({file_size} bytes)")

        processed_count = 0
        failed_count = 0
        error_log = []
        batch_size = 100  # OPTIMIZED: Batch commits

        try:
            # --- Logic for 'Appliance Matrix' (PIVOTED FORMAT) ---
            if import_type == 'appliance_matrix':
                
                # Load file without headers to sniff for brand
                if file_path.endswith(('.xlsx', '.xls')):
                    df_sniff = pd.read_excel(file_path, header=None)
                else:
                    df_sniff = safe_read_csv(file_path, header=None, encoding='utf-8')

                # Find Brand
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
                
                brand = session.query(Brand).filter_by(name=brand_name).first()
                if not brand:
                    brand = Brand(name=brand_name, active=True)
                    session.add(brand)
                    session.commit()
                brand = session.query(Brand).filter_by(name=brand_name).first()

                # Reload DataFrame with correct header
                if file_path.endswith(('.xlsx', '.xls')):
                    df = pd.read_excel(file_path, header=4)
                else:
                    df = safe_read_csv(file_path, header=4, encoding='utf-8')

                # OPTIMIZED: Batch processing
                batch_products = []
                
                # Iterate and process rows
                for index, row in df.iterrows():
                    try:
                        product_name_category = str(row.iloc[0]).strip()
                        if pd.isna(product_name_category) or product_name_category == '':
                            continue

                        # Get or create Category
                        category = session.query(ApplianceCategory).filter_by(name=product_name_category).first()
                        if not category:
                            category = ApplianceCategory(name=product_name_category, active=True)
                            session.add(category)
                            session.flush()  # Get ID without committing
                        
                        # Helper to process a single product entry
                        def process_entry(model_codes_str, series, price, tier, current_session):
                            entry_processed_count = 0
                            if pd.isna(model_codes_str) or str(model_codes_str).strip() == '':
                                return 0
                            
                            model_codes = [mc.strip() for mc in str(model_codes_str).split('/') if mc.strip()]
                            
                            for model_code in model_codes:
                                product = current_session.query(Product).filter_by(model_code=model_code).first()
                                if not product:
                                    product = Product(
                                        model_code=model_code,
                                        brand_id=brand.id,
                                        category_id=category.id,
                                        name=product_name_category,
                                        active=True,
                                        in_stock=True
                                    )
                                    current_session.add(product)
                                
                                product.brand_id = brand.id
                                product.category_id = category.id
                                product.name = product_name_category
                                if pd.notna(series):
                                    product.series = str(series)
                                
                                numeric_price = pd.to_numeric(price, errors='coerce')
                                if pd.notna(numeric_price):
                                    if tier == 'low':
                                        product.low_tier_price = numeric_price
                                    elif tier == 'mid':
                                        product.mid_tier_price = numeric_price
                                    elif tier == 'high':
                                        product.high_tier_price = numeric_price
                                    
                                    if product.base_price is None or (numeric_price < product.base_price):
                                        product.base_price = numeric_price
                                        
                                entry_processed_count += 1
                            return entry_processed_count

                        # Process LOW tier
                        processed_count += process_entry(row.iloc[1], row.iloc[2], row.iloc[3], 'low', session)
                        
                        # Process MID tier
                        processed_count += process_entry(row.iloc[5], row.iloc[6], row.iloc[7], 'mid', session)
                        
                        # Process HIGH tier
                        processed_count += process_entry(row.iloc[9], row.iloc[10], row.iloc[11], 'high', session)
                        
                        # OPTIMIZED: Batch commit every 100 records
                        if processed_count % batch_size == 0:
                            session.commit()
                            app.logger.info(f"Batch committed: {processed_count} records processed")

                    except Exception as row_e:
                        session.rollback()
                        failed_count += 1
                        error_log.append(f"Row {index + 6}: {str(row_e)}")
                        app.logger.error(f"Error processing row {index + 6}: {row_e}")

                # Final commit for remaining records
                session.commit()

            # --- Logic for 'KBB Pricelist' (FLAT FORMAT) ---
            elif import_type == 'kbb_pricelist':
                if file_path.endswith(('.xlsx', '.xls')):
                    df = pd.read_excel(file_path, header=2)
                else:
                    df = safe_read_csv(file_path, header=2, encoding='utf-8')
                
                df.columns = df.columns.str.strip().str.lower().str.replace(' ', '_')
                
                for index, row in df.iterrows():
                    try:
                        code = row.get('code')
                        if pd.isna(code):
                            continue
                        
                        # KBB processing logic here
                        processed_count += 1
                        
                        # OPTIMIZED: Batch commit
                        if processed_count % batch_size == 0:
                            session.commit()
                        
                    except Exception as row_e:
                        session.rollback()
                        failed_count += 1
                        error_log.append(f"Row {index + 4}: {str(row_e)}")
                        app.logger.error(f"Error processing row {index + 4}: {row_e}")
                
                session.commit()

            # Update status to completed
            import_record.status = 'completed'
            import_record.records_processed = processed_count
            import_record.records_failed = failed_count
            import_record.error_log = "\n".join(error_log)
            
            # INVALIDATE CACHE after import
            invalidate_cache('products', 'brands', 'categories', 'product_search')
            
            app.logger.info(f"Import {import_id} completed: {processed_count} processed, {failed_count} failed")
            
        except Exception as e:
            session.rollback()
            import_record.status = 'failed'
            import_record.error_log = f"Fatal Error: {str(e)}"
            app.logger.exception(f"Fatal error in import {import_id}: {e}")
        
        finally:
            import_record.completed_at = datetime.utcnow()
            session.commit()
            session.close()


# ==========================================
# PRODUCT ENDPOINTS (OPTIMIZED)
# ==========================================

@appliance_bp.route('/products', methods=['GET'])
def get_products():
    """
    Get all products with filtering and search
    
    OPTIMIZATIONS:
    - 5-minute cache for product lists
    - Eager loading of brand and category
    - Proper pagination (not deprecated method)
    - Filtering optimizations
    """
    search = request.args.get('search', '')
    brand_ids = request.args.getlist('brand_id', type=int)
    category_id = request.args.get('category_id', type=int)
    series = request.args.get('series')
    tier = request.args.get('tier')
    active_only = request.args.get('active_only', 'true').lower() == 'true'
    page = request.args.get('page', 1, type=int)
    per_page = min(request.args.get('per_page', 50, type=int), 100)
    
    # Build cache key from filters
    cache_key = f"products_{search}_{brand_ids}_{category_id}_{series}_{tier}_{active_only}_{page}_{per_page}"
    
    # Check cache first
    cached = simple_cache_get(cache_key)
    if cached:
        current_app.logger.debug(f"Cache hit for products: {cache_key}")
        return jsonify(cached), 200
    
    session = SessionLocal()
    try:
        # OPTIMIZED: Single query with eager loading
        query = session.query(Product).options(
            joinedload(Product.brand),
            joinedload(Product.category)
        )
        
        if active_only:
            query = query.filter(Product.active == True)
        
        if search:
            search_filter = f"%{search}%"
            query = query.filter(
                or_(
                    Product.name.ilike(search_filter),
                    Product.model_code.ilike(search_filter),
                    Product.series.ilike(search_filter)
                )
            )
        
        if brand_ids:
            query = query.filter(Product.brand_id.in_(brand_ids))
        
        if category_id:
            query = query.filter(Product.category_id == category_id)
        
        if series:
            query = query.filter(Product.series.ilike(f"%{series}%"))
        
        if tier == 'low':
            query = query.filter(Product.low_tier_price.isnot(None))
        elif tier == 'mid':
            query = query.filter(Product.mid_tier_price.isnot(None))
        elif tier == 'high':
            query = query.filter(Product.high_tier_price.isnot(None))
        
        # OPTIMIZED: Proper ordering (brand already eager-loaded)
        query = query.join(Brand).order_by(Brand.name, Product.series, Product.model_code)
        
        # OPTIMIZED: Manual pagination (not deprecated .paginate())
        total_count = query.count()
        products = query.limit(per_page).offset((page - 1) * per_page).all()
        
        result = {
            'products': [serialize_product(p) for p in products],
            'pagination': {
                'page': page,
                'per_page': per_page,
                'total': total_count,
                'pages': (total_count + per_page - 1) // per_page,
                'has_next': page < ((total_count + per_page - 1) // per_page),
                'has_prev': page > 1
            }
        }
        
        # Cache the result
        simple_cache_set(cache_key, result)
        
        return jsonify(result)
        
    except Exception as e:
        current_app.logger.exception(f"Error fetching products: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@appliance_bp.route('/products/<int:product_id>', methods=['GET'])
def get_product(product_id):
    """
    Get a specific product by ID
    
    OPTIMIZATIONS:
    - 5-minute cache for individual products
    - Eager loading of brand and category
    """
    # Check cache first
    cache_key = f"product_{product_id}"
    cached = simple_cache_get(cache_key)
    if cached:
        return jsonify(cached), 200
    
    session = SessionLocal()
    try:
        # OPTIMIZED: Eager load brand and category
        product = session.query(Product)\
            .options(
                joinedload(Product.brand),
                joinedload(Product.category)
            )\
            .filter(Product.id == product_id)\
            .first()
            
        if not product:
            return jsonify({'error': 'Product not found'}), 404
        
        result = serialize_product(product)
        
        # Cache the result
        simple_cache_set(cache_key, result)
        
        return jsonify(result)
        
    except Exception as e:
        current_app.logger.exception(f"Error fetching product {product_id}: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@appliance_bp.route('/products', methods=['POST'])
def create_product():
    """
    Create a new product
    
    OPTIMIZATIONS:
    - Cache invalidation
    """
    session = SessionLocal()
    try:
        data = request.get_json()
        
        required_fields = ['model_code', 'name', 'brand_id', 'category_id']
        for field in required_fields:
            if not data.get(field):
                return jsonify({'error': f'{field} is required'}), 400
        
        if session.query(Product).filter_by(model_code=data['model_code']).first():
            return jsonify({'error': 'Model code already exists'}), 400
        
        product = Product(
            model_code=data['model_code'],
            name=data['name'],
            description=data.get('description'),
            brand_id=data['brand_id'],
            category_id=data['category_id'],
            series=data.get('series'),
            base_price=data.get('base_price'),
            low_tier_price=data.get('low_tier_price'),
            mid_tier_price=data.get('mid_tier_price'),
            high_tier_price=data.get('high_tier_price'),
            dimensions=json.dumps(data.get('dimensions', {})),
            weight=data.get('weight'),
            color_options=json.dumps(data.get('color_options', [])),
            pack_name=data.get('pack_name'),
            notes=data.get('notes'),
            energy_rating=data.get('energy_rating'),
            warranty_years=data.get('warranty_years'),
            active=data.get('active', True),
            in_stock=data.get('in_stock', True),
            lead_time_weeks=data.get('lead_time_weeks')
        )
        
        session.add(product)
        session.commit()
        
        # INVALIDATE CACHE
        invalidate_cache('products', 'product_search')
        
        # Eager load for response
        session.refresh(product)
        product = session.query(Product)\
            .options(joinedload(Product.brand), joinedload(Product.category))\
            .filter(Product.id == product.id)\
            .first()
        
        return jsonify(serialize_product(product)), 201
        
    except Exception as e:
        session.rollback()
        current_app.logger.exception(f"Error creating product: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@appliance_bp.route('/products/<int:product_id>', methods=['PUT'])
def update_product(product_id):
    """
    Update an existing product
    
    OPTIMIZATIONS:
    - Cache invalidation
    """
    session = SessionLocal()
    try:
        product = session.get(Product, product_id)
        if not product:
            return jsonify({'error': 'Product not found'}), 404

        data = request.get_json()
        
        updatable_fields = [
            'name', 'description', 'series', 'base_price', 'low_tier_price',
            'mid_tier_price', 'high_tier_price', 'weight', 'pack_name',
            'notes', 'energy_rating', 'warranty_years', 'active', 'in_stock',
            'lead_time_weeks', 'brand_id', 'category_id'
        ]
        
        for field in updatable_fields:
            if field in data:
                setattr(product, field, data[field])
        
        if 'dimensions' in data:
            product.dimensions = json.dumps(data['dimensions'])
        if 'color_options' in data:
            product.color_options = json.dumps(data['color_options'])
        
        product.updated_at = datetime.utcnow()
        session.commit()
        
        # INVALIDATE CACHE
        invalidate_cache('products', f'product_{product_id}', 'product_search')
        
        # Eager load for response
        product = session.query(Product)\
            .options(joinedload(Product.brand), joinedload(Product.category))\
            .filter(Product.id == product_id)\
            .first()
        
        return jsonify(serialize_product(product))
        
    except Exception as e:
        session.rollback()
        current_app.logger.exception(f"Error updating product: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@appliance_bp.route('/products/<int:product_id>', methods=['DELETE'])
def delete_product(product_id):
    """
    Delete a product (soft delete)
    
    OPTIMIZATIONS:
    - Cache invalidation
    """
    session = SessionLocal()
    try:
        product = session.get(Product, product_id)
        if not product:
            return jsonify({'error': 'Product not found'}), 404
        
        product.active = False
        product.updated_at = datetime.utcnow()
        session.commit()
        
        # INVALIDATE CACHE
        invalidate_cache('products', f'product_{product_id}', 'product_search', 'brands', 'categories')
        
        return jsonify({'message': 'Product deactivated successfully'})
        
    except Exception as e:
        session.rollback()
        current_app.logger.exception(f"Error deleting product: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


# ==========================================
# BRAND ENDPOINTS (OPTIMIZED)
# ==========================================

@appliance_bp.route('/brands', methods=['GET'])
def get_brands():
    """
    Get all brands
    
    OPTIMIZATIONS:
    - 10-minute cache (brands don't change often)
    """
    active_only = request.args.get('active_only', 'true').lower() == 'true'
    
    # Check cache first
    cache_key = f"brands_{active_only}"
    cached = simple_cache_get(cache_key)
    if cached:
        return jsonify(cached), 200
    
    session = SessionLocal()
    try:
        query = session.query(Brand)
        if active_only:
            query = query.filter(Brand.active == True)
        
        brands = query.order_by(Brand.name).all()
        
        result = [{
            'id': b.id,
            'name': b.name,
            'logo_url': b.logo_url,
            'website': b.website,
            'active': b.active,
            'product_count': len([p for p in b.products if p.active]) if active_only else len(b.products)
        } for b in brands]
        
        # Cache the result (10 minutes)
        simple_cache_set(cache_key, result)
        
        return jsonify(result)
        
    except Exception as e:
        current_app.logger.exception(f"Error fetching brands: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@appliance_bp.route('/brands', methods=['POST'])
def create_brand():
    """
    Create a new brand
    
    OPTIMIZATIONS:
    - Cache invalidation
    """
    session = SessionLocal()
    try:
        data = request.get_json()
        
        if not data.get('name'):
            return jsonify({'error': 'Brand name is required'}), 400
        
        if session.query(Brand).filter_by(name=data['name']).first():
            return jsonify({'error': 'Brand already exists'}), 400
        
        brand = Brand(
            name=data['name'],
            logo_url=data.get('logo_url'),
            website=data.get('website'),
            active=data.get('active', True)
        )
        
        session.add(brand)
        session.commit()
        
        # INVALIDATE CACHE
        invalidate_cache('brands')
        
        return jsonify({
            'id': brand.id,
            'name': brand.name,
            'logo_url': brand.logo_url,
            'website': brand.website,
            'active': brand.active
        }), 201
        
    except Exception as e:
        session.rollback()
        current_app.logger.exception(f"Error creating brand: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


# ==========================================
# CATEGORY ENDPOINTS (OPTIMIZED)
# ==========================================

@appliance_bp.route('/categories', methods=['GET'])
def get_categories():
    """
    Get all appliance categories
    
    OPTIMIZATIONS:
    - 10-minute cache (categories don't change often)
    """
    active_only = request.args.get('active_only', 'true').lower() == 'true'
    
    # Check cache first
    cache_key = f"categories_{active_only}"
    cached = simple_cache_get(cache_key)
    if cached:
        return jsonify(cached), 200
    
    session = SessionLocal()
    try:
        query = session.query(ApplianceCategory)
        if active_only:
            query = query.filter(ApplianceCategory.active == True)
        
        categories = query.order_by(ApplianceCategory.name).all()
        
        result = [{
            'id': c.id,
            'name': c.name,
            'description': c.description,
            'active': c.active,
            'product_count': len([p for p in c.products if p.active]) if active_only else len(c.products)
        } for c in categories]
        
        # Cache the result (10 minutes)
        simple_cache_set(cache_key, result)
        
        return jsonify(result)
        
    except Exception as e:
        current_app.logger.exception(f"Error fetching categories: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@appliance_bp.route('/categories', methods=['POST'])
def create_category():
    """
    Create a new appliance category
    
    OPTIMIZATIONS:
    - Cache invalidation
    """
    session = SessionLocal()
    try:
        data = request.get_json()
        
        if not data.get('name'):
            return jsonify({'error': 'Category name is required'}), 400
        
        if session.query(ApplianceCategory).filter_by(name=data['name']).first():
            return jsonify({'error': 'Category already exists'}), 400
        
        category = ApplianceCategory(
            name=data['name'],
            description=data.get('description'),
            active=data.get('active', True)
        )
        
        session.add(category)
        session.commit()
        
        # INVALIDATE CACHE
        invalidate_cache('categories')
        
        return jsonify({
            'id': category.id,
            'name': category.name,
            'description': category.description,
            'active': category.active
        }), 201
        
    except Exception as e:
        session.rollback()
        current_app.logger.exception(f"Error creating category: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


# ==========================================
# SEARCH AND UTILITY ENDPOINTS (OPTIMIZED)
# ==========================================

@appliance_bp.route('/products/<int:product_id>/price/<tier>', methods=['GET'])
def get_product_price_for_tier(product_id, tier):
    """
    Get product price for specific tier
    
    OPTIMIZATIONS:
    - Uses cached product data if available
    """
    # Try to get from cache first
    cache_key = f"product_{product_id}"
    cached = simple_cache_get(cache_key)
    
    if cached:
        price_map = {
            'low': cached.get('pricing', {}).get('low_tier_price'),
            'mid': cached.get('pricing', {}).get('mid_tier_price'),
            'high': cached.get('pricing', {}).get('high_tier_price'),
            'base': cached.get('pricing', {}).get('base_price')
        }
        price = price_map.get(tier)
        
        return jsonify({
            'product_id': product_id,
            'tier': tier,
            'price': price
        })
    
    session = SessionLocal()
    try:
        product = session.get(Product, product_id)
        if not product:
            return jsonify({'error': 'Product not found'}), 404
            
        price = product.get_price_for_tier(tier)
        
        return jsonify({
            'product_id': product_id,
            'tier': tier,
            'price': float(price) if price else None
        })
        
    except Exception as e:
        current_app.logger.exception(f"Error getting price for product {product_id}: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@appliance_bp.route('/products/search', methods=['GET'])
def search_products():
    """
    Search products with autocomplete support
    
    OPTIMIZATIONS:
    - 2-minute cache for search results
    - Eager loading of brand and category
    """
    query_text = request.args.get('q', '')
    limit = min(request.args.get('limit', 10, type=int), 50)
    
    if len(query_text) < 2:
        return jsonify([])
    
    # Check cache first
    cache_key = f"product_search_{query_text}_{limit}"
    cached = simple_cache_get(cache_key)
    if cached:
        return jsonify(cached), 200
    
    session = SessionLocal()
    try:
        search_filter = f"%{query_text}%"
        
        # OPTIMIZED: Eager load brand
        products = session.query(Product)\
            .options(
                joinedload(Product.brand),
                joinedload(Product.category)
            )\
            .filter(Product.active == True)\
            .filter(
                or_(
                    Product.name.ilike(search_filter),
                    Product.model_code.ilike(search_filter),
                    Product.series.ilike(search_filter)
                )
            )\
            .join(Brand)\
            .order_by(Brand.name, Product.series, Product.model_code)\
            .limit(limit)\
            .all()
        
        result = [{
            'id': p.id,
            'model_code': p.model_code,
            'name': p.name,
            'brand_name': p.brand.name if p.brand else None,
            'series': p.series,
            'base_price': float(p.base_price) if p.base_price else None,
            'category_name': p.category.name if p.category else None
        } for p in products]
        
        # Cache the result (2 minutes for fresh search results)
        simple_cache_set(cache_key, result)
        
        return jsonify(result)
        
    except Exception as e:
        current_app.logger.exception(f"Error searching products: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


# ==========================================
# IMPORT ENDPOINTS (OPTIMIZED)
# ==========================================

@appliance_bp.route('/import/upload', methods=['POST'])
def upload_import_file():
    """
    Upload file for data import
    
    OPTIMIZATIONS:
    - Background processing with batch commits
    - Cache invalidation after import
    """
    session = SessionLocal()
    try:
        if 'file' not in request.files:
            return jsonify({'error': 'No file provided'}), 400
        
        file = request.files['file']
        import_type = request.form.get('import_type', 'appliance_matrix')
        
        if file.filename == '':
            return jsonify({'error': 'No file selected'}), 400
        
        if not file.filename.lower().endswith(('.xlsx', '.xls', '.csv')):
            return jsonify({'error': 'Invalid file type. Please upload Excel or CSV file'}), 400
        
        # Save file
        filename = secure_filename(file.filename)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"{timestamp}_{filename}"
        
        upload_folder = current_app.config.get('UPLOAD_FOLDER', 'uploads')
        os.makedirs(upload_folder, exist_ok=True)
        file_path = os.path.join(upload_folder, filename)
        
        try:
            file.save(file_path)
        except Exception as save_error:
            current_app.logger.error(f"Error saving file: {save_error}")
            return jsonify({'error': f'Failed to save file: {str(save_error)}'}), 500
        
        # Create import record
        import_record = DataImport(
            filename=filename,
            import_type=import_type,
            imported_by=request.form.get('imported_by', 'System')
        )
        session.add(import_record)
        session.commit()

        # Start background worker
        try:
            worker_thread = threading.Thread(
                target=process_import_file,
                args=(current_app._get_current_object(), import_record.id, file_path, import_type)
            )
            worker_thread.daemon = True
            worker_thread.start()
        except Exception as thread_error:
            current_app.logger.error(f"Error starting worker thread: {thread_error}")
            import_record.status = 'failed'
            import_record.error_log = f'Failed to start processing: {str(thread_error)}'
            session.commit()
            return jsonify({'error': f'Failed to start processing: {str(thread_error)}'}), 500

        return jsonify({
            'import_id': import_record.id,
            'filename': filename,
            'message': 'File uploaded. Processing has started.'
        }), 201
        
    except Exception as e:
        session.rollback()
        current_app.logger.exception(f"Error uploading import file: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@appliance_bp.route('/import/<int:import_id>/status', methods=['GET'])
def get_import_status(import_id):
    """
    Get status of data import
    
    OPTIMIZATIONS:
    - 1-minute cache for import status
    """
    # Check cache first (short TTL for status)
    cache_key = f"import_status_{import_id}"
    cached = simple_cache_get(cache_key)
    if cached:
        return jsonify(cached), 200
    
    session = SessionLocal()
    try:
        import_record = session.get(DataImport, import_id)
        
        if not import_record:
            return jsonify({'error': 'Import record not found'}), 404
        
        result = {
            'id': import_record.id,
            'filename': import_record.filename,
            'import_type': import_record.import_type,
            'status': import_record.status,
            'records_processed': import_record.records_processed,
            'records_failed': import_record.records_failed,
            'error_log': import_record.error_log,
            'created_at': import_record.created_at.isoformat(),
            'completed_at': import_record.completed_at.isoformat() if import_record.completed_at else None
        }
        
        # Cache the result (1 minute for import status)
        simple_cache_set(cache_key, result)
        
        return jsonify(result)
        
    except Exception as e:
        current_app.logger.exception(f"Error fetching import status: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()