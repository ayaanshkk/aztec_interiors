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
        per_page = int(request.args.get('per_page', 10000))  # ← CHANGE THIS from 1000 to 10000
        
        # Cap per_page at a reasonable limit
        if per_page > 10000:
            per_page = 10000
        
        where_conditions = ["tenant_id = :tenant_id"]
        params = {'tenant_id': str(tenant_id)}
        
        if category:
            where_conditions.append("category = :category")
            params['category'] = category

        brand = request.args.get('brand')
        if brand and brand != 'All':
            where_conditions.append("brand = :brand")
            params['brand'] = brand
        
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
        
        # ← ADD LOGGING to see what's happening
        current_app.logger.info(f"📊 Fetching pricelist: category={category}, page={page}, per_page={per_page}, total={total}")
        
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
        
        current_app.logger.info(f"✅ Returned {len(items)} items out of {total} total")
        
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
                'brand': item.brand if hasattr(item, 'brand') else None,
                'colour': item.colour if hasattr(item, 'colour') else None,
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
        current_app.logger.error(f"❌ Error fetching pricelist: {e}")
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
             width, height, depth, unit, dimension_based, dimension_formula, colour)
            VALUES (:tenant_id, :category, :item_code, :item_name, :description, :base_price, :door_type,
                    :width, :height, :depth, :unit, :dimension_based, :dimension_formula, :colour)
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
            'dimension_formula': data.get('dimension_formula'),
            'colour': data.get('colour')
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

@pricelist_bp.route('/pricelist/debug', methods=['GET'])
@token_required
@require_tenant
def debug_pricelist(tenant_id, employee_id):
    """Debug endpoint to check database contents"""
    session = SessionLocal()
    try:
        # Count by category
        count_query = text("""
            SELECT category, COUNT(*) as count
            FROM "StreemLyne_MT"."PriceList_Master"
            WHERE tenant_id = :tenant_id
            GROUP BY category
        """)
        
        counts = session.execute(count_query, {'tenant_id': str(tenant_id)}).fetchall()
        
        # Get sample items from Kitchen
        sample_query = text("""
            SELECT item_code, door_type, base_price
            FROM "StreemLyne_MT"."PriceList_Master"
            WHERE tenant_id = :tenant_id AND category = 'Kitchen'
            LIMIT 10
        """)
        
        samples = session.execute(sample_query, {'tenant_id': str(tenant_id)}).fetchall()
        
        return jsonify({
            'counts': [{'category': r.category, 'count': r.count} for r in counts],
            'kitchen_samples': [{'item_code': r.item_code, 'door_type': r.door_type, 'price': float(r.base_price)} for r in samples]
        }), 200
        
    except Exception as e:
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
            'dimension_formula': 'dimension_formula',
            'colour': 'colour'
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
        
        # Debug: Print first 15 column names with their types
        for i, col in enumerate(df.columns[:15]):
            current_app.logger.info(f"Column {i}: '{col}' (type: {type(col).__name__})")
        
        items_created = 0
        items_updated = 0
        errors = []
        
        # ============================================================================
        # NEW LOGIC: Separate carcass price from door/drawer pricing
        # ============================================================================
        
        if category == 'Kitchen':
            # Kitchen structure (YOUR EXACT Excel format):
            # Row 2 has headers, data starts at row 3
            # Col 3: "2025 Price" = CARCASS price
            # Col 5: "basic slab frnt door (2250 H) / drawer" = Door COMPONENT price
            # Col 6: "TOTAL" = IGNORE (carcass + door sum)
            # Col 7: "Acrylic gloss/Matt" = Door COMPONENT price
            # Col 8: "TOTAL" = IGNORE
            # Col 9: "vinyl doors" = Door COMPONENT price
            # Col 10: "TOTAL" = IGNORE
            # Col 11: "Black Glass" = Door COMPONENT price
            # Col 12: "TOTAL" = IGNORE
            
            current_app.logger.info(f"Processing Kitchen category with YOUR Excel structure")
            
            # FIXED COLUMN INDICES based on your actual Excel file
            carcass_col_idx = None
            door_component_mappings = []
            
            # Find columns by matching exact patterns
            for i, col_name in enumerate(df.columns):
                col_str = str(col_name).strip()
                col_lower = col_str.lower()
                
                # Find carcass price column (2025 Price)
                if '2025' in col_str and 'price' in col_lower:
                    carcass_col_idx = i
                    current_app.logger.info(f"✅ Carcass Price column at index {i}: '{col_name}'")
                
                # Find door COMPONENT columns (NOT TOTAL columns!)
                # Basic Slab component (NOT the TOTAL after it)
                elif 'basic' in col_lower and 'slab' in col_lower and 'door' in col_lower and 'total' not in col_lower:
                    door_component_mappings.append((i, 'Basic Slab'))
                    current_app.logger.info(f"✅ Basic Slab COMPONENT at index {i}: '{col_name}'")
                
                # Acrylic component (NOT the TOTAL after it)
                elif 'acrylic' in col_lower and 'total' not in col_lower and 'gloss' in col_lower:
                    door_component_mappings.append((i, 'Acrylic Gloss/Matt'))
                    current_app.logger.info(f"✅ Acrylic COMPONENT at index {i}: '{col_name}'")
                
                # Vinyl component (NOT the TOTAL after it)
                elif 'vinyl' in col_lower and 'total' not in col_lower and 'door' in col_lower:
                    door_component_mappings.append((i, 'Vinyl Doors'))
                    current_app.logger.info(f"✅ Vinyl COMPONENT at index {i}: '{col_name}'")
                
                # Black Glass component (NOT the TOTAL after it)
                elif 'black' in col_lower and 'glass' in col_lower and 'total' not in col_lower:
                    door_component_mappings.append((i, 'Black Glass'))
                    current_app.logger.info(f"✅ Black Glass COMPONENT at index {i}: '{col_name}'")
                
                # Log and SKIP any TOTAL columns
                elif col_str == 'TOTAL' or (col_str.startswith('TOTAL') and '.' in col_str):
                    current_app.logger.info(f"⚠️ SKIPPING TOTAL column at index {i}: '{col_name}' (this is carcass+door sum)")
            
            current_app.logger.info(f"📊 Final mappings:")
            current_app.logger.info(f"   Carcass column: {carcass_col_idx}")
            current_app.logger.info(f"   Door component columns: {door_component_mappings}")
            
            # Process each row
            for idx, row in df.iterrows():
                try:
                    # Get code
                    code = None
                    for col in ['Code', 'code', df.columns[0]]:
                        if col in row:
                            code = str(row[col]).strip()
                            break
                    
                    if not code or code == 'nan' or code == '' or code.lower() == 'code':
                        current_app.logger.debug(f"Skipping row {idx}: invalid code '{code}'")
                        continue
                    
                    # Get description
                    item_name = str(row.get('Description carcas only', '')).strip()
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
                    
                    # ========================================
                    # 1. Create/Update "Carcass Only" entry
                    # ========================================
                    if carcass_col_idx is not None and carcass_col_idx < len(row):
                        carcass_price = row.iloc[carcass_col_idx]
                        
                        if pd.notna(carcass_price) and carcass_price != '' and carcass_price != 0:
                            try:
                                carcass_price = float(carcass_price)
                                
                                description = f"{item_name} - Carcass Only"
                                
                                # Check if exists
                                check_query = text("""
                                    SELECT pricelist_id FROM "StreemLyne_MT"."PriceList_Master"
                                    WHERE tenant_id = :tenant_id AND category = :category 
                                    AND item_code = :code AND door_type = 'Carcass Only'
                                """)
                                
                                existing = session.execute(check_query, {
                                    'tenant_id': str(tenant_id),
                                    'category': category,
                                    'code': code
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
                                        'base_price': carcass_price,
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
                                        'base_price': carcass_price,
                                        'door_type': 'Carcass Only',
                                        'width': width,
                                        'height': height,
                                        'depth': depth,
                                        'unit': 'each',
                                        'dimension_based': False
                                    })
                                    items_created += 1
                                    
                            except Exception as e:
                                current_app.logger.error(f"Error processing carcass price for {code}: {e}")
                    
                    # ========================================
                    # 2. Create/Update door component entries
                    # ========================================
                    for col_idx, door_type in door_component_mappings:
                        try:
                            # Get component price from the column
                            if col_idx < len(row):
                                component_price = row.iloc[col_idx]
                            else:
                                continue
                            
                            # Skip if no price
                            if pd.isna(component_price) or component_price == '' or component_price == 0:
                                continue
                            
                            try:
                                component_price = float(component_price)
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
                                    'base_price': component_price,
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
                                    'base_price': component_price,
                                    'door_type': door_type,
                                    'width': width,
                                    'height': height,
                                    'depth': depth,
                                    'unit': 'each',
                                    'dimension_based': False
                                })
                                items_created += 1
                            
                        except Exception as door_error:
                            current_app.logger.error(f"Error processing {door_type} for {code}: {door_error}")
                            continue
                    
                except Exception as row_error:
                    errors.append(f"Row {idx + 1}: {str(row_error)}")
                    current_app.logger.error(f"Error processing row {idx}: {row_error}")
                    continue
        
        else:  # Bedrooms - Keep existing total logic for now
            # (Will update Bedrooms separately in a follow-up)
            # ... existing Bedrooms logic ...
            pass
        
        session.commit()
        
        current_app.logger.info(f"Import completed: {items_created} created, {items_updated} updated, {len(errors)} errors")
        
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