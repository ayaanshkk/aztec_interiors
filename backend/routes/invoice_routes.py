from flask import Blueprint, json, request, jsonify, current_app, send_file, session
from sqlalchemy import text
from datetime import datetime, timedelta
from io import BytesIO

from ..db import SessionLocal
from .auth_helpers import token_required, require_tenant
from .pdf_helpers import PDF

invoice_bp = Blueprint("invoice", __name__)


# ============================================================================
# HELPERS
# ============================================================================

def generate_invoice_number(session, tenant_id):
    result = session.execute(
        text("""
            SELECT COALESCE(MAX(
                CAST(NULLIF(REGEXP_REPLACE(invoice_number, '^INV-(\\d+)$', '\\1'), invoice_number) AS INTEGER)
            ), 0) as max_seq
            FROM "StreemLyne_MT"."Invoice_Master"
            WHERE tenant_id = :t AND invoice_number LIKE 'INV-%'
        """),
        {'t': str(tenant_id)}
    ).fetchone()
    return f"INV-{result.max_seq + 1}"


def calculate_invoice_total(session, invoice_id):
    result = session.execute(
        text("""
            SELECT COALESCE(SUM(amount * quantity), 0) as total
            FROM "StreemLyne_MT"."Invoice_Details"
            WHERE invoice_id = :invoice_id
        """),
        {'invoice_id': invoice_id}
    ).fetchone()
    return float(result.total) if result else 0.0


# ============================================================================
# LIST / CREATE
# ============================================================================

@invoice_bp.route('/invoices', methods=['GET'])
@token_required
@require_tenant
def get_invoices(tenant_id, employee_id):
    session = SessionLocal()
    try:
        client_id = (
            request.args.get('client_id') or
            request.args.get('customer_id') or
            request.args.get('id')
        )

        if not client_id:
            return jsonify([]), 200

        rows = session.execute(
            text("""
                SELECT
                    i.*,
                    c.client_company_name,
                    (SELECT COUNT(*) FROM "StreemLyne_MT"."Invoice_Details"
                     WHERE invoice_id = i.invoice_id) AS items_count
                FROM "StreemLyne_MT"."Invoice_Master" i
                INNER JOIN "StreemLyne_MT"."Client_Master" c ON i.client_id = c.client_id
                WHERE i.tenant_id = :tenant_id AND i.client_id = :client_id
                ORDER BY i.created_at DESC
            """),
            {'tenant_id': str(tenant_id), 'client_id': int(client_id)}
        ).fetchall()

        import json as _json

        result_list = []
        for r in rows:
            # Parse section discounts
            section_discounts = {}
            sd_raw = getattr(r, 'section_discounts', None)
            if sd_raw:
                try:
                    section_discounts = _json.loads(sd_raw) if isinstance(sd_raw, str) else sd_raw
                except:
                    pass

            # Get per-section item totals
            section_rows = session.execute(text("""
                SELECT COALESCE(section, 'Furniture') as section,
                    SUM(COALESCE(discounted_amount, amount * quantity)) as section_total
                FROM "StreemLyne_MT"."Invoice_Details"
                WHERE invoice_id = :iid
                AND (is_sub_item = false OR is_sub_item IS NULL)
                GROUP BY COALESCE(section, 'Furniture')
            """), {'iid': r.invoice_id}).fetchall()

            subtotal_after_section_discounts = sum(
                float(sr.section_total or 0) for sr in section_rows
            )

            vat_pct = float(r.vat_rate) if getattr(r, 'vat_rate', None) is not None else 20.0
            global_disc = float(r.global_discount_percent) if getattr(r, 'global_discount_percent', None) is not None else 0.0
            global_disc_amt = round(subtotal_after_section_discounts * (global_disc / 100), 2)
            after_global_disc = subtotal_after_section_discounts - global_disc_amt
            computed_total = round(after_global_disc * (1 + vat_pct / 100), 2)

            result_list.append({
                'id':             r.invoice_id,
                'invoice_id':     r.invoice_id,
                'invoice_number': r.invoice_number,
                'client_id':      r.client_id,
                'customer_id':    r.client_id,
                'customer_name':  r.customer_name or r.client_company_name,
                'project_id':     r.project_id,
                'total':          round(computed_total, 2),
                'status':         r.status,
                'notes':          r.notes,
                'items_count':    r.items_count or 0,
                'room_name':      r.room_name or '',
                'invoice_date':   r.invoice_date.isoformat() if r.invoice_date else None,
                'due_date':       r.due_date.isoformat()     if r.due_date     else None,
                'created_at':     r.created_at.isoformat()   if r.created_at   else None,
            })

        return jsonify(result_list), 200

    except Exception as e:
        current_app.logger.exception(f"Error fetching invoices: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@invoice_bp.route('/invoices', methods=['POST'])
@token_required
@require_tenant
def create_invoice(tenant_id, employee_id):
    session = SessionLocal()
    try:
        data      = request.get_json(silent=True) or {}
        client_id = data.get('client_id') or data.get('customer_id') or data.get('customerId')

        if not client_id:
            return jsonify({'error': 'client_id is required'}), 400

        client = session.execute(
            text('SELECT client_id FROM "StreemLyne_MT"."Client_Master" WHERE client_id = :c AND tenant_id = :t'),
            {'c': int(client_id), 't': str(tenant_id)}
        ).fetchone()

        if not client:
            return jsonify({'error': 'Client not found'}), 404

        invoice_number = data.get('invoice_number') or generate_invoice_number(session, tenant_id)
        items_data     = data.get('items', [])
        subtotal       = float(data.get('subtotal', 0))
        vat_rate       = float(data.get('vat_percentage', data.get('vat_rate', 20)))
        vat_amount     = subtotal * (vat_rate / 100)
        total_amount   = subtotal + vat_amount

        invoice_date = data.get('invoice_date') or datetime.utcnow().strftime('%Y-%m-%d')
        due_date     = data.get('due_date') or (
            datetime.strptime(invoice_date, '%Y-%m-%d') + timedelta(days=30)
        ).strftime('%Y-%m-%d')

        result = session.execute(
            text("""
                INSERT INTO "StreemLyne_MT"."Invoice_Master"
                (tenant_id, client_id, project_id, invoice_number, invoice_date, due_date,
                 status, notes, customer_name, customer_address, customer_phone, customer_email,
                 subtotal, vat_rate, vat_amount, total_amount, created_by_employee_id,
                 sub_total, vat, description, tax_id,
                 room_name, carcass_colour, door_colour, panelwork_colour, door_style,
                 deposit_paid, total_remaining, door_type, room_type, section_discounts, global_discount_percent, filler_type,
                 additional_terms, additional_notes,
                 signature_type, signature_image, signature_text, signature_name, signature_date,
                 quote_reference)
                VALUES
                (:tenant_id, :client_id, :project_id, :invoice_number, :invoice_date, :due_date,
                 :status, :notes, :customer_name, :customer_address, :customer_phone, :customer_email,
                 :subtotal, :vat_rate, :vat_amount, :total_amount, :created_by,
                 :subtotal, :vat_amount, :notes, :tax_id,
                 :room_name, :carcass_colour, :door_colour, :panelwork_colour, :door_style,
                 :deposit_paid, :total_remaining, :door_type, :room_type, :section_discounts, :global_discount_percent, :filler_type,
                 :additional_terms, :additional_notes,
                 :signature_type, :signature_image, :signature_text, :signature_name, :signature_date,
                 :quote_reference)
                RETURNING invoice_id
            """),
            {
                'tenant_id':        str(tenant_id),
                'client_id':        int(client_id),
                'project_id':       data.get('project_id'),
                'invoice_number':   invoice_number,
                'invoice_date':     invoice_date,
                'due_date':         due_date,
                'status':           data.get('status', 'Draft'),
                'notes':            data.get('notes', ''),
                'customer_name':    data.get('customer_name', ''),
                'customer_address': data.get('customer_address', ''),
                'customer_phone':   data.get('customer_phone', ''),
                'customer_email':   data.get('customer_email', ''),
                'subtotal':         subtotal,
                'vat_rate':         vat_rate,
                'vat_amount':       vat_amount,
                'total_amount':     total_amount,
                'created_by':       employee_id,
                'tax_id':           1,
                'room_name':        data.get('room_name', ''),
                'carcass_colour':   data.get('carcass_colour', ''),
                'door_colour':      data.get('door_colour', ''),
                'panelwork_colour': data.get('panelwork_colour', ''),
                'door_style':       data.get('door_style', ''),
                'deposit_paid':     float(data.get('deposit_paid', 0)),
                'total_remaining':  float(data.get('total_remaining', 0)),
                'door_type':        data.get('door_type', 'Carcass Only'),
                'room_type':        data.get('room_type', 'Kitchen'),
                'filler_type':      data.get('filler_type') or data.get('filler_door_type', 'Basic Slab'),
                'section_discounts':       json.dumps(data.get('section_discounts', {})),
                'global_discount_percent': float(data.get('global_discount_percent', 0)),
                'additional_terms':        json.dumps(data.get('additional_terms', [])),
                'additional_notes':        data.get('additional_notes', ''),
                'signature_type':  data.get('signature_type', 'none'),
                'signature_image': data.get('signature_image'),
                'signature_text':  data.get('signature_text'),
                'signature_name':  data.get('signature_name', ''),
                'signature_date':  data.get('signature_date', ''),
                'quote_reference': data.get('quote_reference') or None,
            }
        )
        invoice_id = result.fetchone().invoice_id

        # Insert items into Invoice_Details
        for item in items_data:
            if not item.get('item') and not item.get('description') and not item.get('amount'):
                continue
            unit_price = float(item.get('amount', 0))
            qty = int(item.get('quantity', 1))
            session.execute(
                text("""
                    INSERT INTO "StreemLyne_MT"."Invoice_Details"
                    (invoice_id, item_name, description, color, quantity, amount,
                    unit_price, service_name, width, height, depth,
                    discount_percent, discounted_amount, section, is_sub_item)
                    VALUES
                    (:invoice_id, :item_name, :desc, :color, :qty, :amt,
                    :unit_price, :service_name, :w, :h, :d, :dp, :da, :section, :is_sub_item)
                """),
                {
                    'invoice_id':   invoice_id,
                    'item_name':    item.get('item', ''),
                    'desc':         item.get('description', ''),
                    'color':        item.get('color', item.get('colour', '')),
                    'qty':          qty,
                    'amt':          unit_price,   # ← unit price stored in amount column
                    'unit_price':   unit_price,   # ← same
                    'service_name': item.get('item', ''),
                    'w':            item.get('width'),
                    'h':            item.get('height'),
                    'd':            item.get('depth'),
                    'dp':           item.get('discount_percent', 0),
                    'da':           item.get('discounted_total', unit_price * qty),
                    'section':      item.get('section', 'Furniture'),
                    'is_sub_item':  bool(item.get('is_sub_item', False)),
                }
            )

        session.commit()
        current_app.logger.info(f"Invoice {invoice_number} created for client {client_id}")

        return jsonify({
            'invoice_id':     invoice_id,
            'invoice_number': invoice_number,
            'message':        'Invoice created successfully'
        }), 201

    except Exception as e:
        session.rollback()
        current_app.logger.exception(f"Error creating invoice: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


# ============================================================================
# SINGLE INVOICE — GET / PUT / DELETE
# ============================================================================

@invoice_bp.route('/invoices/<int:invoice_id>', methods=['GET', 'PUT', 'DELETE'])
@token_required
@require_tenant
def handle_invoice(invoice_id, tenant_id, employee_id):
    session = SessionLocal()
    try:
        if request.method == 'GET':
            row = session.execute(
                text("""
                    SELECT i.*, c.client_company_name, c.address AS client_address, c.client_phone
                    FROM "StreemLyne_MT"."Invoice_Master" i
                    INNER JOIN "StreemLyne_MT"."Client_Master" c ON i.client_id = c.client_id
                    WHERE i.invoice_id = :id AND i.tenant_id = :t
                """),
                {'id': invoice_id, 't': str(tenant_id)}
            ).fetchone()

            if not row:
                return jsonify({'error': 'Invoice not found'}), 404

            items = session.execute(
                text("""
                    SELECT * FROM "StreemLyne_MT"."Invoice_Details"
                    WHERE invoice_id = :id
                    ORDER BY invoice_details_id
                """),
                {'id': invoice_id}
            ).fetchall()

            import json as _json
            section_discounts = {}
            sd_raw = getattr(row, 'section_discounts', None)
            if sd_raw:
                try:
                    section_discounts = _json.loads(sd_raw) if isinstance(sd_raw, str) else sd_raw
                except:
                    pass

            section_rows = session.execute(text("""
                SELECT COALESCE(section, 'Furniture') as section,
                    SUM(COALESCE(discounted_amount, amount * quantity)) as section_total
                FROM "StreemLyne_MT"."Invoice_Details"
                WHERE invoice_id = :iid
                AND (is_sub_item = false OR is_sub_item IS NULL)
                GROUP BY COALESCE(section, 'Furniture')
            """), {'iid': invoice_id}).fetchall()

            subtotal_after_section_discounts = sum(
                float(sr.section_total or 0) for sr in section_rows
            )

            vat_rate_val = float(row.vat_rate) if row.vat_rate is not None else 20.0    
            computed_vat = round(subtotal_after_section_discounts * (vat_rate_val / 100), 2)
            computed_total = round(subtotal_after_section_discounts + computed_vat, 2)


            return jsonify({
                'id':               row.invoice_id,
                'invoice_id':       row.invoice_id,
                'invoice_number':   row.invoice_number,
                'customer_id':      str(row.client_id),
                'customer_name':    row.customer_name    or row.client_company_name,
                'customer_address': row.customer_address or row.client_address,
                'customer_phone':   row.customer_phone   or row.client_phone,
                'customer_email':   row.customer_email,
                'client_id':        row.client_id,
                'project_id':       row.project_id,
                'invoice_date':     row.invoice_date.isoformat() if row.invoice_date else None,
                'due_date':         row.due_date.isoformat()     if row.due_date     else None,
                'subtotal':         round(subtotal_after_section_discounts, 2),
                'vat_rate':         vat_rate_val,
                'vat_amount':       computed_vat,
                'total':            computed_total,
                'global_discount_percent': float(row.global_discount_percent) if getattr(row, 'global_discount_percent', None) is not None else 0.0,
                'status':           row.status,
                'notes':            row.notes or row.description,
                'room_name':        row.room_name        or '',
                'carcass_colour':   row.carcass_colour   or '',
                'door_colour':      row.door_colour       or '',
                'panelwork_colour': row.panelwork_colour or '',
                'door_style':       row.door_style       or '',
                'door_type':        row.door_type        or 'Carcass Only',
                'room_type':        row.room_type        or 'Kitchen',
                'filler_type':      getattr(row, 'filler_type', None) or 'Basic Slab',
                'filler_door_type': getattr(row, 'filler_type', None) or 'Basic Slab',
                'deposit_paid':     float(row.deposit_paid or 0),
                'total_remaining':  max(0, round(computed_total - float(row.deposit_paid or 0), 2)),
                'section_discounts': (_json.loads(row.section_discounts) if isinstance(row.section_discounts, str) else row.section_discounts) if getattr(row, 'section_discounts', None) else {},
                'additional_terms': _json.loads(getattr(row, 'additional_terms', None) or '[]') if isinstance(getattr(row, 'additional_terms', None), str) else (getattr(row, 'additional_terms', None) or []),
                'additional_notes': getattr(row, 'additional_notes', None) or '',
                'signature_type':  getattr(row, 'signature_type', None) or 'none',
                'signature_image': getattr(row, 'signature_image', None) or '',
                'signature_text':  getattr(row, 'signature_text', None) or '',
                'signature_name':  getattr(row, 'signature_name', None) or '',
                'signature_date':  getattr(row, 'signature_date', None) or '',
                'quote_reference': getattr(row, 'quote_reference', None) or '',
                'created_at':       row.created_at.isoformat() if row.created_at else None,
                'items': [
                    {
                        'id':               i.invoice_details_id,
                        'item_id':          i.invoice_details_id,
                        'item':             i.item_name or i.service_name or '',
                        'item_name':        i.item_name or i.service_name or '',
                        'description':      i.description or '',
                        'color':            i.color or '',
                        'quantity':         i.quantity or 1,
                        'amount':           float(i.amount or 0),
                        'width':            i.width,
                        'height':           i.height,
                        'depth':            i.depth,
                        'discount_percent': float(i.discount_percent or 0),
                        'discounted_total': float(i.discounted_amount or i.amount or 0),
                        'line_total':       float(i.amount or 0) * int(i.quantity or 1),
                        'section':          i.section or 'Furniture',
                        'is_sub_item':      bool(i.is_sub_item) if i.is_sub_item is not None else False,
                    }
                    for i in items
                    if (i.item_name or i.service_name or i.description or (i.amount and float(i.amount) > 0))
                ]
            }), 200

        elif request.method == 'PUT':
            data          = request.get_json(silent=True) or {}
            update_fields = []
            params        = {'id': invoice_id, 't': str(tenant_id)}

            for field in ['customer_name', 'customer_address', 'customer_phone',
                        'customer_email', 'status', 'notes', 'invoice_date', 'due_date',
                        'room_name', 'carcass_colour', 'door_colour', 'panelwork_colour',
                        'door_style', 'deposit_paid', 'total_remaining',
                        'door_type', 'room_type', 'filler_type', 'invoice_number',
                        'additional_notes']:
                if field in data and data[field] is not None and data[field] != '':
                    update_fields.append(f"{field} = :{field}")
                    params[field] = data[field]

            if 'additional_terms' in data:
                update_fields.append("additional_terms = :additional_terms")
                params['additional_terms'] = json.dumps(data['additional_terms'])

            for sig_field in ['signature_type', 'signature_image', 'signature_text', 'signature_name', 'signature_date']:
                if sig_field in data:
                    update_fields.append(f"{sig_field} = :{sig_field}")
                    params[sig_field] = data[sig_field]

            if 'quote_reference' in data:
                update_fields.append("quote_reference = :quote_reference")
                params['quote_reference'] = data['quote_reference'] or None

            if 'filler_door_type' in data and 'filler_type' not in data:
                update_fields.append("filler_type = :filler_type")
                params['filler_type'] = data['filler_door_type']
                update_fields.append("section_discounts = :section_discounts")
                sd = data['section_discounts']
                params['section_discounts'] = json.dumps(sd) if isinstance(sd, dict) else sd

            if 'vat_rate' in data:
                update_fields.append("vat_rate = :vat_rate")
                params['vat_rate'] = data['vat_rate']

            if 'items' in data:
                session.execute(
                    text('DELETE FROM "StreemLyne_MT"."Invoice_Details" WHERE invoice_id = :id'),
                    {'id': invoice_id}
                )

                for item in data['items']:
                    if not item.get('item') and not item.get('description') and not item.get('amount'):
                        continue
                    unit_price = float(item.get('amount', 0))
                    qty = int(item.get('quantity', 1))
                    session.execute(
                        text("""
                            INSERT INTO "StreemLyne_MT"."Invoice_Details"
                            (invoice_id, item_name, description, color, quantity, amount,
                            unit_price, service_name, width, height, depth,
                            discount_percent, discounted_amount, section, is_sub_item)
                            VALUES
                            (:invoice_id, :item_name, :desc, :color, :qty, :amt,
                            :unit_price, :service_name, :w, :h, :d, :dp, :da, :section, :is_sub_item)
                        """),
                        {
                            'invoice_id':   invoice_id,
                            'item_name':    item.get('item', ''),
                            'desc':         item.get('description', ''),
                            'color':        item.get('color', item.get('colour', '')),
                            'qty':          qty,
                            'amt':          unit_price,
                            'unit_price':   unit_price,
                            'service_name': item.get('item', ''),
                            'w':            item.get('width'),
                            'h':            item.get('height'),
                            'd':            item.get('depth'),
                            'dp':           item.get('discount_percent', 0),
                            'da':           item.get('discounted_total', unit_price * qty),
                            'section':      item.get('section', 'Furniture'),
                            'is_sub_item':  bool(item.get('is_sub_item', False)),
                        }
                    )

                # ✅ Recompute subtotal with section discounts applied before storing
                import json as _json3
                section_discounts_for_save = {}
                if 'section_discounts' in data:
                    sd = data['section_discounts']
                    section_discounts_for_save = sd if isinstance(sd, dict) else _json3.loads(sd)

                section_totals: dict = {}
                for item in data['items']:
                    if not item.get('item') and not item.get('description') and not item.get('amount'):
                        continue
                    sec = item.get('section', 'Furniture')
                    unit = float(item.get('amount', 0))
                    qty  = int(item.get('quantity', 1))
                    disc = float(item.get('discount_percent', 0))
                    line = item.get('discounted_total') or (unit * qty * (1 - disc / 100))
                    section_totals[sec] = section_totals.get(sec, 0) + float(line)

                subtotal_after_sd = sum(
                    v * (1 - float(section_discounts_for_save.get(k, 0)) / 100)
                    for k, v in section_totals.items()
                )

                global_disc           = float(data.get('global_discount_percent', 0))
                subtotal_after_global = subtotal_after_sd * (1 - global_disc / 100)
                vat_rate              = float(data.get('vat_rate', 20))
                vat_amount            = subtotal_after_global * (vat_rate / 100)
                total_amt             = subtotal_after_global + vat_amount

                update_fields += [
                    "subtotal = :subtotal", "sub_total = :subtotal",
                    "vat_amount = :vat_amount", "vat = :vat_amount",
                    "total_amount = :total_amount",
                ]
                params.update({
                    'subtotal':     round(subtotal_after_global, 2),
                    'vat_amount':   round(vat_amount, 2),
                    'total_amount': round(total_amt, 2),
                    'vat_rate':     vat_rate,
                })
                if 'vat_rate = :vat_rate' not in update_fields:
                    update_fields.append("vat_rate = :vat_rate")

            if not update_fields:
                return jsonify({'error': 'No fields to update'}), 400

            update_fields.append("updated_at = CURRENT_TIMESTAMP")
            session.execute(
                text(f"""
                    UPDATE "StreemLyne_MT"."Invoice_Master"
                    SET {', '.join(update_fields)}
                    WHERE invoice_id = :id AND tenant_id = :t
                """),
                params
            )
            session.commit()
            return jsonify({'success': True, 'message': 'Invoice updated successfully'}), 200

        elif request.method == 'DELETE':
            session.execute(
                text('DELETE FROM "StreemLyne_MT"."Invoice_Details" WHERE invoice_id = :id'),
                {'id': invoice_id}
            )
            session.execute(
                text('DELETE FROM "StreemLyne_MT"."Invoice_Master" WHERE invoice_id = :id AND tenant_id = :t'),
                {'id': invoice_id, 't': str(tenant_id)}
            )
            session.commit()
            return jsonify({'success': True, 'message': 'Invoice deleted'}), 200

    except Exception as e:
        session.rollback()
        current_app.logger.exception(f"Error handling invoice {invoice_id}: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()

# ============================================================================
# DELETE SINGLE ITEM
# ============================================================================

@invoice_bp.route('/invoices/<int:invoice_id>/items/<int:item_id>', methods=['DELETE'])
@token_required
@require_tenant
def delete_invoice_item(invoice_id, item_id, tenant_id, employee_id):
    session = SessionLocal()
    try:
        result = session.execute(
            text("""
                DELETE FROM "StreemLyne_MT"."Invoice_Details"
                WHERE invoice_details_id = :iid AND invoice_id = :inv
            """),
            {'iid': item_id, 'inv': invoice_id}
        )
        if result.rowcount == 0:
            return jsonify({'error': 'Item not found'}), 404

        new_total = calculate_invoice_total(session, invoice_id)
        session.execute(
            text("""
                UPDATE "StreemLyne_MT"."Invoice_Master"
                SET subtotal = :t, sub_total = :t, total_amount = :t,
                    updated_at = CURRENT_TIMESTAMP
                WHERE invoice_id = :id AND tenant_id = :tenant
            """),
            {'t': new_total, 'id': invoice_id, 'tenant': str(tenant_id)}
        )
        session.commit()
        return jsonify({'success': True, 'new_total': new_total}), 200

    except Exception as e:
        session.rollback()
        current_app.logger.exception(f"Error deleting invoice item: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


# ============================================================================
# PDF
# ============================================================================

@invoice_bp.route('/invoices/<int:invoice_id>/pdf', methods=['GET'])
def download_invoice_pdf(invoice_id):
    session = SessionLocal()
    try:
        import json

        row = session.execute(
            text("""
                SELECT i.*, c.client_company_name, c.address AS client_address, c.client_phone
                FROM "StreemLyne_MT"."Invoice_Master" i
                INNER JOIN "StreemLyne_MT"."Client_Master" c ON i.client_id = c.client_id
                WHERE i.invoice_id = :id
            """),
            {'id': invoice_id}
        ).fetchone()

        if not row:
            return jsonify({'error': 'Invoice not found'}), 404

        items = session.execute(
            text("""
                SELECT * FROM "StreemLyne_MT"."Invoice_Details"
                WHERE invoice_id = :id ORDER BY invoice_details_id
            """),
            {'id': invoice_id}
        ).fetchall()

        # ── Parse section discounts ───────────────────────────────────────
        section_discounts_raw = getattr(row, 'section_discounts', None)
        section_discounts = (json.loads(section_discounts_raw) if isinstance(section_discounts_raw, str) else section_discounts_raw) if section_discounts_raw else {}

        SECTIONS = ['Furniture', 'Fillers and End Panels', 'Accessories', 'Handles',
                    'Appliances', 'Sink and Tap', 'Worktops', 'Fittings']

        pdf = PDF('P', 'mm', 'A4')
        pdf.doc_title = 'Invoice'
        pdf.alias_nb_pages()
        pdf.set_auto_page_break(auto=True, margin=22)
        pdf.add_page()

        # ── Customer section (2-column) ───────────────────────────────────
        cust_name    = row.customer_name    or row.client_company_name or 'N/A'
        cust_address = row.customer_address or row.client_address      or 'N/A'
        cust_phone   = row.customer_phone   or row.client_phone        or ''
        inv_date     = row.invoice_date.strftime('%d/%m/%Y') if row.invoice_date else 'N/A'
        due_date     = row.due_date.strftime('%d/%m/%Y')     if row.due_date     else 'N/A'

        right_rows = [
            ('Invoice No',  row.invoice_number or 'N/A'),
            ('Date',        inv_date),
            ('Due Date',    due_date),
        ]
        for field, label in [
            ('room_name',        'Room Name'),
            ('carcass_colour',   'Carcass Colour'),
            ('door_colour',      'Door Colour'),
            ('panelwork_colour', 'Panelwork'),
            ('door_style',       'Door Style'),
        ]:
            v = getattr(row, field, None)
            if v:
                right_rows.append((label, v))

        left_rows = [cust_name, cust_address]
        if cust_phone:
            left_rows.append(cust_phone)

        pdf.draw_two_col_customer('Bill To', left_rows, 'Invoice Details', right_rows)

        # ── Bank details (subtle) ─────────────────────────────────────────
        pdf.set_font('Arial', '', 7.5)
        pdf.set_text_color(100, 100, 100)
        pdf.cell(0, 4, 'BACS: Atelier Luxe Interiors LTD  \xb7  ClearBank  \xb7  Sort: 04-06-05  \xb7  Acc: 31621197  \xb7  Ref: your name / road', 0, 1, 'L')
        pdf.set_text_color(0, 0, 0)
        pdf.ln(5)

        # ── Items by section ──────────────────────────────────────────────
        headers = ['ITEM', 'DESCRIPTION', 'COLOUR', 'QTY']
        widths  = [28, 115, 25, 22]

        valid_items = [
            i for i in items
            if (i.item_name or i.service_name or '').strip() or
               (i.description or '').strip() or
               (i.amount and float(i.amount) > 0)
        ]

        ROW_H       = 8
        PAGE_BOTTOM = pdf.h - 30
        subtotal_after_section_discounts = 0.0

        def draw_item_row(name, desc, color, qty, indent=False):
            clean_name = (name or '').encode('latin-1', errors='ignore').decode('latin-1')
            display_name = ('  - ' + clean_name) if indent else clean_name
            clean_desc = (desc or '').strip()
            for suffix in [' - Standard', '- Standard', ' - Carcass Only', '- Carcass Only']:
                if clean_desc.endswith(suffix):
                    clean_desc = clean_desc[:-len(suffix)].strip()
            clean_desc = clean_desc.encode('latin-1', errors='ignore').decode('latin-1')
            line_h = 5
            desc_w = widths[1] - 2
            chars_per_line = int(desc_w / 2.05)
            num_lines = max(1, -(-len(clean_desc) // chars_per_line))
            row_h = max(ROW_H, num_lines * line_h + 2)
            x0, y0 = pdf.get_x(), pdf.get_y()
            if indent:
                pdf.set_text_color(80, 80, 80)
            pdf.set_font('Arial', '', 9)
            _name = display_name[:24]
            while _name and pdf.get_string_width(_name) > widths[0] - 1:
                _name = _name[:-1]
            pdf.cell(widths[0], row_h, _name, 0, 0, 'L')
            pdf.cell(widths[1], row_h, '', 0, 0, 'L')
            pdf.cell(widths[2], row_h, (color or '')[:16], 0, 0, 'C')
            pdf.cell(widths[3], row_h, str(int(qty or 1)), 0, 1, 'C')
            pdf.set_xy(x0 + widths[0] + 1, y0 + 1)
            pdf.set_font('Arial', '', 8.5)
            pdf.multi_cell(desc_w, line_h, clean_desc, 0, 'L')
            pdf.set_xy(x0, y0 + row_h)
            # thin rule below row
            pdf.set_draw_color(220, 220, 220)
            pdf.set_line_width(0.2)
            pdf.line(x0, pdf.get_y(), x0 + sum(widths), pdf.get_y())
            pdf.set_text_color(0, 0, 0)

        for section in SECTIONS:
            section_items = [i for i in valid_items
                             if (getattr(i, 'section', None) or 'Furniture') == section]
            if not section_items:
                continue

            if pdf.get_y() + 20 + ROW_H > PAGE_BOTTOM:
                pdf.add_page()

            pdf.ln(4)
            pdf.draw_section_label(section)
            pdf.ln(2)
            pdf.draw_table_header(headers, widths)

            section_raw      = 0.0
            section_subtotal = 0.0

            for item in section_items:
                if pdf.get_y() + ROW_H > PAGE_BOTTOM:
                    pdf.add_page()
                    pdf.draw_table_header(headers, widths)

                is_sub = bool(getattr(item, 'is_sub_item', False))
                raw    = round(float(item.amount or 0) * int(item.quantity or 1), 2)
                section_raw += raw
                disc_amt  = getattr(item, 'discounted_total', None) or getattr(item, 'discounted_amount', None)
                effective = round(float(disc_amt), 2) if disc_amt is not None and float(disc_amt) > 0 else raw
                section_subtotal += effective

                draw_item_row(
                    item.item_name or getattr(item, 'service_name', '') or '',
                    item.description or '',
                    item.color or '',
                    item.quantity or 1,
                    indent=is_sub,
                )

            sec_discount_amt = round(section_raw - section_subtotal, 2)
            subtotal_after_section_discounts = round(subtotal_after_section_discounts + section_subtotal, 2)

        # ── Grand totals ──────────────────────────────────────────────────
        if pdf.get_y() > pdf.h - 90:
            pdf.add_page()
        pdf.ln(3)

        vat_rate             = float(row.vat_rate) if row.vat_rate is not None else 20.0
        global_discount_pct  = float(getattr(row, 'global_discount_percent', 0) or 0)
        global_discount_amt  = round(subtotal_after_section_discounts * (global_discount_pct / 100), 2)
        subtotal_after_disc  = round(subtotal_after_section_discounts - global_discount_amt, 2)
        vat_amount           = round(subtotal_after_disc * (vat_rate / 100), 2)
        total                = round(subtotal_after_disc + vat_amount, 2)
        deposit              = float(row.deposit_paid or 0)
        remaining            = max(0, round(total - deposit, 2))

        totals_rows = [('Subtotal', f'\xa3{subtotal_after_section_discounts:.2f}')]
        if global_discount_pct > 0:
            totals_rows.append((f'Discount ({global_discount_pct:.2f}%)', f'-\xa3{global_discount_amt:.2f}'))
        totals_rows.append((f'VAT ({vat_rate:.0f}%)', f'\xa3{vat_amount:.2f}'))
        if deposit > 0:
            totals_rows.append((f'Deposit Paid', f'\xa3{deposit:.2f}'))

        balance_label = 'Balance Due' if deposit > 0 else 'Total'
        balance_value = f'\xa3{remaining:.2f}' if deposit > 0 else f'\xa3{total:.2f}'
        pdf.draw_grand_totals(totals_rows, balance_label, balance_value)

        # ── Payment terms note ────────────────────────────────────────────
        if pdf.get_y() + 40 > pdf.h - 20:
            pdf.add_page()

        pdf.set_font('Arial', '', 8.5)
        pdf.set_text_color(80, 80, 80)
        pdf.cell(0, 5, 'Only BACS or Cash will be accepted on Delivery and Completion.', 0, 1, 'L')
        pdf.cell(0, 5, 'Payment is due within 30 days of the invoice date.', 0, 1, 'L')

        # Additional terms (optional)
        extra_terms_raw = getattr(row, 'additional_terms', None)
        if extra_terms_raw:
            try:
                extra_terms = _json.loads(extra_terms_raw) if isinstance(extra_terms_raw, str) else extra_terms_raw
            except Exception:
                extra_terms = []
            for term in [t for t in (extra_terms or []) if t and str(t).strip()]:
                pdf.cell(0, 5, pdf._enc(str(term)), 0, 1, 'L')

        pdf.set_text_color(0, 0, 0)
        pdf.ln(4)

        # Additional notes (optional)
        extra_notes = getattr(row, 'additional_notes', None) or ''
        if extra_notes.strip():
            pdf.set_font('Arial', 'B', 8.5)
            pdf.set_text_color(80, 80, 80)
            pdf.cell(0, 5, 'Notes', 0, 1, 'L')
            pdf.set_font('Arial', '', 8.5)
            for line in extra_notes.strip().splitlines():
                pdf.multi_cell(0, 5, pdf._enc(line or ''), 0, 'L')
            pdf.set_text_color(0, 0, 0)
            pdf.ln(4)

        pdf.draw_signature_data(
            sig_type=getattr(row, 'signature_type', None) or 'none',
            sig_image=getattr(row, 'signature_image', None) or '',
            sig_text=getattr(row, 'signature_text', None) or '',
            sig_name=getattr(row, 'signature_name', None) or '',
            sig_date=getattr(row, 'signature_date', None) or '',
        )

        out = pdf.output(dest='S')
        if isinstance(out, str):
            out = out.encode('latin-1')
        buf  = BytesIO(bytes(out))
        name = f"Invoice_{row.invoice_number}_{(row.customer_name or 'Customer').replace(' ', '_')}.pdf"
        return send_file(buf, mimetype='application/pdf', as_attachment=False, download_name=name)

    except Exception as e:
        current_app.logger.exception(f"Invoice PDF generation failed: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()

# ============================================================================
# PROFORMA INVOICE ROUTES
# Stored in Invoice_Master with status='Proforma Draft', number prefix PRO-
# ============================================================================

@invoice_bp.route('/proformas', methods=['GET'])
@token_required
@require_tenant
def get_proformas(tenant_id, employee_id):
    session = SessionLocal()
    try:
        client_id = (
            request.args.get('client_id') or
            request.args.get('customer_id') or
            request.args.get('id')
        )
        if not client_id:
            return jsonify([]), 200

        rows = session.execute(
            text("""
                SELECT i.*, c.client_company_name,
                    (SELECT COUNT(*) FROM "StreemLyne_MT"."Invoice_Details"
                     WHERE invoice_id = i.invoice_id) AS items_count
                FROM "StreemLyne_MT"."Invoice_Master" i
                INNER JOIN "StreemLyne_MT"."Client_Master" c ON i.client_id = c.client_id
                WHERE i.tenant_id = :t AND i.client_id = :c
                  AND i.status LIKE 'Proforma%'
                ORDER BY i.created_at DESC
            """),
            {'t': str(tenant_id), 'c': int(client_id)}
        ).fetchall()

        return jsonify([{
            'id':             r.invoice_id,
            'invoice_id':     r.invoice_id,
            'invoice_number': r.invoice_number,
            'client_id':      r.client_id,
            'customer_id':    r.client_id,
            'customer_name':  r.customer_name or r.client_company_name,
            'total':          float(r.total_amount) if r.total_amount else 0.0,
            'status':         r.status,
            'items_count':    r.items_count or 0,
            'invoice_date':   r.invoice_date.isoformat() if r.invoice_date else None,
            'due_date':       r.due_date.isoformat()     if r.due_date     else None,
            'created_at':     r.created_at.isoformat()   if r.created_at   else None,
        } for r in rows]), 200

    except Exception as e:
        current_app.logger.exception(f"Error fetching proformas: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@invoice_bp.route('/proformas', methods=['POST'])
@token_required
@require_tenant
def create_proforma(tenant_id, employee_id):
    session = SessionLocal()
    try:
        data      = request.get_json(silent=True) or {}
        client_id = data.get('client_id') or data.get('customer_id') or data.get('customerId')

        if not client_id:
            return jsonify({'error': 'client_id is required'}), 400

        client = session.execute(
            text('SELECT client_id FROM "StreemLyne_MT"."Client_Master" WHERE client_id = :c AND tenant_id = :t'),
            {'c': int(client_id), 't': str(tenant_id)}
        ).fetchone()
        if not client:
            return jsonify({'error': 'Client not found'}), 404

        pro_seq = session.execute(
            text("""
                SELECT COALESCE(MAX(
                    CAST(NULLIF(REGEXP_REPLACE(invoice_number, '^PRO-(\\d+)$', '\\1'), invoice_number) AS INTEGER)
                ), 0) as max_seq
                FROM "StreemLyne_MT"."Invoice_Master"
                WHERE tenant_id = :t AND invoice_number LIKE 'PRO-%'
            """),
            {'t': str(tenant_id)}
        ).fetchone()
        invoice_number = data.get('invoice_number') or f"PRO-{pro_seq.max_seq + 1}"

        items_data   = data.get('items', [])
        subtotal     = float(data.get('subtotal', 0))
        vat_rate     = float(data.get('vat_percentage', data.get('vat_rate', 20)))
        vat_amount   = subtotal * (vat_rate / 100)
        total_amount = subtotal + vat_amount

        invoice_date = data.get('invoice_date') or datetime.utcnow().strftime('%Y-%m-%d')
        due_date     = data.get('due_date') or (
            datetime.strptime(invoice_date, '%Y-%m-%d') + timedelta(days=30)
        ).strftime('%Y-%m-%d')

        result = session.execute(
            text("""
                INSERT INTO "StreemLyne_MT"."Invoice_Master"
                (tenant_id, client_id, project_id, invoice_number, invoice_date, due_date,
                 status, notes, customer_name, customer_address, customer_phone, customer_email,
                 subtotal, vat_rate, vat_amount, total_amount, created_by_employee_id,
                 sub_total, vat, description, tax_id,
                 room_name, carcass_colour, door_colour, panelwork_colour, door_style,
                 deposit_paid, total_remaining, door_type, room_type, filler_type,
                 additional_terms, additional_notes,
                 signature_type, signature_image, signature_text, signature_name, signature_date)
                VALUES
                (:tenant_id, :client_id, :project_id, :invoice_number, :invoice_date, :due_date,
                 :status, :notes, :customer_name, :customer_address, :customer_phone, :customer_email,
                 :subtotal, :vat_rate, :vat_amount, :total_amount, :created_by,
                 :subtotal, :vat_amount, :notes, :tax_id,
                 :room_name, :carcass_colour, :door_colour, :panelwork_colour, :door_style,
                 :deposit_paid, :total_remaining, :door_type, :room_type, :filler_type,
                 :additional_terms, :additional_notes,
                 :signature_type, :signature_image, :signature_text, :signature_name, :signature_date)
                RETURNING invoice_id
            """),
            {
                'tenant_id':        str(tenant_id),
                'client_id':        int(client_id),
                'project_id':       data.get('project_id'),
                'invoice_number':   invoice_number,
                'invoice_date':     invoice_date,
                'due_date':         due_date,
                'status':           data.get('status', 'Draft'),
                'notes':            data.get('notes', ''),
                'customer_name':    data.get('customer_name', ''),
                'customer_address': data.get('customer_address', ''),
                'customer_phone':   data.get('customer_phone', ''),
                'customer_email':   data.get('customer_email', ''),
                'subtotal':         subtotal,
                'vat_rate':         vat_rate,
                'vat_amount':       vat_amount,
                'total_amount':     total_amount,
                'created_by':       employee_id,
                'tax_id':           1,
                'room_name':        data.get('room_name', ''),
                'carcass_colour':   data.get('carcass_colour', ''),
                'door_colour':      data.get('door_colour', ''),
                'panelwork_colour': data.get('panelwork_colour', ''),
                'door_style':       data.get('door_style', ''),
                'deposit_paid':     float(data.get('deposit_paid', 0)),
                'total_remaining':  float(data.get('total_remaining', 0)),
                'door_type':        data.get('door_type', 'Carcass Only'),
                'room_type':        data.get('room_type', 'Kitchen'),
                'filler_type':      data.get('filler_type') or data.get('filler_door_type', 'Basic Slab'),
                'additional_terms': json.dumps(data.get('additional_terms', [])),
                'additional_notes': data.get('additional_notes', ''),
                'signature_type':  data.get('signature_type', 'none'),
                'signature_image': data.get('signature_image'),
                'signature_text':  data.get('signature_text'),
                'signature_name':  data.get('signature_name', ''),
                'signature_date':  data.get('signature_date', ''),
            }
        )

        invoice_id = result.fetchone().invoice_id

        for item in items_data:
            if not item.get('item') and not item.get('description') and not item.get('amount'):
                continue
            unit_price = float(item.get('amount', 0))
            qty = int(item.get('quantity', 1))
            session.execute(
                text("""
                    INSERT INTO "StreemLyne_MT"."Invoice_Details"
                    (invoice_id, item_name, description, color, quantity, amount,
                     unit_price, service_name, width, height, depth, discount_percent, discounted_amount)
                    VALUES (:iid, :name, :desc, :color, :qty, :amt, :up, :name, :w, :h, :d, :dp, :da)
                """),
                {
                    'iid': invoice_id, 'name': item.get('item', ''), 'desc': item.get('description', ''),
                    'color': item.get('color', item.get('colour', '')), 'qty': qty, 'amt': unit_price,
                    'up': unit_price, 'w': item.get('width'), 'h': item.get('height'),
                    'd': item.get('depth'), 'dp': item.get('discount_percent', 0),
                    'da': item.get('discounted_total', unit_price * qty),
                }
            )

        session.commit()
        return jsonify({'invoice_id': invoice_id, 'invoice_number': invoice_number,
                        'message': 'Proforma invoice created successfully'}), 201

    except Exception as e:
        session.rollback()
        current_app.logger.exception(f"Error creating proforma: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@invoice_bp.route('/proformas/<int:invoice_id>', methods=['GET', 'PUT', 'DELETE'])
@token_required
@require_tenant
def handle_proforma(invoice_id, tenant_id, employee_id):
    session = SessionLocal()
    try:
        if request.method == 'GET':
            row = session.execute(
                text("""
                    SELECT i.*, c.client_company_name, c.address AS client_address, c.client_phone
                    FROM "StreemLyne_MT"."Invoice_Master" i
                    INNER JOIN "StreemLyne_MT"."Client_Master" c ON i.client_id = c.client_id
                    WHERE i.invoice_id = :id AND i.tenant_id = :t
                """),
                {'id': invoice_id, 't': str(tenant_id)}
            ).fetchone()
            if not row:
                return jsonify({'error': 'Proforma not found'}), 404

            items = session.execute(
                text('SELECT * FROM "StreemLyne_MT"."Invoice_Details" WHERE invoice_id = :id ORDER BY invoice_details_id'),
                {'id': invoice_id}
            ).fetchall()

            return jsonify({
                'id': row.invoice_id, 'invoice_id': row.invoice_id,
                'invoice_number': row.invoice_number, 'customer_id': str(row.client_id),
                'customer_name': row.customer_name or row.client_company_name,
                'customer_address': row.customer_address or row.client_address,
                'customer_phone': row.customer_phone or row.client_phone,
                'customer_email': row.customer_email, 'client_id': row.client_id,
                'invoice_date': row.invoice_date.isoformat() if row.invoice_date else None,
                'due_date': row.due_date.isoformat() if row.due_date else None,
                'subtotal': float(row.subtotal or row.sub_total or 0),
                'vat_rate': float(row.vat_rate) if row.vat_rate is not None else 20.0,
                'vat_amount': float(row.vat_amount or row.vat or 0),
                'total': float(row.total_amount or 0),
                'status': row.status, 'notes': row.notes,
                'filler_type':      getattr(row, 'filler_type', None) or 'Basic Slab',
                'filler_door_type': getattr(row, 'filler_type', None) or 'Basic Slab',
                'door_type':        getattr(row, 'door_type', None) or 'Carcass Only',
                'room_type':        getattr(row, 'room_type', None) or 'Kitchen',
                'additional_terms': json.loads(getattr(row, 'additional_terms', None) or '[]') if isinstance(getattr(row, 'additional_terms', None), str) else (getattr(row, 'additional_terms', None) or []),
                'additional_notes': getattr(row, 'additional_notes', None) or '',
                'signature_type':  getattr(row, 'signature_type', None) or 'none',
                'signature_image': getattr(row, 'signature_image', None) or '',
                'signature_text':  getattr(row, 'signature_text', None) or '',
                'signature_name':  getattr(row, 'signature_name', None) or '',
                'signature_date':  getattr(row, 'signature_date', None) or '',
                'created_at': row.created_at.isoformat() if row.created_at else None,
                'items': [
                    {
                        'id':               i.invoice_details_id,
                        'item_id':          i.invoice_details_id,
                        'item':             i.item_name or i.service_name or '',
                        'item_name':        i.item_name or i.service_name or '',
                        'description':      i.description or '',
                        'color':            i.color or '',
                        'quantity':         i.quantity or 1,
                        'amount':           float(i.amount or 0),
                        'width':            i.width,
                        'height':           i.height,
                        'depth':            i.depth,
                        'discount_percent': float(i.discount_percent or 0),
                        'discounted_total': float(i.discounted_amount or i.amount or 0),
                        'line_total':       float(i.amount or 0) * int(i.quantity or 1),
                        'section':          i.section or 'Furniture',
                    }
                    for i in items
                    if (i.item_name or i.service_name or i.description or (i.amount and float(i.amount) > 0))
                ]
            }), 200

        elif request.method == 'PUT':
            data = request.get_json(silent=True) or {}
            update_fields = []
            params = {'id': invoice_id, 't': str(tenant_id)}

            for field in ['customer_name', 'customer_address', 'customer_phone',
                          'customer_email', 'status', 'notes', 'invoice_date', 'due_date',
                          'door_type', 'room_type', 'filler_type',
                          'room_name', 'carcass_colour', 'door_colour', 'panelwork_colour', 'door_style',
                          'deposit_paid', 'total_remaining', 'invoice_number', 'additional_notes']:
                if field in data and data[field] is not None and data[field] != '':
                    update_fields.append(f"{field} = :{field}")
                    params[field] = data[field]

            if 'additional_terms' in data:
                update_fields.append("additional_terms = :additional_terms")
                params['additional_terms'] = json.dumps(data['additional_terms'])

            for sig_field in ['signature_type', 'signature_image', 'signature_text', 'signature_name', 'signature_date']:
                if sig_field in data:
                    update_fields.append(f"{sig_field} = :{sig_field}")
                    params[sig_field] = data[sig_field]

            if 'vat_rate' in data:
                update_fields.append("vat_rate = :vat_rate")
                params['vat_rate'] = data['vat_rate']

            if 'filler_door_type' in data and 'filler_type' not in data:
                update_fields.append("filler_type = :filler_type")
                params['filler_type'] = data['filler_door_type']

            if 'items' in data:
                session.execute(
                    text('DELETE FROM "StreemLyne_MT"."Invoice_Details" WHERE invoice_id = :id'),
                    {'id': invoice_id}
                )
                total = 0.0
                for item in data['items']:
                    if not item.get('item') and not item.get('description') and not item.get('amount'):
                        continue
                    unit_price = float(item.get('amount', 0))
                    qty = int(item.get('quantity', 1))
                    session.execute(
                        text("""
                            INSERT INTO "StreemLyne_MT"."Invoice_Details"
                            (invoice_id, item_name, description, color, quantity, amount,
                             unit_price, service_name, width, height, depth, discount_percent, discounted_amount)
                            VALUES (:iid, :name, :desc, :color, :qty, :amt, :up, :name, :w, :h, :d, :dp, :da)
                        """),
                        {
                            'iid': invoice_id, 'name': item.get('item', ''), 'desc': item.get('description', ''),
                            'color': item.get('color', item.get('colour', '')), 'qty': qty, 'amt': unit_price,
                            'up': unit_price, 'w': item.get('width'),
                            'h': item.get('height'), 'd': item.get('depth'),
                            'dp': item.get('discount_percent', 0), 'da': item.get('discounted_total', unit_price * qty),
                        }
                    )
                    total += unit_price * qty

                vat_rate = float(data.get('vat_rate', 20))
                vat_amount = total * (vat_rate / 100)
                update_fields += [
                    "subtotal = :subtotal", "sub_total = :subtotal",
                    "vat_amount = :vat_amount", "vat = :vat_amount", "total_amount = :total_amount",
                ]
                params.update({'subtotal': total, 'vat_amount': vat_amount,
                               'total_amount': total + vat_amount, 'vat_rate': vat_rate})
                if 'vat_rate = :vat_rate' not in update_fields:
                    update_fields.append("vat_rate = :vat_rate")

            if not update_fields:
                return jsonify({'error': 'No fields to update'}), 400

            update_fields.append("updated_at = CURRENT_TIMESTAMP")
            session.execute(
                text(f'UPDATE "StreemLyne_MT"."Invoice_Master" SET {", ".join(update_fields)} WHERE invoice_id = :id AND tenant_id = :t'),
                params
            )
            session.commit()
            return jsonify({'success': True, 'message': 'Proforma updated successfully'}), 200

        elif request.method == 'DELETE':
            session.execute(text('DELETE FROM "StreemLyne_MT"."Invoice_Details" WHERE invoice_id = :id'), {'id': invoice_id})
            session.execute(text('DELETE FROM "StreemLyne_MT"."Invoice_Master" WHERE invoice_id = :id AND tenant_id = :t'), {'id': invoice_id, 't': str(tenant_id)})
            session.commit()
            return jsonify({'success': True, 'message': 'Proforma deleted'}), 200

    except Exception as e:
        session.rollback()
        current_app.logger.exception(f"Error handling proforma {invoice_id}: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@invoice_bp.route('/proformas/<int:invoice_id>/pdf', methods=['GET'])
def download_proforma_pdf(invoice_id):
    session = SessionLocal()
    try:
        row = session.execute(
            text("""
                SELECT i.*, c.client_company_name, c.address AS client_address, c.client_phone
                FROM "StreemLyne_MT"."Invoice_Master" i
                INNER JOIN "StreemLyne_MT"."Client_Master" c ON i.client_id = c.client_id
                WHERE i.invoice_id = :id
            """),
            {'id': invoice_id}
        ).fetchone()
        if not row:
            return jsonify({'error': 'Proforma not found'}), 404

        items = session.execute(
            text('SELECT * FROM "StreemLyne_MT"."Invoice_Details" WHERE invoice_id = :id ORDER BY invoice_details_id'),
            {'id': invoice_id}
        ).fetchall()

        SECTIONS = ['Furniture', 'Fillers and End Panels', 'Accessories', 'Handles',
                    'Appliances', 'Sink and Tap', 'Worktops', 'Fittings']

        pdf = PDF('P', 'mm', 'A4')
        pdf.doc_title = 'Proforma Invoice'
        pdf.alias_nb_pages()
        pdf.add_page()
        pdf.set_auto_page_break(auto=True, margin=22)

        # ── Customer section (2-column) ───────────────────────────────────
        cust_name    = row.customer_name    or row.client_company_name or 'N/A'
        cust_address = row.customer_address or row.client_address      or 'N/A'
        cust_phone   = row.customer_phone   or row.client_phone        or ''
        inv_date     = row.invoice_date.strftime('%d/%m/%Y') if row.invoice_date else 'N/A'
        due_date     = row.due_date.strftime('%d/%m/%Y')     if row.due_date     else 'N/A'

        right_rows = [
            ('Proforma No',  row.invoice_number or 'N/A'),
            ('Date',         inv_date),
            ('Valid Until',  due_date),
        ]
        for field, label in [
            ('room_name',        'Room Name'),
            ('carcass_colour',   'Carcass Colour'),
            ('door_colour',      'Door Colour'),
            ('panelwork_colour', 'Panelwork'),
            ('door_style',       'Door Style'),
        ]:
            v = getattr(row, field, None)
            if v:
                right_rows.append((label, v))

        left_rows = [cust_name, cust_address]
        if cust_phone:
            left_rows.append(cust_phone)

        pdf.draw_two_col_customer('Bill To', left_rows, 'Proforma Details', right_rows)

        # ── Items by section ──────────────────────────────────────────────
        headers = ['ITEM', 'DESCRIPTION', 'COLOUR', 'QTY', 'UNIT PRICE', 'AMOUNT']
        widths  = [22, 86, 22, 12, 24, 24]

        ROW_H       = 8
        PAGE_BOTTOM = pdf.h - 30
        subtotal    = 0.0

        def draw_item_row_pf(name, desc, color, qty, unit, line_total):
            clean_name = (name or '').encode('latin-1', errors='ignore').decode('latin-1')
            clean_desc = (desc or '').strip().encode('latin-1', errors='ignore').decode('latin-1')
            line_h = 5
            desc_w = widths[1] - 2
            chars_per_line = int(desc_w / 2.05)
            num_lines = max(1, -(-len(clean_desc) // chars_per_line))
            row_h = max(ROW_H, num_lines * line_h + 2)
            x0, y0 = pdf.get_x(), pdf.get_y()
            pdf.set_font('Arial', '', 9)
            _name = clean_name[:20]
            while _name and pdf.get_string_width(_name) > widths[0] - 1:
                _name = _name[:-1]
            pdf.cell(widths[0], row_h, _name, 0, 0, 'L')
            pdf.cell(widths[1], row_h, '', 0, 0, 'L')
            pdf.cell(widths[2], row_h, (color or '')[:14], 0, 0, 'C')
            pdf.cell(widths[3], row_h, str(int(qty or 1)), 0, 0, 'C')
            pdf.cell(widths[4], row_h, f'\xa3{unit:.2f}', 0, 0, 'R')
            pdf.cell(widths[5], row_h, f'\xa3{line_total:.2f}', 0, 1, 'R')
            pdf.set_xy(x0 + widths[0] + 1, y0 + 1)
            pdf.set_font('Arial', '', 8.5)
            pdf.multi_cell(desc_w, line_h, clean_desc, 0, 'L')
            pdf.set_xy(x0, y0 + row_h)
            pdf.set_draw_color(220, 220, 220)
            pdf.set_line_width(0.2)
            pdf.line(x0, pdf.get_y(), x0 + sum(widths), pdf.get_y())

        for section in SECTIONS:
            sec_items = [i for i in items
                         if (getattr(i, 'section', None) or 'Furniture') == section
                         and ((i.item_name or getattr(i, 'service_name', '') or '').strip()
                              or (i.description or '').strip()
                              or (i.amount and float(i.amount) > 0))]
            if not sec_items:
                continue

            if pdf.get_y() + 20 + ROW_H > PAGE_BOTTOM:
                pdf.add_page()

            pdf.ln(4)
            pdf.draw_section_label(section)
            pdf.ln(2)
            pdf.draw_table_header(headers, widths)

            sec_total = 0.0
            for item in sec_items:
                if pdf.get_y() + ROW_H > PAGE_BOTTOM:
                    pdf.add_page()
                    pdf.draw_table_header(headers, widths)
                unit = float(item.amount or 0)
                qty  = int(item.quantity or 1)
                lt   = round(unit * qty, 2)
                sec_total += lt
                draw_item_row_pf(
                    item.item_name or getattr(item, 'service_name', '') or '',
                    item.description or '',
                    item.color or '',
                    qty, unit, lt,
                )
            subtotal += sec_total

        # ── Grand totals ──────────────────────────────────────────────────
        if pdf.get_y() > pdf.h - 80:
            pdf.add_page()
        pdf.ln(5)

        vat_rate   = float(row.vat_rate) if row.vat_rate is not None else 20.0
        vat_amount = round(subtotal * (vat_rate / 100), 2)
        total      = round(subtotal + vat_amount, 2)

        pdf.draw_grand_totals(
            [('Subtotal', f'\xa3{subtotal:.2f}'), (f'VAT ({vat_rate:.0f}%)', f'\xa3{vat_amount:.2f}')],
            'Total', f'\xa3{total:.2f}',
        )

        # ── Notes ─────────────────────────────────────────────────────────
        if pdf.get_y() + 35 > pdf.h - 20:
            pdf.add_page()

        pdf.set_font('Arial', '', 8.5)
        pdf.set_text_color(80, 80, 80)
        pdf.cell(0, 5, 'This is a Proforma Invoice \x96 not a VAT invoice.', 0, 1, 'L')
        pdf.cell(0, 5, 'Payment is required before goods are dispatched or work commences.', 0, 1, 'L')

        # Additional terms (optional)
        pf_terms_raw = getattr(row, 'additional_terms', None)
        if pf_terms_raw:
            try:
                pf_extra_terms = json.loads(pf_terms_raw) if isinstance(pf_terms_raw, str) else pf_terms_raw
            except Exception:
                pf_extra_terms = []
            for term in [t for t in (pf_extra_terms or []) if t and str(t).strip()]:
                pdf.cell(0, 5, pdf._enc(str(term)), 0, 1, 'L')

        pdf.set_text_color(0, 0, 0)
        pdf.ln(4)

        # Additional notes (optional)
        pf_notes = getattr(row, 'additional_notes', None) or ''
        if pf_notes.strip():
            pdf.set_font('Arial', 'B', 8.5)
            pdf.set_text_color(80, 80, 80)
            pdf.cell(0, 5, 'Notes', 0, 1, 'L')
            pdf.set_font('Arial', '', 8.5)
            for line in pf_notes.strip().splitlines():
                pdf.multi_cell(0, 5, pdf._enc(line or ''), 0, 'L')
            pdf.set_text_color(0, 0, 0)
            pdf.ln(4)

        pdf.draw_signature_data(
            sig_type=getattr(row, 'signature_type', None) or 'none',
            sig_image=getattr(row, 'signature_image', None) or '',
            sig_text=getattr(row, 'signature_text', None) or '',
            sig_name=getattr(row, 'signature_name', None) or '',
            sig_date=getattr(row, 'signature_date', None) or '',
        )

        out = pdf.output(dest='S')
        if isinstance(out, str):
            out = out.encode('latin-1')
        buf  = BytesIO(bytes(out))
        name = f"Proforma_{row.invoice_number}_{(row.customer_name or 'Customer').replace(' ', '_')}.pdf"
        return send_file(buf, mimetype='application/pdf', as_attachment=False, download_name=name)

    except Exception as e:
        current_app.logger.exception(f"Proforma PDF generation failed: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()