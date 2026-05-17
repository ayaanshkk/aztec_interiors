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

@receipt_bp.route('/receipts/download-pdf', methods=['POST'])
def download_receipt_pdf():
    """Generate and download receipt PDF (no auth required — public)"""
    try:
        data = request.get_json(silent=True) or {}

        if not data:
            return jsonify({'error': 'Missing receipt data'}), 400

        pdf = PDF('P', 'mm', 'A4')
        pdf.doc_title = 'Official Receipt'
        pdf.alias_nb_pages()
        pdf.add_page()
        pdf.set_auto_page_break(auto=True, margin=30)

        HEADER_FILL = (230, 230, 230)
        TOTAL_FILL  = (200, 200, 200)
        col_width   = 190 / 2
        line_height = 7

        # ── Customer details ───────────────────────────────────────────
        pdf.set_fill_color(*HEADER_FILL)
        pdf.set_draw_color(0, 0, 0)
        pdf.set_font('Arial', 'B', 12)
        pdf.cell(col_width, line_height, 'Customer Details', 'T', 0, 'L', 1)
        pdf.cell(col_width, line_height, 'Date',             'T', 1, 'R', 1)

        pdf.set_font('Arial', 'B', 10)
        pdf.cell(30, line_height, 'Name:', 0, 0, 'L')
        pdf.set_font('Arial', '', 10)
        pdf.cell(col_width - 30, line_height, data.get('customerName', 'N/A'), 0, 0, 'L')
        pdf.cell(col_width, line_height,
                 data.get('receiptDate', datetime.now().strftime('%d/%m/%Y')), 0, 1, 'R')

        pdf.set_font('Arial', 'B', 10)
        pdf.cell(30, line_height, 'Address:', 0, 0, 'L')
        pdf.set_font('Arial', '', 10)
        pdf.multi_cell(col_width - 30, line_height, data.get('customerAddress', 'N/A'), 0, 'L', 0)

        y_after = pdf.get_y()
        pdf.set_font('Arial', 'B', 10)
        pdf.set_xy(10, y_after)
        pdf.cell(30, line_height, 'Phone:', 'B', 0, 'L')
        pdf.set_font('Arial', '', 10)
        pdf.cell(col_width - 30, line_height, data.get('customerPhone', 'N/A'), 'B', 1, 'L')
        pdf.ln(5)

        # ── Payment confirmation sentence ──────────────────────────────
        pdf.set_font('Arial', '', 11)
        pdf.multi_cell(
            0, 6,
            f"Confirmation of payment received by BACS for "
            f"{data.get('paymentDescription', 'your Kitchen/Bedroom Cabinetry')}",
            0, 'L'
        )
        pdf.ln(5)

        # ── Paid amount ────────────────────────────────────────────────
        pdf.set_fill_color(*TOTAL_FILL)
        pdf.set_font('Arial', 'B', 14)
        pdf.cell(col_width, 10, 'Paid:', 1, 0, 'L', 1)
        pdf.set_font('Arial', 'B', 16)
        pdf.cell(col_width, 10, f"£{data.get('paidAmount', 0):,.2f}", 1, 1, 'R', 1)
        pdf.ln(5)

        # ── Totals summary ─────────────────────────────────────────────
        pdf.set_font('Arial', 'B', 11)
        pdf.cell(col_width, 7, 'Paid to date:', 'T', 0, 'L')
        pdf.set_font('Arial', '', 11)
        pdf.cell(col_width, 7, f"£{data.get('totalPaidToDate', 0):,.2f}", 'T', 1, 'R')

        pdf.set_font('Arial', 'B', 12)
        pdf.cell(col_width, 8, 'Balance to Pay:', 'T', 0, 'L')
        pdf.cell(col_width, 8, f"£{data.get('balanceToPay', 0):,.2f}", 'T', 1, 'R')
        pdf.ln(10)

        # ── Signature ──────────────────────────────────────────────────
        pdf.set_font('Arial', '', 11)
        pdf.cell(0, 5, 'Many Thanks', 0, 1, 'L')
        pdf.ln(5)
        pdf.set_font('Arial', 'I', 12)
        pdf.cell(0, 5, 'Shahida Macci', 0, 1, 'L')

        pdf_output = pdf.output(dest='S')
        pdf_file   = BytesIO(pdf_output)

        customer_name = data.get('customerName', 'Customer').replace(' ', '_')
        date_str      = data.get('receiptDate', datetime.now().strftime('%Y-%m-%d'))
        filename      = f"Receipt_{data.get('receiptType', 'Payment').title()}_{customer_name}_{date_str}.pdf"

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