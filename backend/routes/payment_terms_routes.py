from flask import Blueprint, request, jsonify, current_app, send_file
from sqlalchemy import text
from datetime import datetime
from io import BytesIO
import json

from ..db import SessionLocal
from .auth_helpers import token_required, require_tenant
from .pdf_helpers import PDF

payment_terms_bp = Blueprint("payment_terms", __name__)


# ============================================================================
# HELPERS
# ============================================================================

def generate_pt_number(session, tenant_id):
    count = session.execute(
        text('SELECT COUNT(*) as c FROM "StreemLyne_MT"."Payment_Terms_Master" WHERE tenant_id = :t'),
        {'t': str(tenant_id)}
    ).fetchone().c
    return f"PT-{datetime.utcnow().strftime('%Y%m%d')}-{count + 1:03d}"


# ============================================================================
# LIST / CREATE
# ============================================================================

@payment_terms_bp.route('/payment-terms', methods=['GET'])
@token_required
@require_tenant
def get_payment_terms(tenant_id, employee_id):
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
                SELECT pt.*, c.client_company_name
                FROM "StreemLyne_MT"."Payment_Terms_Master" pt
                INNER JOIN "StreemLyne_MT"."Client_Master" c ON pt.client_id = c.client_id
                WHERE pt.tenant_id = :t AND pt.client_id = :c
                ORDER BY pt.created_at DESC
            """),
            {'t': str(tenant_id), 'c': int(client_id)}
        ).fetchall()

        return jsonify([{
            'id':              r.pt_id,
            'pt_id':           r.pt_id,
            'pt_number':       r.pt_number,
            'client_id':       r.client_id,
            'customer_id':     r.client_id,
            'customer_name':   r.customer_name or r.client_company_name,
            'total_amount_due': float(r.total_amount_due or 0),
            'total_amount_paid': float(r.total_amount_paid or 0),
            'status':          r.status,
            'created_at':      r.created_at.isoformat() if r.created_at else None,
        } for r in rows]), 200

    except Exception as e:
        current_app.logger.exception(f"Error fetching payment terms: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@payment_terms_bp.route('/payment-terms', methods=['POST'])
@token_required
@require_tenant
def create_payment_terms(tenant_id, employee_id):
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

        pt_number = data.get('pt_number') or generate_pt_number(session, tenant_id)
        rows_data = data.get('payment_rows', [])

        total_due  = sum(float(r.get('amount_due',  0) or 0) for r in rows_data)
        total_paid = sum(float(r.get('amount_paid', 0) or 0) for r in rows_data)

        result = session.execute(
            text("""
                INSERT INTO "StreemLyne_MT"."Payment_Terms_Master"
                (tenant_id, client_id, pt_number, date,
                 customer_name, customer_address, customer_phone,
                 payment_rows, total_amount_due, total_amount_paid,
                 notes, status, created_by_employee_id)
                VALUES
                (:tenant_id, :client_id, :pt_number, :date,
                 :customer_name, :customer_address, :customer_phone,
                 :payment_rows, :total_due, :total_paid,
                 :notes, 'Active', :created_by)
                RETURNING pt_id
            """),
            {
                'tenant_id':        str(tenant_id),
                'client_id':        int(client_id),
                'pt_number':        pt_number,
                'date':             data.get('date') or datetime.utcnow().strftime('%Y-%m-%d'),
                'customer_name':    data.get('customer_name', ''),
                'customer_address': data.get('customer_address', ''),
                'customer_phone':   data.get('customer_phone', ''),
                'payment_rows':     json.dumps(rows_data),
                'total_due':        total_due,
                'total_paid':       total_paid,
                'notes':            data.get('notes', ''),
                'created_by':       employee_id,
            }
        )
        pt_id = result.fetchone().pt_id
        session.commit()

        return jsonify({
            'pt_id':     pt_id,
            'pt_number': pt_number,
            'message':   'Payment terms created successfully'
        }), 201

    except Exception as e:
        session.rollback()
        current_app.logger.exception(f"Error creating payment terms: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


# ============================================================================
# SINGLE — GET / PUT / DELETE
# ============================================================================

@payment_terms_bp.route('/payment-terms/<int:pt_id>', methods=['GET', 'PUT', 'DELETE'])
@token_required
@require_tenant
def handle_payment_terms(pt_id, tenant_id, employee_id):
    session = SessionLocal()
    try:
        if request.method == 'GET':
            row = session.execute(
                text("""
                    SELECT pt.*, c.client_company_name, c.address AS client_address, c.client_phone
                    FROM "StreemLyne_MT"."Payment_Terms_Master" pt
                    INNER JOIN "StreemLyne_MT"."Client_Master" c ON pt.client_id = c.client_id
                    WHERE pt.pt_id = :id AND pt.tenant_id = :t
                """),
                {'id': pt_id, 't': str(tenant_id)}
            ).fetchone()

            if not row:
                return jsonify({'error': 'Payment terms not found'}), 404

            rows_data = row.payment_rows
            if isinstance(rows_data, str):
                rows_data = json.loads(rows_data)

            return jsonify({
                'id':               row.pt_id,
                'pt_id':            row.pt_id,
                'pt_number':        row.pt_number,
                'customer_id':      str(row.client_id),
                'customer_name':    row.customer_name    or row.client_company_name,
                'customer_address': row.customer_address or row.client_address,
                'customer_phone':   row.customer_phone   or row.client_phone,
                'date':             row.date.isoformat()     if row.date       else None,
                'payment_rows':     rows_data or [],
                'total_amount_due':  float(row.total_amount_due  or 0),
                'total_amount_paid': float(row.total_amount_paid or 0),
                'notes':            row.notes,
                'status':           row.status,
                'created_at':       row.created_at.isoformat() if row.created_at else None,
            }), 200

        elif request.method == 'PUT':
            data = request.get_json(silent=True) or {}
            update_fields = []
            params = {'id': pt_id, 't': str(tenant_id)}

            for field in ['customer_name', 'customer_address', 'customer_phone', 'date', 'notes', 'status']:
                if field in data:
                    update_fields.append(f"{field} = :{field}")
                    params[field] = data[field]

            if 'payment_rows' in data:
                rows_data  = data['payment_rows']
                total_due  = sum(float(r.get('amount_due',  0) or 0) for r in rows_data)
                total_paid = sum(float(r.get('amount_paid', 0) or 0) for r in rows_data)
                update_fields += [
                    "payment_rows = :payment_rows",
                    "total_amount_due = :total_due",
                    "total_amount_paid = :total_paid",
                ]
                params.update({
                    'payment_rows': json.dumps(rows_data),
                    'total_due':    total_due,
                    'total_paid':   total_paid,
                })

            if not update_fields:
                return jsonify({'error': 'No fields to update'}), 400

            update_fields.append("updated_at = CURRENT_TIMESTAMP")
            session.execute(
                text(f"""
                    UPDATE "StreemLyne_MT"."Payment_Terms_Master"
                    SET {', '.join(update_fields)}
                    WHERE pt_id = :id AND tenant_id = :t
                """),
                params
            )
            session.commit()
            return jsonify({'success': True, 'message': 'Payment terms updated'}), 200

        elif request.method == 'DELETE':
            session.execute(
                text('DELETE FROM "StreemLyne_MT"."Payment_Terms_Master" WHERE pt_id = :id AND tenant_id = :t'),
                {'id': pt_id, 't': str(tenant_id)}
            )
            session.commit()
            return jsonify({'success': True, 'message': 'Payment terms deleted'}), 200

    except Exception as e:
        session.rollback()
        current_app.logger.exception(f"Error handling payment terms {pt_id}: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


# ============================================================================
# PDF — no auth so window.open() works
# ============================================================================

@payment_terms_bp.route('/payment-terms/<int:pt_id>/pdf', methods=['GET'])
def download_payment_terms_pdf(pt_id):
    session = SessionLocal()
    try:
        row = session.execute(
            text("""
                SELECT pt.*, c.client_company_name, c.address AS client_address, c.client_phone
                FROM "StreemLyne_MT"."Payment_Terms_Master" pt
                INNER JOIN "StreemLyne_MT"."Client_Master" c ON pt.client_id = c.client_id
                WHERE pt.pt_id = :id
            """),
            {'id': pt_id}
        ).fetchone()

        if not row:
            return jsonify({'error': 'Payment terms not found'}), 404

        rows_data = row.payment_rows
        if isinstance(rows_data, str):
            rows_data = json.loads(rows_data)

        FILL   = (230, 230, 230)
        YELLOW = (255, 255, 180)
        GREEN  = (180, 230, 180)
        RED    = (220, 50,  50)
        lh     = 7

        pdf = PDF('P', 'mm', 'A4')
        pdf.doc_title = 'PAYMENT TERMS'
        pdf.alias_nb_pages()
        pdf.add_page()
        pdf.set_auto_page_break(auto=True, margin=20)

        # ── Coloured info bars ─────────────────────────────────────────────
        pdf.set_fill_color(*GREEN)
        pdf.set_font('Arial', 'B', 9)
        pdf.cell(0, 5, 'Bacs details:', 1, 1, 'L', 1)
        pdf.set_fill_color(*YELLOW)
        pdf.set_font('Arial', '', 9)
        pdf.cell(0, 5, 'Please use your name and/or road name as reference:', 1, 1, 'L', 1)
        pdf.ln(1)

        pdf.set_font('Arial', '', 9)
        pdf.cell(0, 5, 'Acc name : Atelier Luxe Interiors LTD', 0, 1, 'L')
        pdf.cell(0, 5, 'Bank : Tide', 0, 1, 'L')
        pdf.cell(0, 5, 'Sort Code: 04 06 05', 0, 1, 'L')
        pdf.cell(0, 5, 'Acc No: 31621197', 0, 1, 'L')
        pdf.ln(5)

        # ── Customer info table ────────────────────────────────────────────
        cust_name    = row.customer_name    or row.client_company_name or 'N/A'
        cust_address = row.customer_address or row.client_address      or 'N/A'
        cust_phone   = row.customer_phone   or row.client_phone        or 'N/A'

        for label, value in [('NAME', cust_name), ('ADDRESS', cust_address), ('PHONE NO.', cust_phone)]:
            pdf.set_font('Arial', 'B', 10)
            pdf.set_fill_color(*FILL)
            pdf.cell(35, lh, label, 1, 0, 'L', 1)
            pdf.set_font('Arial', '', 10)
            pdf.cell(155, lh, value, 1, 1, 'L', 0)

        pdf.ln(8)

        # ── Payments table ────────────────────────────────────────────────
        col_labels = ['', 'AMOUNT DUE', 'AMOUNT PAID', 'DATE', 'SIGNED']
        col_widths = [52, 38, 38, 32, 30]  # total = 190

        # Header row
        pdf.set_fill_color(*FILL)
        pdf.set_font('Arial', 'B', 9)
        for i, (label, width) in enumerate(zip(col_labels, col_widths)):
            # "AMOUNT PAID" header in red like the image
            if label == 'AMOUNT PAID':
                pdf.set_text_color(*RED)
            else:
                pdf.set_text_color(0, 0, 0)
            pdf.cell(width, 8, label, 1, 0, 'C', 1)
        pdf.set_text_color(0, 0, 0)
        pdf.ln()

        # Payment rows
        pdf.set_font('Arial', '', 9)
        default_rows = [
            {'label': 'Deposit',                     'amount_due': '', 'amount_paid': '', 'date': '', 'signed': ''},
            {'label': '6 wks Prior to\ncommencement of\nworks', 'amount_due': '', 'amount_paid': '', 'date': '', 'signed': ''},
            {'label': 'On Completion',               'amount_due': '', 'amount_paid': '', 'date': '', 'signed': ''},
        ]

        # Merge saved data into default rows
        for i, default in enumerate(default_rows):
            if i < len(rows_data):
                saved = rows_data[i]
                default['amount_due']  = f"£{float(saved.get('amount_due',  0) or 0):.2f}" if saved.get('amount_due')  else ''
                default['amount_paid'] = f"£{float(saved.get('amount_paid', 0) or 0):.2f}" if saved.get('amount_paid') else ''
                default['date']        = saved.get('date', '')
                default['signed']      = saved.get('signed', '')

        for r in default_rows:
            label_lines = r['label'].split('\n')
            row_h = max(8, len(label_lines) * 6)

            x0, y0 = pdf.get_x(), pdf.get_y()

            # Label cell (left column)
            pdf.cell(col_widths[0], row_h, '', 1, 0, 'L')
            pdf.cell(col_widths[1], row_h, r['amount_due'],  1, 0, 'C')
            # Amount paid in red
            pdf.set_text_color(*RED)
            pdf.cell(col_widths[2], row_h, r['amount_paid'], 1, 0, 'C')
            pdf.set_text_color(0, 0, 0)
            pdf.cell(col_widths[3], row_h, r['date'],        1, 0, 'C')
            pdf.cell(col_widths[4], row_h, r['signed'],      1, 1, 'C')

            # Write label text inside first cell
            pdf.set_font('Arial', '', 9)
            for line_idx, line in enumerate(label_lines):
                pdf.set_xy(x0 + 2, y0 + 1 + line_idx * 6)
                pdf.cell(col_widths[0] - 4, 6, line, 0, 0, 'L')
            pdf.set_xy(x0, y0 + row_h)

        # Totals row
        total_due  = float(row.total_amount_due  or 0)
        total_paid = float(row.total_amount_paid or 0)

        pdf.set_font('Arial', 'B', 10)
        pdf.set_fill_color(*FILL)
        pdf.cell(col_widths[0], 8, 'TOTAL', 1, 0, 'L', 1)
        pdf.cell(col_widths[1], 8, f"£{total_due:.2f}",  1, 0, 'C', 1)
        pdf.set_text_color(*RED)
        pdf.cell(col_widths[2], 8, f"£{total_paid:.2f}", 1, 0, 'C', 1)
        pdf.set_text_color(0, 0, 0)
        pdf.cell(col_widths[3], 8, '', 1, 0, 'C', 1)
        pdf.cell(col_widths[4], 8, '', 1, 1, 'C', 1)

        pdf.ln(6)

        # ── Footer text ────────────────────────────────────────────────────
        pdf.set_x(10)
        pdf.set_font('Arial', 'B', 9)
        pdf.cell(0, 5, 'Only Bacs or Cash will be accepted on Delivery and Completion', 0, 1, 'L')
        pdf.ln(3)

        pdf.set_x(10)
        pdf.set_text_color(*RED)
        pdf.set_font('Arial', 'B', 9)
        pdf.cell(0, 5, 'We can not confirm or guarantee a fitting date, only give a week commencing', 0, 1, 'L')
        pdf.set_x(10)
        pdf.cell(0, 5, 'date once the deposit has been paid.', 0, 1, 'L')
        pdf.set_text_color(0, 0, 0)
        pdf.ln(6)

        pdf.set_x(10)
        pdf.set_text_color(*RED)
        pdf.set_font('Arial', 'B', 10)
        pdf.cell(0, 6, 'Please sign here to confirm.', 0, 1, 'L')
        pdf.set_text_color(0, 0, 0)
        pdf.ln(6)

        pdf.set_font('Arial', '', 9)
        pdf.set_x(10)
        pdf.cell(45, 6, 'Customer Signature:', 0, 0, 'L')
        pdf.cell(145, 6, '', 'B', 1, 'L')
        pdf.ln(4)
        pdf.set_x(10)
        pdf.cell(45, 6, 'Date:', 0, 0, 'L')
        pdf.cell(80, 6, '', 'B', 1, 'L')

        out  = pdf.output(dest='S')
        if isinstance(out, str):
            out = out.encode('latin-1')
        buf  = BytesIO(bytes(out))
        name = f"PaymentTerms_{row.pt_number}_{(row.customer_name or 'Customer').replace(' ', '_')}.pdf"
        return send_file(buf, mimetype='application/pdf', as_attachment=False, download_name=name)

    except Exception as e:
        current_app.logger.exception(f"Payment terms PDF failed: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()