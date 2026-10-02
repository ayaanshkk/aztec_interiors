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
    result = session.execute(
        text("""
            SELECT COALESCE(MAX(
                CAST(NULLIF(REGEXP_REPLACE(pt_number, '^PT-(\\d+)$', '\\1'), pt_number) AS INTEGER)
            ), 0) as max_seq
            FROM "StreemLyne_MT"."Payment_Terms_Master"
            WHERE tenant_id = :t
        """),
        {'t': str(tenant_id)}
    ).fetchone()
    return f"PT-{result.max_seq + 1}"


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

            for field in ['customer_name', 'customer_address', 'customer_phone', 'date', 'notes', 'status', 'pt_number']:
                if field in data and data[field] is not None and data[field] != '':
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

        pdf = PDF('P', 'mm', 'A4')
        pdf.doc_title = 'Payment Terms'
        pdf.alias_nb_pages()
        pdf.add_page()
        pdf.set_auto_page_break(auto=True, margin=22)

        # ── Customer section (2-column) ────────────────────────────────────
        cust_name    = row.customer_name    or row.client_company_name or 'N/A'
        cust_address = row.customer_address or row.client_address      or 'N/A'
        cust_phone   = row.customer_phone   or row.client_phone        or ''
        pt_date      = row.date.strftime('%d/%m/%Y') if row.date else 'N/A'

        left_rows  = [cust_name, cust_address]
        if cust_phone:
            left_rows.append(cust_phone)
        right_rows = [('PT No', row.pt_number or 'N/A'), ('Date', pt_date)]
        pdf.draw_two_col_customer('Bill To', left_rows, 'Document Details', right_rows)

        # ── BACS note ─────────────────────────────────────────────────────
        pdf.set_font('Arial', '', 7.5)
        pdf.set_text_color(100, 100, 100)
        pdf.cell(0, 4, 'BACS: Atelier Luxe Interiors LTD  \xb7  ClearBank  \xb7  Sort: 04-06-05  \xb7  Acc: 31621197  \xb7  Ref: your name / road', 0, 1, 'L')
        pdf.set_text_color(0, 0, 0)
        pdf.ln(6)

        # ── Payments table ────────────────────────────────────────────────
        col_labels = ['', 'AMOUNT DUE', 'AMOUNT PAID', 'DATE', 'SIGNED']
        col_widths = [52, 38, 38, 32, 30]

        # Header
        pdf.draw_table_header(col_labels, col_widths)
        pdf.ln(2)

        # Data rows
        default_rows = [
            {'label': 'Deposit',                                          'amount_due': '', 'amount_paid': '', 'date': '', 'signed': ''},
            {'label': '6 wks Prior to\ncommencement of works',            'amount_due': '', 'amount_paid': '', 'date': '', 'signed': ''},
            {'label': 'On Completion',                                    'amount_due': '', 'amount_paid': '', 'date': '', 'signed': ''},
        ]

        for i, default in enumerate(default_rows):
            if i < len(rows_data):
                saved = rows_data[i]
                default['amount_due']  = f"\xa3{float(saved.get('amount_due',  0) or 0):.2f}" if saved.get('amount_due')  else ''
                default['amount_paid'] = f"\xa3{float(saved.get('amount_paid', 0) or 0):.2f}" if saved.get('amount_paid') else ''
                default['date']        = saved.get('date', '')
                default['signed']      = saved.get('signed', '')

        for r in default_rows:
            label_lines = r['label'].split('\n')
            row_h = max(8, len(label_lines) * 6)
            x0, y0 = pdf.get_x(), pdf.get_y()
            pdf.set_font('Arial', '', 9)
            pdf.set_text_color(30, 30, 30)
            pdf.cell(col_widths[0], row_h, '', 0, 0, 'L')
            pdf.cell(col_widths[1], row_h, r['amount_due'],  0, 0, 'C')
            pdf.set_text_color(160, 0, 0)
            pdf.cell(col_widths[2], row_h, r['amount_paid'], 0, 0, 'C')
            pdf.set_text_color(30, 30, 30)
            pdf.cell(col_widths[3], row_h, r['date'],        0, 0, 'C')
            pdf.cell(col_widths[4], row_h, r['signed'],      0, 1, 'C')
            for line_idx, line in enumerate(label_lines):
                pdf.set_xy(x0 + 2, y0 + 1 + line_idx * 6)
                pdf.cell(col_widths[0] - 4, 6, line, 0, 0, 'L')
            pdf.set_xy(x0, y0 + row_h)
            pdf.set_draw_color(220, 220, 220)
            pdf.set_line_width(0.2)
            pdf.line(x0, pdf.get_y(), x0 + sum(col_widths), pdf.get_y())

        # Totals row (thick rule then row)
        total_due  = float(row.total_amount_due  or 0)
        total_paid = float(row.total_amount_paid or 0)

        pdf.set_fill_color(23, 23, 23)
        pdf.set_text_color(255, 255, 255)
        pdf.set_font('Arial', 'B', 9)
        pdf.cell(col_widths[0], 7, 'TOTAL', 0, 0, 'L', fill=True)
        pdf.cell(col_widths[1], 7, f'\xa3{total_due:.2f}',  0, 0, 'C', fill=True)
        pdf.cell(col_widths[2], 7, f'\xa3{total_paid:.2f}', 0, 0, 'C', fill=True)
        pdf.cell(col_widths[3], 7, '', 0, 0, 'C', fill=True)
        pdf.cell(col_widths[4], 7, '', 0, 1, 'C', fill=True)
        pdf.set_fill_color(255, 255, 255)
        pdf.set_text_color(0, 0, 0)

        pdf.ln(8)

        # ── Footer text ────────────────────────────────────────────────────
        pdf.set_font('Arial', '', 8.5)
        pdf.set_text_color(80, 80, 80)
        pdf.cell(0, 5, 'Only BACS or Cash will be accepted on Delivery and Completion.', 0, 1, 'L')
        pdf.cell(0, 5, 'We cannot confirm or guarantee a fitting date; only give a week commencing date once the deposit has been paid.', 0, 1, 'L')
        pdf.set_text_color(0, 0, 0)
        pdf.ln(6)

        pdf.draw_signature_lines(['Customer Signature', 'Date'])

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