from flask import Blueprint, request, jsonify, current_app, send_file
from sqlalchemy import text
import json
from datetime import datetime
from io import BytesIO

from ..db import SessionLocal
from .auth_helpers import token_required, require_tenant
from .pdf_helpers import PDF  # shared PDF class

receipt_bp = Blueprint("receipt", __name__)


# ==========================================
# RECEIPT ROUTES
# ==========================================

@receipt_bp.route('/receipts', methods=['GET'])
@token_required
@require_tenant
def get_receipts(tenant_id, employee_id):
    """Fetch all receipt form submissions for a customer"""
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
                SELECT *
                FROM "StreemLyne_MT"."Customer_Form_Submissions"
                WHERE tenant_id = :tenant_id
                  AND client_id = :client_id
                  AND form_type LIKE 'receipt_%'
                ORDER BY submitted_at DESC
            """),
            {'tenant_id': str(tenant_id), 'client_id': int(client_id)}
        ).fetchall()

        result = []
        for row in rows:
            try:
                fd = json.loads(row.form_data) if isinstance(row.form_data, str) else (row.form_data or {})
            except Exception:
                fd = {}

            receipt_type = (fd.get('receiptType') or fd.get('receipt_type') or row.form_type or 'receipt').lower()
            type_key     = 'deposit' if 'deposit' in receipt_type else 'final' if 'final' in receipt_type else 'receipt'
            type_label   = 'Deposit Receipt' if type_key == 'deposit' else 'Final Receipt' if type_key == 'final' else 'Receipt'

            result.append({
                'id':                 row.form_submission_id,
                'form_submission_id': row.form_submission_id,
                'receipt_type':       type_key,
                'title':              type_label,
                'customer_name':      fd.get('customerName') or fd.get('customer_name', ''),
                'paid_amount':        float(fd.get('paidAmount')      or fd.get('paid_amount')      or 0),
                'total_paid_to_date': float(fd.get('totalPaidToDate') or fd.get('total_paid_to_date') or 0),
                'balance_to_pay':     float(fd.get('balanceToPay')    or fd.get('balance_to_pay')    or 0),
                'receipt_date':       fd.get('receiptDate') or fd.get('receipt_date'),
                'amount_paid':        float(fd.get('paidAmount')   or fd.get('paid_amount')   or 0),
                'balance':            float(fd.get('balanceToPay') or fd.get('balance_to_pay') or 0),
                'created_at':         row.submitted_at.isoformat() if row.submitted_at else None,
                'project_id':         row.project_id,
                'form_data':          fd,
            })

        return jsonify(result), 200

    except Exception as e:
        current_app.logger.exception(f"Error fetching receipts: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


def download_receipt_pdf():
    """Generate and download receipt PDF"""
    try:
        data = request.get_json(silent=True) or {}

        if not data:
            return jsonify({'error': 'Missing receipt data'}), 400

        FILL   = (230, 230, 230)
        DARK   = (50, 50, 50)
        RED    = (200, 50, 50)
        lh     = 6

        pdf = PDF('P', 'mm', 'A4')
        receipt_type = data.get('receiptType', 'receipt').lower()
        if receipt_type == 'deposit':
            pdf.doc_title = 'DEPOSIT RECEIPT'
        elif receipt_type == 'final':
            pdf.doc_title = 'FINAL RECEIPT'
        else:
            pdf.doc_title = 'RECEIPT'

        pdf.alias_nb_pages()
        pdf.add_page()
        pdf.set_auto_page_break(auto=True, margin=25)

        cust_name    = data.get('customerName',    'N/A')
        cust_address = data.get('customerAddress', 'N/A')
        cust_phone   = data.get('customerPhone',   'N/A')
        receipt_date = data.get('receiptDate',     datetime.now().strftime('%d/%m/%Y'))
        pay_method   = data.get('paymentMethod',   'BACS')
        pay_desc     = data.get('paymentDescription', 'your Kitchen/Bedroom Cabinetry')
        paid         = float(data.get('paidAmount',      0) or 0)
        paid_to_date = float(data.get('totalPaidToDate', 0) or 0)
        balance      = float(data.get('balanceToPay',    0) or 0)

        # ── Customer + Date table ──────────────────────────────────────
        pdf.set_fill_color(*FILL)
        pdf.set_font('Arial', 'B', 9)
        pdf.cell(0, 5, 'Customer Details', 'T', 1, 'L', 1)

        for label, value in [
            ('Name:',    cust_name),
            ('Address:', cust_address),
            ('Phone:',   cust_phone),
        ]:
            pdf.set_font('Arial', 'B', 10)
            pdf.set_fill_color(*FILL)
            pdf.cell(35, lh, label, 1, 0, 'L', 1)
            pdf.set_font('Arial', '', 10)
            pdf.cell(155, lh, value, 1, 1, 'L', 0)

        # Date row
        pdf.set_font('Arial', 'B', 10)
        pdf.set_fill_color(*FILL)
        pdf.cell(35, lh, 'Date:', 1, 0, 'L', 1)
        pdf.set_font('Arial', '', 10)
        pdf.cell(155, lh, receipt_date, 1, 1, 'L', 0)

        pdf.ln(6)

        # ── Confirmation sentence ──────────────────────────────────────
        pdf.set_font('Arial', '', 10)
        pdf.set_x(10)
        pdf.cell(0, 6,
            f"Confirmation of payment received by {pay_method} for {pay_desc}.",
            0, 1, 'L')
        pdf.ln(5)

        # ── Paid amount (prominent dark box) ──────────────────────────
        pdf.set_fill_color(*DARK)
        pdf.set_text_color(255, 255, 255)
        pdf.set_font('Arial', 'B', 14)
        pdf.cell(95, 12, 'AMOUNT PAID', 1, 0, 'L', 1)
        pdf.set_font('Arial', 'B', 16)
        pdf.cell(95, 12, f"£{paid:,.2f}", 1, 1, 'R', 1)
        pdf.set_text_color(0, 0, 0)
        pdf.ln(4)

        # ── Paid to date ───────────────────────────────────────────────
        pdf.set_fill_color(*FILL)
        pdf.set_font('Arial', 'B', 11)
        pdf.cell(95, 9, 'Total Paid to Date:', 'T', 0, 'L', 1)
        pdf.set_font('Arial', 'B', 11)
        pdf.cell(95, 9, f"£{paid_to_date:,.2f}", 'T', 1, 'R', 1)

        # ── Balance to pay (red) ───────────────────────────────────────
        pdf.set_text_color(*RED)
        pdf.set_font('Arial', 'B', 12)
        pdf.cell(95, 10, 'Balance to Pay:', 'T', 0, 'L')
        pdf.cell(95, 10, f"£{balance:,.2f}", 'T', 1, 'R')
        pdf.set_text_color(0, 0, 0)

        pdf.ln(10)

        # ── Signature ──────────────────────────────────────────────────
        pdf.set_font('Arial', '', 11)
        pdf.set_x(10)
        pdf.cell(0, 6, 'Many Thanks,', 0, 1, 'L')
        pdf.ln(3)
        pdf.set_font('Arial', 'BI', 13)
        pdf.set_x(10)
        pdf.cell(0, 6, 'Tanvir Shaikh', 0, 1, 'L')

        pdf_output = pdf.output(dest='S')
        pdf_file   = BytesIO(pdf_output)

        filename = f"Receipt_{receipt_type.title()}_{cust_name.replace(' ', '_')}_{receipt_date.replace('/', '-')}.pdf"

        return send_file(pdf_file, mimetype='application/pdf',
                         as_attachment=True, download_name=filename)

    except Exception as e:
        current_app.logger.exception(f"Receipt PDF generation failed: {e}")
        return jsonify({"error": f"Failed to generate Receipt PDF: {str(e)}"}), 500


@receipt_bp.route('/receipts/save', methods=['POST'])
@token_required
@require_tenant
def save_receipt(tenant_id, employee_id):
    """Save receipt data to Customer_Form_Submissions"""
    session = SessionLocal()
    try:
        data      = request.get_json(silent=True) or {}
        client_id = data.get('customerId') or data.get('clientId')

        if not client_id:
            return jsonify({'error': 'Missing client ID'}), 400

        # Verify client exists
        client = session.execute(
            text("""
                SELECT client_id FROM "StreemLyne_MT"."Client_Master"
                WHERE client_id = :client_id AND tenant_id = :tenant_id
            """),
            {'client_id': int(client_id), 'tenant_id': str(tenant_id)}
        ).fetchone()

        if not client:
            return jsonify({'error': 'Client not found'}), 404

        data['form_type']   = f"receipt_{data.get('receiptType', 'general')}"
        data['is_receipt']  = True

        result = session.execute(
            text("""
                INSERT INTO "StreemLyne_MT"."Customer_Form_Submissions"
                (tenant_id, client_id, form_type, form_name, form_data,
                 token_used, submitted_by, submission_status)
                VALUES (:tenant_id, :client_id, :form_type, :form_name, :form_data,
                        :token, :submitted_by, 'submitted')
                RETURNING form_submission_id
            """),
            {
                'tenant_id':    str(tenant_id),
                'client_id':    int(client_id),
                'form_type':    data['form_type'],
                'form_name':    f"Receipt - {data.get('receiptType', 'Payment')}",
                'form_data':    json.dumps(data),
                'token':        f"RECEIPT-{data.get('receiptType', '').upper()}-{client_id}-{datetime.utcnow().timestamp()}",
                'submitted_by': (
                    request.current_user.username
                    if hasattr(request, 'current_user') and hasattr(request.current_user, 'username')
                    else 'System'
                )
            }
        )

        form_id = result.fetchone().form_submission_id
        session.commit()

        return jsonify({
            "success":            True,
            "message":            f"Receipt ({data.get('receiptType', 'Payment').title()}) saved successfully!",
            "form_submission_id": form_id
        }), 201

    except Exception as e:
        session.rollback()
        current_app.logger.exception(f"Error saving receipt: {e}")
        return jsonify({"error": f"Failed to save receipt: {str(e)}"}), 500
    finally:
        session.close()