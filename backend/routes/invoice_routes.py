from flask import Blueprint, json, request, jsonify, current_app, send_file
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
    count = session.execute(
        text('SELECT COUNT(*) as c FROM "StreemLyne_MT"."Invoice_Master" WHERE tenant_id = :t'),
        {'t': str(tenant_id)}
    ).fetchone().c
    return f"INV-{datetime.utcnow().strftime('%Y%m%d')}-{count + 1:03d}"


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
                       SUM(COALESCE(amount, 0) * COALESCE(quantity, 1)) as section_total
                FROM "StreemLyne_MT"."Invoice_Details"
                WHERE invoice_id = :iid
                GROUP BY COALESCE(section, 'Furniture')
            """), {'iid': r.invoice_id}).fetchall()

            subtotal_after_section_discounts = 0.0
            for sr in section_rows:
                disc_pct = float(section_discounts.get(sr.section, 0) or 0)
                subtotal_after_section_discounts += float(sr.section_total or 0) * (1 - disc_pct / 100)

            vat_pct = float(getattr(r, 'vat_rate', 20) or 20)
            computed_total = subtotal_after_section_discounts * (1 + vat_pct / 100)

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
                 deposit_paid, total_remaining, door_type, room_type, section_discounts)
                VALUES
                (:tenant_id, :client_id, :project_id, :invoice_number, :invoice_date, :due_date,
                 :status, :notes, :customer_name, :customer_address, :customer_phone, :customer_email,
                 :subtotal, :vat_rate, :vat_amount, :total_amount, :created_by,
                 :subtotal, :vat_amount, :notes, :tax_id,
                 :room_name, :carcass_colour, :door_colour, :panelwork_colour, :door_style,
                 :deposit_paid, :total_remaining, :door_type, :room_type, :section_discounts)
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
                'section_discounts': json.dumps(data.get('section_discounts', {})),
            }
        )
        invoice_id = result.fetchone().invoice_id

        # Insert items into Invoice_Details
        for item in items_data:
            if not item.get('item') and not item.get('description') and not item.get('amount'):
                continue
            amt = float(item.get('amount', item.get('line_total', 0)))
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
                    'amt':          amt,
                    'unit_price':   float(item.get('amount', 0)) / qty if qty else 0,
                    'service_name': item.get('item', ''),
                    'w':            item.get('width'),
                    'h':            item.get('height'),
                    'd':            item.get('depth'),
                    'dp':           item.get('discount_percent', 0),
                    'da':           item.get('discounted_total', amt),
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
                'subtotal':         float(row.subtotal    or row.sub_total or 0),
                'vat_rate':         float(row.vat_rate    or 20),
                'vat_amount':       float(row.vat_amount  or row.vat or 0),
                'total':            float(row.total_amount or 0),
                'status':           row.status,
                'notes':            row.notes or row.description,
                'room_name':        row.room_name        or '',
                'carcass_colour':   row.carcass_colour   or '',
                'door_colour':      row.door_colour      or '',
                'panelwork_colour': row.panelwork_colour or '',
                'door_style':       row.door_style       or '',
                'door_type': row.door_type or 'Carcass Only',
                'room_type': row.room_type or 'Kitchen',
                'deposit_paid':     float(row.deposit_paid    or 0),
                'total_remaining':  float(row.total_remaining or 0),
                'section_discounts': (json.loads(row.section_discounts) if isinstance(row.section_discounts, str) else row.section_discounts) if getattr(row, 'section_discounts', None) else {},
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
                        'door_type', 'room_type']:
                if field in data:
                    update_fields.append(f"{field} = :{field}")
                    params[field] = data[field]

            if 'section_discounts' in data:
                import json as _json
                update_fields.append("section_discounts = :section_discounts")
                sd = data['section_discounts']
                params['section_discounts'] = _json.dumps(sd) if isinstance(sd, dict) else sd

            if 'vat_rate' in data:
                update_fields.append("vat_rate = :vat_rate")
                params['vat_rate'] = data['vat_rate']

            if 'items' in data:
                session.execute(
                    text('DELETE FROM "StreemLyne_MT"."Invoice_Details" WHERE invoice_id = :id'),
                    {'id': invoice_id}
                )
                total = 0.0
                for item in data['items']:
                    if not item.get('item') and not item.get('description') and not item.get('amount'):
                        continue
                    amt = float(item.get('amount', item.get('line_total', 0)))
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
                            'amt':          amt,
                            'unit_price':   amt / qty if qty else 0,
                            'service_name': item.get('item', ''),
                            'w':            item.get('width'),
                            'h':            item.get('height'),
                            'd':            item.get('depth'),
                            'dp':           item.get('discount_percent', 0),
                            'da':           item.get('discounted_total', amt),
                            'section':      item.get('section', 'Furniture'),
                            'is_sub_item':  bool(item.get('is_sub_item', False)),
                        }
                    )
                    total += amt * qty

                vat_rate   = float(data.get('vat_rate', 20))
                vat_amount = total * (vat_rate / 100)
                total_amt  = total + vat_amount

                update_fields += [
                    "subtotal = :subtotal", "sub_total = :subtotal",
                    "vat_amount = :vat_amount", "vat = :vat_amount",
                    "total_amount = :total_amount",
                ]
                params.update({
                    'subtotal':     total,
                    'vat_amount':   vat_amount,
                    'total_amount': total_amt,
                    'vat_rate':     vat_rate,
                })
                # Ensure vat_rate is in update_fields exactly once
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

        FILL   = (230, 230, 230)
        YELLOW = (255, 255, 180)
        GREEN  = (180, 230, 180)
        lh     = 6

        SECTIONS = ['Furniture', 'Fillers and End Panels', 'Accessories', 'Handles',
                    'Appliances', 'Sink and Tap', 'Worktops', 'Fittings']

        pdf = PDF('P', 'mm', 'A4')
        pdf.doc_title = 'INVOICE'
        pdf.alias_nb_pages()
        pdf.set_auto_page_break(auto=True, margin=20)
        pdf.add_page()
        pdf.set_auto_page_break(auto=False, margin=20)

        # ── Registration + bank details ───────────────────────────────────
        pdf.set_fill_color(*GREEN)
        pdf.set_font('Arial', 'B', 9)
        pdf.cell(0, 5, 'Registered to England No 5246881   |   VAT Reg No.686 8010 72', 1, 1, 'C', 1)
        pdf.ln(1)

        pdf.set_fill_color(*YELLOW)
        pdf.set_font('Arial', '', 9)
        pdf.cell(0, 5,
            'Acc name: Atelier Luxe Interiors LTD  |  Bank: ClearBank  |  Sort Code: 04 06 05  |  Acc No: 31621197',
            1, 1, 'C', 1)
        pdf.ln(1)

        pdf.set_fill_color(*FILL)
        pdf.cell(0, 5, 'Please use your name and/or road name as reference', 1, 1, 'C', 1)
        pdf.ln(4)

        # ── Customer info ─────────────────────────────────────────────────
        cust_name    = row.customer_name    or row.client_company_name or 'N/A'
        cust_address = row.customer_address or row.client_address      or 'N/A'
        cust_phone   = row.customer_phone   or row.client_phone        or 'N/A'
        inv_date     = row.invoice_date.strftime('%d/%m/%Y') if row.invoice_date else 'N/A'
        due_date     = row.due_date.strftime('%d/%m/%Y')     if row.due_date     else 'N/A'

        customer_fields = [
            ('DATE:',        inv_date),
            ('DUE DATE:',    due_date),
            ('NAME:',        cust_name),
            ('ADDRESS:',     cust_address),
            ('TEL:',         cust_phone),
        ]
        for field, label in [
            ('room_name',        'ROOM NAME:'),
            ('carcass_colour',   'CARCASS COLOUR:'),
            ('door_colour',      'DOOR COLOUR:'),
            ('panelwork_colour', 'PANELWORK COLOUR:'),
            ('door_style',       'DOOR STYLE:'),
        ]:
            v = getattr(row, field, None)
            if v:
                customer_fields.append((label, v))

        for label, value in customer_fields:
            pdf.set_font('Arial', 'B', 9)
            pdf.set_fill_color(*FILL)
            pdf.cell(45, lh, label, 1, 0, 'L', 1)
            pdf.set_font('Arial', '', 9)
            pdf.cell(145, lh, value, 1, 1, 'L')

        pdf.ln(5)

        # ── Items by section ──────────────────────────────────────────────
        headers = ['ITEM', 'DESCRIPTION', 'COLOUR', 'QTY']
        widths  = [35, 118, 22, 15]

        valid_items = [
            i for i in items
            if (i.item_name or i.service_name or '').strip() or
               (i.description or '').strip() or
               (i.amount and float(i.amount) > 0)
        ]

        ROW_H       = 8
        PAGE_BOTTOM = pdf.h - 35
        subtotal_after_section_discounts = 0.0

        def draw_row(name, desc, color, qty, amount, indent=False, discounted_amount=None, discount_pct=0):
            row_h = 8
            x0, y0 = pdf.get_x(), pdf.get_y()
            clean_name = (name or '').encode('latin-1', errors='ignore').decode('latin-1')
            display_name = (' - ' + clean_name) if indent else clean_name
            pdf.cell(widths[0], row_h, display_name[:22], 1, 0, 'L')
            pdf.cell(widths[1], row_h, '', 1, 0, 'L')
            pdf.cell(widths[2], row_h, color or '', 1, 0, 'C')
            pdf.cell(widths[3], row_h, str(int(qty or 1)), 1, 1, 'C')
            pdf.set_xy(x0 + widths[0] + 1, y0 + 1)
            clean_desc = (desc or '').encode('latin-1', errors='ignore').decode('latin-1')
            pdf.cell(widths[1] - 2, row_h - 2,
                     (clean_desc[:100] if len(clean_desc) > 100 else clean_desc), 0, 0, 'L')
            pdf.set_xy(x0, y0 + row_h)
            # Return discounted line total if discount applied
            base = float(amount or 0) * int(qty or 1)
            if discounted_amount is not None:
                return float(discounted_amount)
            if discount_pct and discount_pct > 0:
                return base * (1 - float(discount_pct) / 100)
            return base

        def draw_section_header(section_name):
            pdf.set_font('Arial', 'B', 10)
            pdf.cell(0, 7, section_name, 0, 1, 'L')
            pdf.set_fill_color(*FILL)
            pdf.set_font('Arial', 'B', 9)
            for h, w in zip(headers, widths):
                pdf.cell(w, 8, h, 1, 0, 'C', 1)
            pdf.ln()
            pdf.set_font('Arial', '', 9)

        for section in SECTIONS:
            section_items = [i for i in valid_items
                             if (getattr(i, 'section', None) or 'Furniture') == section]
            if not section_items:
                continue

            header_h = 7 + 8
            if pdf.get_y() + header_h + ROW_H > PAGE_BOTTOM:
                pdf.add_page()

            draw_section_header(section)

            section_subtotal = 0.0
            for item in section_items:
                if pdf.get_y() + ROW_H > PAGE_BOTTOM:
                    pdf.add_page()

                is_sub = bool(getattr(item, 'is_sub_item', False))
                lt = draw_row(
                    item.item_name or getattr(item, 'service_name', '') or '',
                    item.description or '',
                    item.color or '',
                    item.quantity or 1,
                    item.amount or 0,
                    indent=is_sub,
                    discounted_amount=float(item.discounted_amount) if (item.discounted_amount and float(getattr(item, 'discount_percent', 0) or 0) > 0) else None,
                    discount_pct=float(getattr(item, 'discount_percent', 0) or 0),
                )
                section_subtotal += lt

            # ── Section totals with optional section discount ─────────────
            sec_discount_pct = float(section_discounts.get(section, 0) or 0)
            sec_discount_amt = section_subtotal * (sec_discount_pct / 100)
            sec_total = section_subtotal - sec_discount_amt
            subtotal_after_section_discounts += sec_total

            pdf.ln(1)
            sec_tx = 120
            pdf.set_font('Arial', '', 8)
            pdf.set_x(sec_tx)
            pdf.cell(45, 5, f'{section} Subtotal:', 0, 0, 'R')
            pdf.cell(25, 5, f'£{section_subtotal:.2f}', 0, 1, 'R')

            if sec_discount_pct > 0:
                pdf.set_font('Arial', '', 8)
                pdf.set_x(sec_tx)
                pdf.cell(45, 5, 'Section Discount:', 0, 0, 'R')
                pdf.set_text_color(200, 0, 0)
                pdf.cell(25, 5, f'-£{sec_discount_amt:.2f}', 0, 1, 'R')
                pdf.set_text_color(0, 0, 0)

            pdf.set_font('Arial', 'B', 8)
            pdf.set_fill_color(220, 220, 220)
            pdf.set_x(sec_tx)
            pdf.cell(45, 5, f'{section} Total:', 1, 0, 'R', 1)
            pdf.cell(25, 5, f'£{sec_total:.2f}', 1, 1, 'R', 1)
            pdf.ln(4)

        # ── Totals ────────────────────────────────────────────────────────
        pdf.ln(3)
        vat_rate   = float(row.vat_rate or 20)
        vat_amount = subtotal_after_section_discounts * (vat_rate / 100)
        total      = subtotal_after_section_discounts + vat_amount
        deposit    = float(row.deposit_paid or 0)
        remaining  = max(0, float(row.total_remaining or (total - deposit)))
        tx         = 105

        totals_rows = [('SUB TOTAL:', f'£{subtotal_after_section_discounts:.2f}'),
                       (f'VAT ({vat_rate:.0f}%):', f'£{vat_amount:.2f}')]

        for label, value in totals_rows:
            pdf.set_x(tx)
            pdf.set_font('Arial', '', 10)
            pdf.cell(50, lh, label, 0, 0, 'R')
            pdf.set_font('Arial', 'B', 10)
            pdf.cell(35, lh, value, 0, 1, 'R')

        pdf.set_x(tx)
        pdf.set_fill_color(*FILL)
        pdf.set_font('Arial', 'B', 12)
        pdf.cell(50, 8, 'TOTAL:', 'T', 0, 'R', 1)
        pdf.cell(35, 8, f'£{total:.2f}', 'T', 1, 'R', 1)

        if deposit > 0:
            pdf.ln(2)
            pdf.set_x(tx)
            pdf.set_font('Arial', '', 10)
            pdf.cell(50, lh, 'DEPOSIT PAID:', 0, 0, 'R')
            pdf.set_font('Arial', 'B', 10)
            pdf.cell(35, lh, f'£{deposit:.2f}', 0, 1, 'R')

            pdf.set_x(tx)
            pdf.set_font('Arial', 'B', 11)
            pdf.cell(50, 7, 'TOTAL REMAINING:', 0, 0, 'R')
            pdf.cell(35, 7, f'£{remaining:.2f}', 0, 1, 'R')

        pdf.ln(8)

        # ── Payment terms ─────────────────────────────────────────────────
        if pdf.get_y() + 60 > pdf.h - 20:
            pdf.add_page()

        pdf.set_font('Arial', 'B', 9)
        pdf.cell(0, 5, 'Only Bacs or Cash will be accepted on Delivery and Completion', 0, 1, 'L')
        pdf.cell(0, 5, 'NOTE: Payment is due within 30 days of the invoice date.', 0, 1, 'L')
        pdf.ln(4)

        pdf.set_text_color(200, 0, 0)
        pdf.cell(0, 5, 'Please sign here to confirm.', 0, 1, 'L')
        pdf.set_text_color(0, 0, 0)
        pdf.ln(6)

        # ── Signature lines ───────────────────────────────────────────────
        pdf.set_font('Arial', '', 9)
        for label in ['Customer Signature:', 'Customer Name:', 'Date:']:
            pdf.cell(45, 6, label, 0, 0, 'L')
            pdf.cell(145, 6, '', 'B', 1, 'L')
            pdf.ln(2)

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

        count = session.execute(
            text("SELECT COUNT(*) as c FROM \"StreemLyne_MT\".\"Invoice_Master\" WHERE tenant_id = :t AND status LIKE 'Proforma%'"),
            {'t': str(tenant_id)}
        ).fetchone().c
        invoice_number = data.get('invoice_number') or f"PRO-{datetime.utcnow().strftime('%Y%m%d')}-{count + 1:03d}"

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
                 deposit_paid, total_remaining)
                VALUES
                (:tenant_id, :client_id, :project_id, :invoice_number, :invoice_date, :due_date,
                 :status, :notes, :customer_name, :customer_address, :customer_phone, :customer_email,
                 :subtotal, :vat_rate, :vat_amount, :total_amount, :created_by,
                 :subtotal, :vat_amount, :notes, :tax_id,
                 :room_name, :carcass_colour, :door_colour, :panelwork_colour, :door_style,
                 :deposit_paid, :total_remaining)
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
            }
        )

        invoice_id = result.fetchone().invoice_id

        for item in items_data:
            if not item.get('item') and not item.get('description') and not item.get('amount'):
                continue
            amt = float(item.get('amount', item.get('line_total', 0)))
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
                    'color': item.get('color', item.get('colour', '')), 'qty': qty, 'amt': amt,
                    'up': amt / qty if qty else 0, 'w': item.get('width'), 'h': item.get('height'),
                    'd': item.get('depth'), 'dp': item.get('discount_percent', 0),
                    'da': item.get('discounted_total', amt),
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
                'vat_rate': float(row.vat_rate or 20),
                'vat_amount': float(row.vat_amount or row.vat or 0),
                'total': float(row.total_amount or 0),
                'status': row.status, 'notes': row.notes,
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
                          'customer_email', 'status', 'notes', 'invoice_date', 'due_date']:
                if field in data:
                    update_fields.append(f"{field} = :{field}")
                    params[field] = data[field]

            if 'vat_rate' in data:
                update_fields.append("vat_rate = :vat_rate")
                params['vat_rate'] = data['vat_rate']

            if 'items' in data:
                session.execute(
                    text('DELETE FROM "StreemLyne_MT"."Invoice_Details" WHERE invoice_id = :id'),
                    {'id': invoice_id}
                )
                total = 0.0
                for item in data['items']:
                    if not item.get('item') and not item.get('description') and not item.get('amount'):
                        continue
                    amt = float(item.get('amount', item.get('line_total', 0)))
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
                            'color': item.get('color', item.get('colour', '')), 'qty': qty, 'amt': amt,
                            'up': amt / qty if qty else 0, 'w': item.get('width'),
                            'h': item.get('height'), 'd': item.get('depth'),
                            'dp': item.get('discount_percent', 0), 'da': item.get('discounted_total', amt),
                        }
                    )
                    total += amt * qty

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

        FILL=(230,230,230); YELLOW=(255,255,180); GREEN=(180,230,180); lh=6

        pdf = PDF('P', 'mm', 'A4')
        pdf.doc_title = 'PROFORMA INVOICE'
        pdf.alias_nb_pages(); pdf.add_page(); 
        pdf.set_auto_page_break(auto=True, margin=20)

        pdf.set_fill_color(*GREEN); pdf.set_font('Arial','B',9)
        pdf.cell(0,5,'Registered to England No 5246881   |   VAT Reg No.686 8010 72',1,1,'C',1); pdf.ln(1)
        pdf.set_fill_color(*YELLOW); pdf.set_font('Arial','',9)
        pdf.cell(0,5,'Acc name: Atelier Luxe Interiors LTD  |  Bank: ClearBank  |  Sort Code: 04 06 05  |  Acc No: 31621197',1,1,'C',1); pdf.ln(1)
        pdf.set_fill_color(*FILL)
        pdf.cell(0,5,'Please use your name and/or road name as reference',1,1,'C',1); pdf.ln(4)

        for label, value in [
            ('PROFORMA NO:', row.invoice_number or 'N/A'),
            ('DATE:',        row.invoice_date.strftime('%d/%m/%Y') if row.invoice_date else 'N/A'),
            ('VALID UNTIL:', row.due_date.strftime('%d/%m/%Y')     if row.due_date     else 'N/A'),
        ]:
            pdf.set_x(110); pdf.set_fill_color(*FILL); pdf.set_font('Arial','B',10)
            pdf.cell(40,lh,label,1,0,'L',1); pdf.set_font('Arial','',10)
            pdf.cell(40,lh,value,1,1,'R',0)
        pdf.ln(5)

        cust_name    = row.customer_name    or row.client_company_name or 'N/A'
        cust_address = row.customer_address or row.client_address      or 'N/A'
        cust_phone   = row.customer_phone   or row.client_phone        or 'N/A'

        for label, value in [('NAME:',cust_name),('ADDRESS:',cust_address),('TEL:',cust_phone)]:
            pdf.set_font('Arial','B',10); pdf.set_fill_color(*FILL)
            pdf.cell(35,lh,label,1,0,'L',1); pdf.set_font('Arial','',10)
            pdf.cell(155,lh,value,1,1,'L',0)
        pdf.ln(5)

        headers=['ITEM','DESCRIPTION','COLOUR','QTY','UNIT PRICE','AMOUNT']
        widths=[22,86,22,12,24,24]
        pdf.set_fill_color(*FILL); pdf.set_font('Arial','B',9)
        for h,w in zip(headers,widths): pdf.cell(w,8,h,1,0,'C',1)
        pdf.ln(); pdf.set_font('Arial','',9); subtotal=0.0

        for item in items:
            name=item.item_name or item.service_name or ''
            desc=item.description or ''
            if not name and not desc and not (item.amount and float(item.amount)>0): continue
            row_h=8; x0,y0=pdf.get_x(),pdf.get_y()
            unit=float(item.unit_price or item.amount or 0)
            lt=float(item.amount or 0)*int(item.quantity or 1)
            pdf.cell(widths[0],row_h,name[:20],1,0,'L')
            pdf.cell(widths[1],row_h,'',1,0,'L')
            pdf.cell(widths[2],row_h,item.color or '',1,0,'C')
            pdf.cell(widths[3],row_h,str(item.quantity or 1),1,0,'C')
            pdf.cell(widths[4],row_h,f'£{unit:.2f}',1,0,'R')
            pdf.cell(widths[5],row_h,f'£{lt:.2f}',1,1,'R')
            pdf.set_xy(x0+widths[0]+1,y0+1); pdf.set_font('Arial','',8)
            pdf.cell(widths[1]-2,row_h-2,desc[:100] if len(desc)>100 else desc,0,0,'L')
            pdf.set_font('Arial','',9); pdf.set_xy(x0,y0+row_h); subtotal+=lt

        pdf.set_auto_page_break(auto=True, margin=40)
        pdf.ln(3)
        vat_rate=float(row.vat_rate or 20)
        vat_amount=float(row.vat_amount or row.vat or subtotal*(vat_rate/100))
        total=float(row.total_amount or subtotal+vat_amount); tx=105

        for label,value in [('SUB TOTAL:',f'£{subtotal:.2f}'),(f'VAT ({vat_rate:.0f}%):',f'£{vat_amount:.2f}')]:
            pdf.set_x(tx); pdf.set_font('Arial','',10); pdf.cell(50,lh,label,0,0,'R')
            pdf.set_font('Arial','B',10); pdf.cell(35,lh,value,0,1,'R')

        pdf.set_x(tx); pdf.set_fill_color(*FILL); pdf.set_font('Arial','B',12)
        pdf.cell(50,8,'TOTAL:','T',0,'R',1); pdf.cell(35,8,f'£{total:.2f}','T',1,'R',1); pdf.ln(8)

        pdf.set_x(10); pdf.set_font('Arial','B',9)
        pdf.cell(0,5,'This is a Proforma Invoice - not a VAT invoice.',0,1,'L')
        pdf.set_x(10); pdf.cell(0,5,'Payment is required before goods are dispatched or work commences.',0,1,'L')
        pdf.ln(4); pdf.set_x(10); pdf.set_text_color(200,0,0)
        pdf.cell(0,5,'Please sign here to confirm.',0,1,'L')
        pdf.set_text_color(0,0,0); pdf.ln(6); pdf.set_font('Arial','',9)

        for label in ['Customer Signature:','Customer Name:','Date:']:
            pdf.set_x(10); pdf.cell(45,6,label,0,0,'L'); pdf.cell(145,6,'','B',1,'L'); pdf.ln(2)

        out=pdf.output(dest='S'); buf=BytesIO(out)
        name=f"Proforma_{row.invoice_number}_{(row.customer_name or 'Customer').replace(' ','_')}.pdf"
        return send_file(buf,mimetype='application/pdf',as_attachment=False,download_name=name)

    except Exception as e:
        current_app.logger.exception(f"Proforma PDF generation failed: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()