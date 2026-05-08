from flask import Blueprint, request, jsonify, current_app, send_file
from sqlalchemy import text
import pandas as pd
from io import BytesIO
import json

from ..db import SessionLocal
from .auth_helpers import token_required, require_tenant

pricelist_bp = Blueprint('pricelist', __name__)


@pricelist_bp.route('/pricelist', methods=['GET'])
@token_required
@require_tenant
def get_pricelist(tenant_id, employee_id):
    """Get all price list items with pagination"""
    session = SessionLocal()
    try:
        category = request.args.get('category')
        search = request.args.get('search', '').lower()
        page = int(request.args.get('page', 1))
        per_page = int(request.args.get('per_page', 1000))
        
        where_conditions = ["tenant_id = :tenant_id"]
        params = {'tenant_id': str(tenant_id)}
        
        if category:
            where_conditions.append("category = :category")
            params['category'] = category
        
        if search:
            where_conditions.append(
                "(LOWER(item_code) LIKE :search OR LOWER(description) LIKE :search OR LOWER(item_name) LIKE :search)"
            )
            params['search'] = f'%{search}%'
        
        where_clause = " AND ".join(where_conditions)
        
        count_query = text(f"""
            SELECT COUNT(*) as total
            FROM "StreemLyne_MT"."PriceList_Master"
            WHERE {where_clause}
        """)
        total = session.execute(count_query, params).fetchone().total
        
        offset = (page - 1) * per_page
        query = text(f"""
            SELECT * FROM "StreemLyne_MT"."PriceList_Master"
            WHERE {where_clause}
            ORDER BY item_code, door_type
            LIMIT :limit OFFSET :offset
        """)
        
        params['limit'] = per_page
        params['offset'] = offset
        
        items = session.execute(query, params).fetchall()
        
        result = []
        for item in items:
            result.append({
                'pricelist_id': item.pricelist_id,
                'tenant_id': item.tenant_id,
                'category': item.category,
                'item_code': item.item_code,
                'item_name': item.item_name,
                'description': item.description,
                'base_price': float(item.base_price) if item.base_price else None,
                'door_type': item.door_type,
                'width': item.width,
                'height': item.height,
                'depth': item.depth,
                'unit': item.unit,
                'dimension_based': item.dimension_based,
                'dimension_formula': item.dimension_formula,
                'created_at': item.created_at.isoformat() if item.created_at else None,
                'updated_at': item.updated_at.isoformat() if item.updated_at else None
            })
        
        return jsonify({
            'items': result,
            'pagination': {
                'page': page,
                'per_page': per_page,
                'total': total,
                'pages': (total + per_page - 1) // per_page
            }
        }), 200
        
    except Exception as e:
        print(f"Error fetching pricelist: {e}")
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
        
        if not data.get('category'):
            return jsonify({'error': 'category is required'}), 400
        if not data.get('item_code'):
            return jsonify({'error': 'item_code is required'}), 400
        if not data.get('door_type'):
            return jsonify({'error': 'door_type is required'}), 400
        
        insert_query = text("""
            INSERT INTO "StreemLyne_MT"."PriceList_Master"
            (tenant_id, category, item_code, item_name, description, base_price, door_type,
             width, height, depth, unit, dimension_based, dimension_formula)
            VALUES (:tenant_id, :category, :item_code, :item_name, :description, :base_price, :door_type,
                    :width, :height, :depth, :unit, :dimension_based, :dimension_formula)
            RETURNING pricelist_id
        """)
        
        result = session.execute(insert_query, {
            'tenant_id': str(tenant_id),
            'category': data['category'],
            'item_code': data['item_code'],
            'item_name': data.get('item_name', ''),
            'description': data.get('description', ''),
            'base_price': data.get('base_price'),
            'door_type': data['door_type'],
            'width': data.get('width'),
            'height': data.get('height'),
            'depth': data.get('depth'),
            'unit': data.get('unit', 'each'),
            'dimension_based': data.get('dimension_based', False),
            'dimension_formula': data.get('dimension_formula')
        })
        
        pricelist_id = result.fetchone().pricelist_id
        session.commit()
        
        return jsonify({
            'pricelist_id': pricelist_id,
            'message': 'Price list item created'
        }), 201
        
    except Exception as e:
        session.rollback()
        print(f"Error creating pricelist item: {e}")
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
            'item_code': 'item_code',
            'item_name': 'item_name',
            'description': 'description',
            'base_price': 'base_price',
            'door_type': 'door_type',
            'width': 'width',
            'height': 'height',
            'depth': 'depth',
            'unit': 'unit',
            'category': 'category',
            'dimension_based': 'dimension_based',
            'dimension_formula': 'dimension_formula'
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
        print(f"Error updating pricelist item: {e}")
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
        print(f"Error deleting pricelist item: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@pricelist_bp.route('/pricelist/bulk-upload', methods=['POST'])
@token_required
@require_tenant
def bulk_upload_pricelist(tenant_id, employee_id):
    """Bulk upload price list items from Excel file"""
    session = SessionLocal()
    try:
        if 'file' not in request.files:
            return jsonify({'error': 'No file uploaded'}), 400
        
        file = request.files['file']
        category = request.form.get('category', 'Kitchen')
        
        if not file.filename.endswith(('.xlsx', '.xls')):
            return jsonify({'error': 'Only Excel files are supported'}), 400
        
        # Read Excel file - Different header rows for Kitchen vs Bedrooms
        # Kitchen: row 1 (index 1), Bedrooms: row 2 (index 2)
        header_row = 1 if category == 'Kitchen' else 2
        
        current_app.logger.info(f"=" * 80)
        current_app.logger.info(f"STARTING EXCEL IMPORT - Category: {category}, Header row: {header_row}")
        current_app.logger.info(f"=" * 80)
        
        df = pd.read_excel(BytesIO(file.read()), header=header_row)
        
        current_app.logger.info(f"Excel file read successfully!")
        current_app.logger.info(f"Category: {category}, Header row: {header_row}")
        current_app.logger.info(f"DataFrame shape: {df.shape} (rows x columns)")
        current_app.logger.info(f"All column names: {df.columns.tolist()}")
        current_app.logger.info(f"First 3 rows of data:\n{df.head(3).to_string()}")
        
        # Debug: Print first 10 column names with their types
        for i, col in enumerate(df.columns[:15]):
            current_app.logger.info(f"Column {i}: '{col}' (type: {type(col).__name__})")
        
        items_created = 0
        items_updated = 0
        errors = []
        
        # Log column names to understand structure
        current_app.logger.info(f"DataFrame shape: {df.shape}")
        current_app.logger.info(f"First 5 column names: {df.columns[:15].tolist()}")
        
        # Find TOTAL columns by name for both categories
        total_columns = []
        base_cabinet_col = None
        
        if category == 'Kitchen':
            # Kitchen: Find columns named TOTAL, TOTAL.1, TOTAL.2, TOTAL.3
            door_type_names = ['Basic Slab', 'Acrylic Gloss/Matt', 'Vinyl Doors', 'Black Glass']
            for i, col_name in enumerate(df.columns):
                col_str = str(col_name).strip()
                if col_str == 'TOTAL' or col_str.startswith('TOTAL.'):
                    total_columns.append((col_name, i))
                    current_app.logger.info(f"Found TOTAL column: '{col_name}' at index {i}")
        else:  # Bedrooms
            # Bedrooms: Find 2025 Price column first (Base Cabinet Only)
            # Then find TOTAL columns
            door_type_names = ['Base Cabinet Only', 'Basic Slab', 'Acrylic Gloss/Matt', 'Vinyl Doors', 'Black Glass']
            
            # Find "2025 Price" column for Base Cabinet Only
            # It could be named "2025 Price" exactly or have variations
            for i, col_name in enumerate(df.columns):
                col_str = str(col_name).strip()
                # Check for exact match or partial match
                if col_str == '2025 Price' or '2025' in col_str and 'Price' in col_str:
                    base_cabinet_col = (col_name, i)
                    current_app.logger.info(f"Found Base Cabinet column: '{col_name}' at index {i}")
                    break
            
            # Find TOTAL columns - pandas might name them TOTAL, TOTAL.1, TOTAL.2, etc.
            for i, col_name in enumerate(df.columns):
                col_str = str(col_name).strip()
                # Match TOTAL exactly or TOTAL.1, TOTAL.2, etc.
                if col_str == 'TOTAL' or (col_str.startswith('TOTAL') and (col_str == 'TOTAL' or col_str[5:6] == '.')):
                    total_columns.append((col_name, i))
                    current_app.logger.info(f"Found TOTAL column: '{col_name}' at index {i}")
        
        current_app.logger.info(f"Found {len(total_columns)} TOTAL columns")
        
        if category == 'Bedrooms' and not base_cabinet_col:
            current_app.logger.warning("Could not find '2025 Price' column for Bedrooms!")
            current_app.logger.info(f"Available columns: {[str(c).lower() for c in df.columns[:10]]}")
        
        if len(total_columns) == 0:
            current_app.logger.warning("Could not find any TOTAL columns!")
            current_app.logger.info(f"Available columns: {df.columns.tolist()}")
        
        # Build door type mappings
        door_type_mappings = []
        
        if category == 'Bedrooms' and base_cabinet_col:
            door_type_mappings.append((base_cabinet_col[1], 'Base Cabinet Only'))
        
        # Add TOTAL columns with their door types
        for idx, (col_name, col_idx) in enumerate(total_columns):
            if category == 'Kitchen':
                if idx < len(door_type_names):
                    door_type_mappings.append((col_idx, door_type_names[idx]))
            else:  # Bedrooms - skip "Base Cabinet Only" in door_type_names since we added it above
                door_idx = idx + 1 if base_cabinet_col else idx
                if door_idx < len(door_type_names):
                    door_type_mappings.append((col_idx, door_type_names[door_idx]))
        
        current_app.logger.info(f"Door type mappings: {door_type_mappings}")
        
        for idx, row in df.iterrows():
            try:
                # Get code - handle both "Code" column name variations
                code = None
                for col in ['Code', 'code', df.columns[0]]:
                    if col in row:
                        code = str(row[col]).strip()
                        break
                
                if not code or code == 'nan' or code == '' or code.lower() == 'code':
                    current_app.logger.debug(f"Skipping row {idx}: invalid code '{code}'")
                    continue
                
                # Get description - different column names for Kitchen vs Bedrooms
                item_name = ''
                if category == 'Kitchen':
                    item_name = str(row.get('Description carcas only', '')).strip()
                else:  # Bedrooms
                    # Column index 1 or 2 typically has the description
                    for col in [df.columns[1], df.columns[2]]:
                        val = str(row.get(col, '')).strip()
                        if val and val != 'nan' and val != '':
                            item_name = val
                            break
                
                if not item_name or item_name == 'nan':
                    item_name = code  # Fallback to code
                
                # Get dimensions
                width = None
                height = None
                depth = None
                
                if 'Width' in row and pd.notna(row['Width']):
                    try:
                        width = int(float(row['Width']))
                    except:
                        pass
                
                if 'Height' in row and pd.notna(row['Height']):
                    try:
                        height = int(float(row['Height']))
                    except:
                        pass
                
                if 'Depth' in row and pd.notna(row['Depth']):
                    try:
                        depth = int(float(row['Depth']))
                    except:
                        pass
                
                # Process each door type
                for col_idx, door_type in door_type_mappings:
                    try:
                        # Get price from the column
                        if col_idx < len(row):
                            price = row.iloc[col_idx]
                        else:
                            continue
                        
                        # Skip if no price
                        if pd.isna(price) or price == '' or price == 0:
                            continue
                        
                        try:
                            price = float(price)
                        except:
                            continue
                        
                        # Create description with door type
                        description = f"{item_name} - {door_type}"
                        
                        # Check if exists
                        check_query = text("""
                            SELECT pricelist_id FROM "StreemLyne_MT"."PriceList_Master"
                            WHERE tenant_id = :tenant_id AND category = :category 
                            AND item_code = :code AND door_type = :door_type
                        """)
                        
                        existing = session.execute(check_query, {
                            'tenant_id': str(tenant_id),
                            'category': category,
                            'code': code,
                            'door_type': door_type
                        }).fetchone()
                        
                        if existing:
                            # Update
                            update_query = text("""
                                UPDATE "StreemLyne_MT"."PriceList_Master"
                                SET item_name = :item_name,
                                    description = :description,
                                    base_price = :base_price,
                                    width = :width,
                                    height = :height,
                                    depth = :depth
                                WHERE pricelist_id = :pricelist_id
                            """)
                            
                            session.execute(update_query, {
                                'pricelist_id': existing.pricelist_id,
                                'item_name': item_name,
                                'description': description,
                                'base_price': price,
                                'width': width,
                                'height': height,
                                'depth': depth
                            })
                            items_updated += 1
                        else:
                            # Insert
                            insert_query = text("""
                                INSERT INTO "StreemLyne_MT"."PriceList_Master"
                                (tenant_id, category, item_code, item_name, description, base_price, door_type,
                                 width, height, depth, unit, dimension_based)
                                VALUES (:tenant_id, :category, :item_code, :item_name, :description, :base_price, :door_type,
                                        :width, :height, :depth, :unit, :dimension_based)
                            """)
                            
                            session.execute(insert_query, {
                                'tenant_id': str(tenant_id),
                                'category': category,
                                'item_code': code,
                                'item_name': item_name,
                                'description': description,
                                'base_price': price,
                                'door_type': door_type,
                                'width': width,
                                'height': height,
                                'depth': depth,
                                'unit': 'each',
                                'dimension_based': False
                            })
                            items_created += 1
                        
                    except Exception as door_error:
                        print(f"Error processing door type {door_type} for {code}: {door_error}")
                        continue
                    
            except Exception as row_error:
                errors.append(f"Row {idx + 1}: {str(row_error)}")
                print(f"Error processing row {idx}: {row_error}")
                continue
        
        session.commit()
        
        current_app.logger.info(f"Import completed: {items_created} created, {items_updated} updated, {len(errors)} errors")
        if items_created == 0 and items_updated == 0:
            current_app.logger.warning("No items were processed! Check if door_type_mappings is empty or if all rows were skipped")
        
        response = {
            'success': True,
            'items_created': items_created,
            'items_updated': items_updated,
            'total_processed': items_created + items_updated
        }
        
        if errors:
            response['errors'] = errors[:10]
        
        return jsonify(response), 200
        
    except Exception as e:
        session.rollback()
        print(f"Error in bulk upload: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@pricelist_bp.route('/pricelist/export', methods=['GET'])
@token_required
@require_tenant
def export_pricelist(tenant_id, employee_id):
    """Export price list to Excel"""
    session = SessionLocal()
    try:
        category = request.args.get('category')
        
        where_conditions = ["tenant_id = :tenant_id"]
        params = {'tenant_id': str(tenant_id)}
        
        if category:
            where_conditions.append("category = :category")
            params['category'] = category
        
        where_clause = " AND ".join(where_conditions)
        
        query = text(f"""
            SELECT * FROM "StreemLyne_MT"."PriceList_Master"
            WHERE {where_clause}
            ORDER BY item_code, door_type
        """)
        
        items = session.execute(query, params).fetchall()
        
        # Convert to DataFrame
        data = []
        for item in items:
            data.append({
                'Code': item.item_code,
                'Description': item.item_name,
                'Door Type': item.door_type,
                'Price': item.base_price,
                'Width': item.width,
                'Height': item.height,
                'Depth': item.depth,
                'Category': item.category,
                'Unit': item.unit
            })
        
        df = pd.DataFrame(data)
        
        # Create Excel file
        output = BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, sheet_name='Pricelist', index=False)
        
        output.seek(0)
        
        filename = f"pricelist_{category if category else 'all'}_{pd.Timestamp.now().strftime('%Y%m%d')}.xlsx"
        
        return send_file(
            output,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            as_attachment=True,
            download_name=filename
        )
        
    except Exception as e:
        print(f"Error exporting pricelist: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()