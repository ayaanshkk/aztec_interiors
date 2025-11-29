from flask import Blueprint, request, jsonify, current_app
from ..db import SessionLocal
from ..models import PriceListItem
from .auth_helpers import token_required
import re

pricelist_bp = Blueprint('pricelist', __name__)

@pricelist_bp.route('/pricelist', methods=['GET', 'POST'])
@token_required
def handle_pricelist():
    session = SessionLocal()
    try:
        if request.method == 'POST':
            data = request.json
            item = PriceListItem(
                category=data['category'],  # 'kitchen' or 'bedroom'
                item_name=data['item_name'],
                description=data.get('description', ''),
                base_price=data.get('base_price'),
                dimension_based=data.get('dimension_based', False),
                dimension_formula=data.get('dimension_formula'),  # e.g., "width * height"
                unit=data.get('unit', 'each')
            )
            session.add(item)
            session.commit()
            return jsonify({'id': item.id, 'message': 'Price list item created'}), 201
        
        # GET all items
        category = request.args.get('category')
        query = session.query(PriceListItem)
        if category:
            query = query.filter_by(category=category)
        items = query.all()
        return jsonify([item.to_dict() for item in items])
    
    except Exception as e:
        session.rollback()
        current_app.logger.error(f"Error handling pricelist: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@pricelist_bp.route('/pricelist/search', methods=['POST'])
@token_required
def search_pricelist():
    """Smart search for price list items based on description"""
    session = SessionLocal()
    try:
        data = request.json
        search_term = data.get('search_term', '').lower()
        category = data.get('category')  # 'kitchen' or 'bedroom'
        dimensions = data.get('dimensions', {})  # {'width': 400, 'height': 1495}
        
        query = session.query(PriceListItem)
        if category:
            query = query.filter_by(category=category)
        
        # Fuzzy search on item_name and description
        items = query.filter(
            (PriceListItem.item_name.ilike(f'%{search_term}%')) |
            (PriceListItem.description.ilike(f'%{search_term}%'))
        ).all()
        
        results = []
        for item in items:
            item_dict = item.to_dict()
            
            # Calculate price if dimension-based
            if item.dimension_based and dimensions:
                calculated_price = calculate_price(item, dimensions)
                item_dict['calculated_price'] = calculated_price
            
            results.append(item_dict)
        
        return jsonify(results)
    
    except Exception as e:
        current_app.logger.error(f"Error searching pricelist: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


def calculate_price(item: 'PriceListItem', dimensions: dict) -> float:
    """Calculate price based on dimensions"""
    if not item.dimension_formula:
        return float(item.base_price or 0)
    
    try:
        # Replace dimension placeholders with actual values
        formula = item.dimension_formula
        for key, value in dimensions.items():
            formula = formula.replace(key, str(value))
        
        # Evaluate the formula safely (basic arithmetic only)
        result = eval(formula, {"__builtins__": {}}, {})
        return float(result)
    except Exception as e:
        current_app.logger.error(f"Error calculating price: {e}")
        return float(item.base_price or 0)