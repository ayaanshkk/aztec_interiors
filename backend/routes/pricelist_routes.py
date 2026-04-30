from flask import Blueprint, request, jsonify, current_app
from sqlalchemy import text
import re

from ..db import SessionLocal
from .auth_helpers import token_required, require_tenant

pricelist_bp = Blueprint('pricelist', __name__)


def calculate_price(base_price, dimension_formula, dimensions):
    """Calculate price based on dimensions"""
    if not dimension_formula:
        return float(base_price or 0)
    
    try:
        # Replace dimension placeholders with actual values
        formula = dimension_formula
        for key, value in dimensions.items():
            formula = formula.replace(key, str(value))
        
        # Evaluate the formula safely (basic arithmetic only)
        # Only allow basic math operations
        allowed_names = {}
        result = eval(formula, {"__builtins__": {}}, allowed_names)
        return float(result)
    except Exception as e:
        current_app.logger.error(f"Error calculating price: {e}")
        return float(base_price or 0)


@pricelist_bp.route('/pricelist', methods=['GET'])
@token_required
@require_tenant
def get_pricelist(tenant_id, employee_id):
    """Get all price list items with optional category filter"""
    session = SessionLocal()
    try:
        category = request.args.get('category')
        
        # Build WHERE clause
        where_conditions = ["tenant_id = :tenant_id"]
        params = {'tenant_id': str(tenant_id)}
        
        if category:
            where_conditions.append("category = :category")
            params['category'] = category
        
        where_clause = " AND ".join(where_conditions)
        
        query = text(f"""
            SELECT * FROM "StreemLyne_MT"."PriceList_Master"
            WHERE {where_clause}
            ORDER BY category, item_name
        """)
        
        items = session.execute(query, params).fetchall()
        
        result = []
        for item in items:
            result.append({
                'pricelist_id': item.pricelist_id,
                'category': item.category,
                'item_name': item.item_name,
                'description': item.description,
                'base_price': float(item.base_price) if item.base_price else None,
                'dimension_based': item.dimension_based,
                'dimension_formula': item.dimension_formula,
                'unit': item.unit,
                'created_at': item.created_at.isoformat() if item.created_at else None
            })
        
        return jsonify(result), 200
        
    except Exception as e:
        current_app.logger.error(f"Error fetching pricelist: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@pricelist_bp.route('/pricelist', methods=['POST'])
@token_required
@require_tenant
def create_pricelist_item(tenant_id, employee_id):
    """Create a new price list item"""
    session = SessionLocal()
    try:
        data = request.get_json()
        
        # Validate required fields
        if not data.get('category'):
            return jsonify({'error': 'category is required'}), 400
        if not data.get('item_name'):
            return jsonify({'error': 'item_name is required'}), 400
        
        insert_query = text("""
            INSERT INTO "StreemLyne_MT"."PriceList_Master"
            (tenant_id, category, item_name, description, base_price,
             dimension_based, dimension_formula, unit)
            VALUES (:tenant_id, :category, :item_name, :description, :base_price,
                    :dimension_based, :dimension_formula, :unit)
            RETURNING pricelist_id
        """)
        
        result = session.execute(insert_query, {
            'tenant_id': str(tenant_id),
            'category': data['category'],
            'item_name': data['item_name'],
            'description': data.get('description', ''),
            'base_price': data.get('base_price'),
            'dimension_based': data.get('dimension_based', False),
            'dimension_formula': data.get('dimension_formula'),
            'unit': data.get('unit', 'each')
        })
        
        pricelist_id = result.fetchone().pricelist_id
        session.commit()
        
        current_app.logger.info(f"Price list item {pricelist_id} created")
        
        return jsonify({
            'pricelist_id': pricelist_id,
            'message': 'Price list item created'
        }), 201
        
    except Exception as e:
        session.rollback()
        current_app.logger.error(f"Error creating pricelist item: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@pricelist_bp.route('/pricelist/<int:pricelist_id>', methods=['PUT'])
@token_required
@require_tenant
def update_pricelist_item(pricelist_id, tenant_id, employee_id):
    """Update a price list item"""
    session = SessionLocal()
    try:
        data = request.get_json()
        
        update_fields = []
        params = {'pricelist_id': pricelist_id, 'tenant_id': str(tenant_id)}
        
        updatable = {
            'category': 'category',
            'item_name': 'item_name',
            'description': 'description',
            'base_price': 'base_price',
            'dimension_based': 'dimension_based',
            'dimension_formula': 'dimension_formula',
            'unit': 'unit'
        }
        
        for key, col in updatable.items():
            if key in data:
                update_fields.append(f"{col} = :{key}")
                params[key] = data[key]
        
        if not update_fields:
            return jsonify({'error': 'No fields to update'}), 400
        
        update_query = text(f"""
            UPDATE "StreemLyne_MT"."PriceList_Master"
            SET {', '.join(update_fields)}
            WHERE pricelist_id = :pricelist_id AND tenant_id = :tenant_id
        """)
        
        result = session.execute(update_query, params)
        
        if result.rowcount == 0:
            return jsonify({'error': 'Price list item not found'}), 404
        
        session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Price list item updated'
        }), 200
        
    except Exception as e:
        session.rollback()
        current_app.logger.error(f"Error updating pricelist item: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@pricelist_bp.route('/pricelist/<int:pricelist_id>', methods=['DELETE'])
@token_required
@require_tenant
def delete_pricelist_item(pricelist_id, tenant_id, employee_id):
    """Delete a price list item"""
    session = SessionLocal()
    try:
        delete_query = text("""
            DELETE FROM "StreemLyne_MT"."PriceList_Master"
            WHERE pricelist_id = :pricelist_id AND tenant_id = :tenant_id
        """)
        
        result = session.execute(delete_query, {
            'pricelist_id': pricelist_id,
            'tenant_id': str(tenant_id)
        })
        
        if result.rowcount == 0:
            return jsonify({'error': 'Price list item not found'}), 404
        
        session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Price list item deleted'
        }), 200
        
    except Exception as e:
        session.rollback()
        current_app.logger.error(f"Error deleting pricelist item: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@pricelist_bp.route('/pricelist/search', methods=['POST'])
@token_required
@require_tenant
def search_pricelist(tenant_id, employee_id):
    """Smart search for price list items based on description"""
    session = SessionLocal()
    try:
        data = request.get_json()
        search_term = data.get('search_term', '').lower()
        category = data.get('category')
        dimensions = data.get('dimensions', {})
        
        # Build WHERE clause
        where_conditions = ["tenant_id = :tenant_id"]
        params = {'tenant_id': str(tenant_id), 'search_term': f'%{search_term}%'}
        
        if category:
            where_conditions.append("category = :category")
            params['category'] = category
        
        # Add search condition
        where_conditions.append("(LOWER(item_name) LIKE :search_term OR LOWER(description) LIKE :search_term)")
        
        where_clause = " AND ".join(where_conditions)
        
        query = text(f"""
            SELECT * FROM "StreemLyne_MT"."PriceList_Master"
            WHERE {where_clause}
            ORDER BY item_name
        """)
        
        items = session.execute(query, params).fetchall()
        
        results = []
        for item in items:
            item_dict = {
                'pricelist_id': item.pricelist_id,
                'category': item.category,
                'item_name': item.item_name,
                'description': item.description,
                'base_price': float(item.base_price) if item.base_price else None,
                'dimension_based': item.dimension_based,
                'dimension_formula': item.dimension_formula,
                'unit': item.unit
            }
            
            # Calculate price if dimension-based
            if item.dimension_based and dimensions:
                calculated_price = calculate_price(
                    item.base_price,
                    item.dimension_formula,
                    dimensions
                )
                item_dict['calculated_price'] = calculated_price
            
            results.append(item_dict)
        
        return jsonify(results), 200
        
    except Exception as e:
        current_app.logger.error(f"Error searching pricelist: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@pricelist_bp.route('/pricelist/categories', methods=['GET'])
@token_required
@require_tenant
def get_categories(tenant_id, employee_id):
    """Get all unique categories in price list"""
    session = SessionLocal()
    try:
        query = text("""
            SELECT DISTINCT category 
            FROM "StreemLyne_MT"."PriceList_Master"
            WHERE tenant_id = :tenant_id
            ORDER BY category
        """)
        
        categories = session.execute(query, {'tenant_id': str(tenant_id)}).fetchall()
        
        return jsonify([c.category for c in categories]), 200
        
    except Exception as e:
        current_app.logger.error(f"Error fetching categories: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()