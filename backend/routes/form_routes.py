from flask import Blueprint, request, jsonify, current_app, send_file
from sqlalchemy import text
import secrets
import string
import json
from datetime import datetime, timedelta
from io import BytesIO
from fpdf import FPDF

from ..db import SessionLocal
from .auth_helpers import token_required, require_tenant

form_bp = Blueprint("form", __name__)

# In-memory storage for form tokens (for production use Redis/DB)
form_tokens = {}

def generate_secure_token(length=32):
    """Generate a secure random token"""
    alphabet = string.ascii_letters + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(length))


# ==========================================
# PDF GENERATION CLASS
# ==========================================

class PDF(FPDF):
    """Custom PDF class with header and footer"""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.doc_title = ''
    
    def header(self):
        """PDF header with company info"""
        self.set_font('Arial', 'B', 16)
        self.cell(0, 10, 'AZTEC INTERIORS LEICESTER LTD', 0, 1, 'C')
        self.set_font('Arial', '', 10)
        self.cell(0, 5, '20 Victoria Road East, Leicester, LE5 5FD', 0, 1, 'C')
        self.cell(0, 5, 'Tel: 0116 2761866 | Email: aztecinteriors@hotmail.co.uk', 0, 1, 'C')
        self.ln(5)
        
        if self.doc_title:
            self.set_font('Arial', 'B', 14)
            self.cell(0, 8, self.doc_title, 0, 1, 'C')
            self.ln(5)
    
    def footer(self):
        """PDF footer with page numbers"""
        self.set_y(-15)
        self.set_font('Arial', 'I', 8)
        self.cell(0, 10, f'Page {self.page_no()}/{{nb}}', 0, 0, 'C')


# ==========================================
# INVOICE ROUTES
# ==========================================

@form_bp.route('/invoices/download-pdf', methods=['POST'])
@token_required
@require_tenant
def download_invoice_pdf(tenant_id, employee_id):
    """Generate and download invoice PDF"""
    try:
        data = request.get_json(silent=True) or {}
        
        if not data:
            return jsonify({'error': 'Missing invoice data'}), 400

        pdf = PDF('P', 'mm', 'A4')
        pdf.doc_title = 'Invoice'
        pdf.alias_nb_pages()
        pdf.add_page()
        pdf.set_auto_page_break(auto=True, margin=35)
        pdf.set_font('Arial', '', 10)
        
        HEADER_FILL = (230, 230, 230)
        col_width = 190 / 2
        line_height = 6
        
        # Invoice header details
        pdf.set_x(110)
        pdf.set_fill_color(*HEADER_FILL)
        pdf.set_font('Arial', 'B', 10)
        pdf.cell(40, line_height, 'INVOICE NO:', 1, 0, 'L', 1)
        pdf.set_font('Arial', '', 10)
        pdf.cell(40, line_height, data.get('invoiceNumber', 'N/A'), 1, 1, 'R', 0)
        
        pdf.set_x(110)
        pdf.set_font('Arial', 'B', 10)
        pdf.cell(40, line_height, 'DATE:', 1, 0, 'L', 1)
        pdf.set_font('Arial', '', 10)
        pdf.cell(40, line_height, data.get('invoiceDate', datetime.now().strftime('%Y-%m-%d')), 1, 1, 'R', 0)
        
        pdf.set_x(110)
        pdf.set_font('Arial', 'B', 10)
        pdf.cell(40, line_height, 'DUE DATE:', 1, 0, 'L', 1)
        pdf.set_font('Arial', 'B', 10)
        pdf.cell(40, line_height, data.get('dueDate', 'N/A'), 1, 1, 'R', 0)
        pdf.ln(5)
        
        # Customer details
        pdf.set_font('Arial', 'B', 10)
        pdf.cell(col_width, line_height, 'BILL TO:', 'T', 1, 'L', 0)
        pdf.set_font('Arial', 'B', 12)
        pdf.cell(0, line_height, data.get('customerName', 'N/A'), 0, 1, 'L', 0)
        pdf.set_font('Arial', '', 10)
        pdf.multi_cell(col_width, line_height, data.get('customerAddress', 'N/A'), 0, 'L', 0)
        pdf.cell(0, line_height, data.get('customerPhone', 'N/A'), 0, 1, 'L', 0)
        pdf.ln(10)
        
        # Line items
        header = ['QTY', 'DESCRIPTION', 'UNIT PRICE', 'AMOUNT']
        widths = [15, 105, 35, 35]
        pdf.set_fill_color(*HEADER_FILL)
        pdf.set_font('Arial', 'B', 9)
        
        for i, h in enumerate(header):
            align = 'C' if i == 0 else ('R' if i >= 2 else 'L')
            pdf.cell(widths[i], 8, h, 1, 0, align, 1)
        pdf.ln()

        pdf.set_font('Arial', '', 9)
        for item in data.get('items', []):
            description = item.get('description', '')
            amount = item.get('amount', 0)
            x_start = pdf.get_x()
            y_start = pdf.get_y()
            
            pdf.set_xy(x_start + widths[0], y_start)
            pdf.multi_cell(widths[1], 5, description, 0, 'L', False, dry_run=True)
            row_h = pdf.get_y() - y_start
            row_h = max(5, row_h)
            
            pdf.set_xy(x_start, y_start)
            pdf.cell(widths[0], row_h, '1', 1, 0, 'C', 0)
            pdf.multi_cell(widths[1], row_h, description, 1, 'L', 0, False)
            pdf.set_xy(x_start + widths[0] + widths[1], y_start)
            pdf.cell(widths[2], row_h, '', 1, 0, 'R', 0)
            pdf.cell(widths[3], row_h, f"£{amount:,.2f}", 1, 1, 'R', 0)
        
        pdf.ln(5)

        # Totals
        totals_x_start = 105
        pdf.set_font('Arial', '', 10)
        pdf.set_x(totals_x_start)
        pdf.cell(50, line_height, 'Subtotal:', 0, 0, 'R')
        pdf.set_font('Arial', 'B', 10)
        pdf.cell(40, line_height, f"£{data.get('subTotal', 0):,.2f}", 0, 1, 'R')
        
        pdf.set_x(totals_x_start)
        pdf.set_font('Arial', '', 10)
        vat_label = f"VAT ({data.get('vatRate', 0)}%):"
        pdf.cell(50, line_height, vat_label, 0, 0, 'R')
        pdf.set_font('Arial', 'B', 10)
        pdf.cell(40, line_height, f"£{data.get('vatAmount', 0):,.2f}", 0, 1, 'R')
        
        pdf.set_x(totals_x_start)
        pdf.set_fill_color(*HEADER_FILL)
        pdf.set_font('Arial', 'B', 12)
        pdf.cell(50, 8, 'TOTAL DUE:', 'T', 0, 'R', 1)
        pdf.cell(40, 8, f"£{data.get('totalAmount', 0):,.2f}", 'T', 1, 'R', 1)
        pdf.ln(10)
        
        # Bank details
        Y_LIMIT = 297 - 35
        y_safe_start = Y_LIMIT - 30
        if pdf.get_y() > y_safe_start:
            pdf.set_y(y_safe_start)
        pdf.ln(2)
        pdf.set_font('Arial', 'B', 10)
        pdf.set_xy(10, pdf.get_y())
        pdf.multi_cell(col_width, 5, 'Payment by Bank Transfer:', 0, 'L')
        pdf.set_font('Arial', '', 10)
        pdf.set_xy(10, pdf.get_y())
        pdf.multi_cell(col_width, 5, 'Acc Name: Aztec Interiors Leicester LTD | Bank: HSBC\nSort Code: 40-28-06 | Acc No: 43820343', 0, 'L')
        pdf.set_font('Arial', 'I', 9)
        pdf.set_xy(10, pdf.get_y())
        pdf.multi_cell(0, 5, 'Please use your name and/or road name as reference.', 0, 'L')

        pdf_output = pdf.output(dest='S')
        pdf_file = BytesIO(pdf_output)
        customer_name = data.get('customerName', 'Customer').replace(' ', '_')
        filename = f"Invoice_{data.get('invoiceNumber', '0000')}_{customer_name}.pdf"
        
        return send_file(pdf_file, mimetype='application/pdf', as_attachment=True, download_name=filename)

    except Exception as e:
        current_app.logger.exception(f"Invoice PDF generation failed: {e}")
        return jsonify({"error": f"Failed to generate Invoice PDF: {str(e)}"}), 500


@form_bp.route('/invoices/save', methods=['POST'])
@token_required
@require_tenant
def save_invoice(tenant_id, employee_id):
    """Save invoice to Invoices_Master table"""
    session = SessionLocal()
    try:
        data = request.get_json(silent=True) or {}
        client_id = data.get('customerId') or data.get('clientId')
        
        if not client_id:
            return jsonify({'error': 'Missing client ID'}), 400
        
        # Verify client exists
        client_query = text("""
            SELECT client_id FROM "StreemLyne_MT"."Client_Master"
            WHERE client_id = :client_id AND tenant_id = :tenant_id
        """)
        client = session.execute(client_query, {
            'client_id': int(client_id),
            'tenant_id': str(tenant_id)
        }).fetchone()
        
        if not client:
            return jsonify({'error': 'Client not found'}), 404
        
        # Insert into Invoices_Master
        insert_query = text("""
            INSERT INTO "StreemLyne_MT"."Invoices_Master"
            (tenant_id, client_id, invoice_number, invoice_date, due_date,
             subtotal, vat_rate, vat_amount, total_amount,
             items, notes, created_by_employee_id)
            VALUES (:tenant_id, :client_id, :invoice_number, :invoice_date, :due_date,
                    :subtotal, :vat_rate, :vat_amount, :total_amount,
                    :items, :notes, :created_by)
            RETURNING invoice_id
        """)
        
        result = session.execute(insert_query, {
            'tenant_id': str(tenant_id),
            'client_id': int(client_id),
            'invoice_number': data.get('invoiceNumber'),
            'invoice_date': data.get('invoiceDate'),
            'due_date': data.get('dueDate'),
            'subtotal': data.get('subTotal', 0),
            'vat_rate': data.get('vatRate', 0),
            'vat_amount': data.get('vatAmount', 0),
            'total_amount': data.get('totalAmount', 0),
            'items': json.dumps(data.get('items', [])),
            'notes': data.get('notes', ''),
            'created_by': employee_id
        })
        
        invoice_id = result.fetchone().invoice_id
        session.commit()
        
        current_app.logger.info(f"Invoice {data.get('invoiceNumber')} saved for client {client_id}")

        return jsonify({
            "success": True,
            "message": f"Invoice {data.get('invoiceNumber')} saved successfully!",
            "invoice_id": invoice_id
        }), 201

    except Exception as e:
        session.rollback()
        current_app.logger.exception(f"Error saving invoice: {e}")
        return jsonify({"error": f"Failed to save invoice: {str(e)}"}), 500
    finally:
        session.close()


# ==========================================
# RECEIPT ROUTES
# ==========================================

@form_bp.route('/receipts/download-pdf', methods=['POST'])
def download_receipt_pdf():
    """Generate and download receipt PDF"""
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
        TOTAL_FILL = (200, 200, 200)
        col_width = 190 / 2
        line_height = 7
        
        # Customer details
        pdf.set_fill_color(*HEADER_FILL)
        pdf.set_draw_color(0, 0, 0)
        pdf.set_font('Arial', 'B', 12)
        pdf.cell(col_width, line_height, 'Customer Details', 'T', 0, 'L', 1)
        pdf.cell(col_width, line_height, 'Date', 'T', 1, 'R', 1)
        pdf.set_font('Arial', '', 10)
        
        pdf.set_font('Arial', 'B', 10)
        pdf.cell(30, line_height, 'Name:', 0, 0, 'L')
        pdf.set_font('Arial', '', 10)
        pdf.cell(col_width - 30, line_height, data.get('customerName', 'N/A'), 0, 0, 'L')
        pdf.cell(col_width, line_height, data.get('receiptDate', datetime.now().strftime('%d/%m/%Y')), 0, 1, 'R')
        
        pdf.set_font('Arial', 'B', 10)
        pdf.cell(30, line_height, 'Address:', 0, 0, 'L')
        pdf.set_font('Arial', '', 10)
        pdf.multi_cell(col_width - 30, line_height, data.get('customerAddress', 'N/A'), 0, 'L', 0)
        
        y_after_address = pdf.get_y()
        pdf.set_font('Arial', 'B', 10)
        pdf.set_xy(10, y_after_address)
        pdf.cell(30, line_height, 'Phone:', 'B', 0, 'L')
        pdf.set_font('Arial', '', 10)
        pdf.cell(col_width - 30, line_height, data.get('customerPhone', 'N/A'), 'B', 1, 'L')
        pdf.ln(5)

        # Payment confirmation
        pdf.set_font('Arial', '', 11)
        pdf.multi_cell(0, 6, f"Confirmation of payment received by BACS for {data.get('paymentDescription', 'your Kitchen/Bedroom Cabinetry')}", 0, 'L')
        pdf.ln(5)

        # Paid amount
        pdf.set_fill_color(*TOTAL_FILL)
        pdf.set_font('Arial', 'B', 14)
        pdf.cell(col_width, 10, 'Paid:', 1, 0, 'L', 1)
        pdf.set_font('Arial', 'B', 16)
        pdf.cell(col_width, 10, f"£{data.get('paidAmount', 0):,.2f}", 1, 1, 'R', 1)
        pdf.ln(5)

        # Summary
        pdf.set_font('Arial', 'B', 11)
        pdf.cell(col_width, 7, 'Paid to date:', 'T', 0, 'L')
        pdf.set_font('Arial', '', 11)
        pdf.cell(col_width, 7, f"£{data.get('totalPaidToDate', 0):,.2f}", 'T', 1, 'R')

        pdf.set_font('Arial', 'B', 12)
        pdf.cell(col_width, 8, 'Balance to Pay:', 'T', 0, 'L')
        pdf.cell(col_width, 8, f"£{data.get('balanceToPay', 0):,.2f}", 'T', 1, 'R')
        pdf.ln(10)

        # Signature
        pdf.set_font('Arial', '', 11)
        pdf.cell(0, 5, 'Many Thanks', 0, 1, 'L')
        pdf.ln(5)
        pdf.set_font('Arial', 'I', 12)
        pdf.cell(0, 5, 'Shahida Macci', 0, 1, 'L')

        pdf_output = pdf.output(dest='S')
        pdf_file = BytesIO(pdf_output)

        customer_name = data.get('customerName', 'Customer').replace(' ', '_')
        date_str = data.get('receiptDate', datetime.now().strftime('%Y-%m-%d'))
        filename = f"Receipt_{data.get('receiptType', 'Payment').title()}_{customer_name}_{date_str}.pdf"
        
        return send_file(pdf_file, mimetype='application/pdf', as_attachment=True, download_name=filename)

    except Exception as e:
        current_app.logger.exception(f"Receipt PDF generation failed: {e}")
        return jsonify({"error": f"Failed to generate Receipt PDF: {str(e)}"}), 500


@form_bp.route('/receipts/save', methods=['POST'])
@token_required
@require_tenant
def save_receipt(tenant_id, employee_id):
    """Save receipt data to Customer_Form_Submissions"""
    session = SessionLocal()
    try:
        data = request.get_json(silent=True) or {}
        client_id = data.get('customerId') or data.get('clientId')
        
        if not client_id:
            return jsonify({'error': 'Missing client ID'}), 400
        
        # Verify client exists
        client_query = text("""
            SELECT client_id FROM "StreemLyne_MT"."Client_Master"
            WHERE client_id = :client_id AND tenant_id = :tenant_id
        """)
        client = session.execute(client_query, {
            'client_id': int(client_id),
            'tenant_id': str(tenant_id)
        }).fetchone()
        
        if not client:
            return jsonify({'error': 'Client not found'}), 404
        
        # Mark as receipt
        data['form_type'] = f"receipt_{data.get('receiptType', 'general')}"
        data['is_receipt'] = True

        insert_query = text("""
            INSERT INTO "StreemLyne_MT"."Customer_Form_Submissions"
            (tenant_id, client_id, form_type, form_name, form_data,
             token_used, submitted_by, submission_status)
            VALUES (:tenant_id, :client_id, :form_type, :form_name, :form_data,
                    :token, :submitted_by, 'submitted')
            RETURNING form_submission_id
        """)
        
        result = session.execute(insert_query, {
            'tenant_id': str(tenant_id),
            'client_id': int(client_id),
            'form_type': data['form_type'],
            'form_name': f"Receipt - {data.get('receiptType', 'Payment')}",
            'form_data': json.dumps(data),
            'token': f"RECEIPT-{data.get('receiptType', '').upper()}-{client_id}-{datetime.utcnow().timestamp()}",
            'submitted_by': request.current_user.username if hasattr(request.current_user, 'username') else 'System'
        })
        
        form_id = result.fetchone().form_submission_id
        session.commit()

        return jsonify({
            "success": True,
            "message": f"Receipt ({data.get('receiptType', 'Payment').title()}) saved successfully!",
            "form_submission_id": form_id
        }), 201

    except Exception as e:
        session.rollback()
        current_app.logger.exception(f"Error saving receipt: {e}")
        return jsonify({"error": f"Failed to save receipt: {str(e)}"}), 500
    finally:
        session.close()


# ==========================================
# CHECKLIST ROUTES
# ==========================================

@form_bp.route('/checklists/download-pdf', methods=['POST'])
def download_checklist_pdf():
    """Generate and download checklist PDF"""
    try:
        data = request.get_json(silent=True) or {}
        
        if not data or not data.get('items'):
            return jsonify({'error': 'Missing form data for PDF generation'}), 400

        pdf = PDF('P', 'mm', 'A4')
        pdf.doc_title = 'Remedial Checklist'
        pdf.alias_nb_pages()
        pdf.add_page()
        pdf.set_auto_page_break(auto=True, margin=15)
        pdf.set_font('Arial', '', 10)
        
        HEADER_FILL_LIGHT = (230, 230, 230)
        HEADER_FILL_DARK = (200, 200, 200)
        col_width = 190 / 2
        line_height = 6

        # Customer details
        pdf.set_fill_color(*HEADER_FILL_LIGHT)
        pdf.set_draw_color(0, 0, 0)
        pdf.set_font('Arial', 'B', 10)
        pdf.cell(col_width, line_height, 'CUSTOMER NAME:', 1, 0, 'L', 1)
        pdf.set_font('Arial', '', 10)
        pdf.cell(col_width, line_height, data.get('customerName', 'N/A'), 1, 1, 'L', 0)
        
        pdf.set_font('Arial', 'B', 10)
        pdf.cell(col_width, line_height, 'CUSTOMER ADDRESS:', 1, 0, 'L', 1)
        pdf.set_font('Arial', '', 10)
        pdf.multi_cell(col_width, line_height, data.get('customerAddress', 'N/A'), 'LRT', 'L', 0)
        end_y = pdf.get_y()
        pdf.set_xy(10, end_y - line_height)
        pdf.cell(col_width, line_height, '', 'B', 0, 'L')
        pdf.set_y(end_y)

        pdf.set_font('Arial', 'B', 10)
        pdf.cell(col_width, line_height, 'CUSTOMER TEL NO.:', 1, 0, 'L', 1)
        pdf.set_font('Arial', '', 10)
        pdf.cell(col_width, line_height, data.get('customerPhone', 'N/A'), 1, 1, 'L', 0)

        pdf.set_font('Arial', 'B', 10)
        pdf.cell(col_width, line_height, 'DATE:', 1, 0, 'L', 1)
        pdf.set_font('Arial', '', 10)
        pdf.cell(col_width, line_height, data.get('date', 'N/A'), 1, 1, 'L', 0)

        pdf.set_font('Arial', 'B', 10)
        pdf.cell(col_width, line_height, 'FITTERS:', 1, 0, 'L', 1)
        pdf.set_font('Arial', '', 10)
        pdf.cell(col_width, line_height, data.get('fitters', 'N/A'), 1, 1, 'L', 0)
        pdf.ln(10)
        
        # Items table
        pdf.set_font('Arial', 'B', 10)
        pdf.cell(0, 5, 'Items Required for Remedial Action', 0, 1, 'L')
        pdf.ln(1)
        
        header = ['NO', 'ITEM', 'REMEDIAL ACTION', 'COLOUR', 'SIZE', 'QTY']
        widths = [10, 50, 60, 25, 25, 20]
        
        pdf.set_fill_color(*HEADER_FILL_DARK)
        pdf.set_font('Arial', 'B', 9)
        
        for i, h in enumerate(header):
            pdf.cell(widths[i], 7, h, 1, 0, 'C', 1)
        pdf.ln()

        pdf.set_font('Arial', '', 9)
        pdf.set_fill_color(255, 255, 255)
        
        for index, item in enumerate(data.get('items', [])):
            if not item.get('item') and not item.get('remedialAction'):
                continue
            
            row_data = [
                str(index + 1),
                item.get('item', ''),
                item.get('remedialAction', ''),
                item.get('colour', ''),
                item.get('size', ''),
                str(item.get('qty', '')),
            ]
            
            x_start = pdf.get_x()
            y_start = pdf.get_y()

            pdf.set_xy(x_start + widths[0], y_start)
            pdf.multi_cell(widths[1], 4, row_data[1], 0, 'L', 0, False)
            h_item = pdf.get_y() - y_start
            
            pdf.set_xy(x_start + widths[0] + widths[1], y_start)
            pdf.multi_cell(widths[2], 4, row_data[2], 0, 'L', 0, False)
            h_action = pdf.get_y() - y_start

            row_h = max(5, h_item, h_action)
            pdf.set_xy(x_start, y_start)

            for i, txt in enumerate(row_data):
                align = 'C' if i == 0 or i >= 3 else 'L'
                
                if i in [1, 2]:
                    x = pdf.get_x()
                    y = pdf.get_y()
                    pdf.cell(widths[i], row_h, '', 1, 0, align, 0)
                    pdf.set_xy(x + widths[i], y)
                else:
                    pdf.cell(widths[i], row_h, txt, 1, 0, align, 0)
            
            pdf.set_xy(x_start + widths[0], y_start)
            pdf.multi_cell(widths[1], 4, row_data[1], 0, 'L', 0, False)
            
            pdf.set_xy(x_start + widths[0] + widths[1], y_start)
            pdf.multi_cell(widths[2], 4, row_data[2], 0, 'L', 0, False)

            pdf.set_y(y_start + row_h)
        
        pdf_output = pdf.output(dest='S')
        pdf_file = BytesIO(pdf_output)

        customer_name = data.get('customerName', 'Customer').replace(' ', '_')
        date_str = data.get('date', datetime.now().strftime('%Y-%m-%d'))
        filename = f"Remedial_Checklist_{customer_name}_{date_str}.pdf"
        
        return send_file(pdf_file, mimetype='application/pdf', as_attachment=True, download_name=filename)

    except Exception as e:
        current_app.logger.exception(f"PDF generation failed: {e}")
        return jsonify({"error": f"Server failed to generate PDF: {str(e)}"}), 500


@form_bp.route('/checklists/save', methods=['POST'])
@token_required
@require_tenant
def save_checklist(tenant_id, employee_id):
    """Save checklist to Customer_Form_Submissions"""
    session = SessionLocal()
    try:
        data = request.get_json(silent=True) or {}
        checklist_type = data.get('checklistType', 'unknown')
        client_id = data.get('customerId') or data.get('clientId')
        
        if not client_id:
            return jsonify({'error': 'Missing client ID'}), 400
        
        # Verify client exists
        client_query = text("""
            SELECT client_id FROM "StreemLyne_MT"."Client_Master"
            WHERE client_id = :client_id AND tenant_id = :tenant_id
        """)
        client = session.execute(client_query, {
            'client_id': int(client_id),
            'tenant_id': str(tenant_id)
        }).fetchone()
        
        if not client:
            return jsonify({'error': 'Client not found'}), 404

        insert_query = text("""
            INSERT INTO "StreemLyne_MT"."Customer_Form_Submissions"
            (tenant_id, client_id, form_type, form_name, form_data,
             token_used, submitted_by, submission_status)
            VALUES (:tenant_id, :client_id, :form_type, :form_name, :form_data,
                    '', :submitted_by, 'submitted')
            RETURNING form_submission_id
        """)
        
        result = session.execute(insert_query, {
            'tenant_id': str(tenant_id),
            'client_id': int(client_id),
            'form_type': f"checklist_{checklist_type}",
            'form_name': f"{checklist_type.title()} Checklist",
            'form_data': json.dumps(data),
            'submitted_by': request.current_user.username if hasattr(request.current_user, 'username') else 'System'
        })
        
        form_id = result.fetchone().form_submission_id
        session.commit()
        
        current_app.logger.info(f"Checklist '{checklist_type}' saved for client {client_id}")

        return jsonify({
            "success": True,
            "message": f"{checklist_type.title()} Checklist saved successfully!",
            "form_submission_id": form_id
        }), 201

    except Exception as e:
        session.rollback()
        current_app.logger.exception(f"Error saving checklist: {e}")
        return jsonify({"error": f"Failed to save checklist: {str(e)}"}), 500
    finally:
        session.close()


# ==========================================
# FORM TOKEN ROUTES
# ==========================================

@form_bp.route('/customers/<int:customer_id>/generate-form-link', methods=['POST'])
@token_required
@require_tenant
def generate_customer_form_link(customer_id, tenant_id, employee_id):
    """Generate form link for specific customer"""
    session = SessionLocal()
    try:
        # Verify customer exists
        customer_query = text("""
            SELECT client_id FROM "StreemLyne_MT"."Client_Master"
            WHERE client_id = :client_id AND tenant_id = :tenant_id
        """)
        customer = session.execute(customer_query, {
            'client_id': customer_id,
            'tenant_id': str(tenant_id)
        }).fetchone()
        
        if not customer:
            return jsonify({'success': False, 'error': 'Customer not found'}), 404

        data = request.get_json(silent=True) or {}
        form_type = data.get('formType', 'bedroom')

        token = generate_secure_token()
        expiration = datetime.now() + timedelta(hours=24)
        
        form_tokens[token] = {
            'customer_id': customer_id,
            'tenant_id': tenant_id,
            'form_type': form_type,
            'created_at': datetime.now(),
            'expires_at': expiration,
            'used': False
        }
        
        current_app.logger.debug(f"Generated token {token} for customer {customer_id}")

        return jsonify({
            'success': True,
            'token': token,
            'form_type': form_type,
            'expires_at': expiration.isoformat(),
            'message': f'{form_type.title()} form link generated successfully'
        }), 200

    except Exception as e:
        current_app.logger.exception(f"Failed to generate form link for customer {customer_id}")
        return jsonify({'success': False, 'error': f'Failed to generate form link: {str(e)}'}), 500
    finally:
        session.close()


@form_bp.route('/validate-form-token/<token>', methods=['GET'])
def validate_form_token(token):
    """Validate form token"""
    try:
        if token not in form_tokens:
            return jsonify({'valid': False, 'error': 'Invalid token'}), 404

        token_data = form_tokens[token]

        if datetime.now() > token_data['expires_at']:
            del form_tokens[token]
            return jsonify({'valid': False, 'error': 'Token has expired'}), 410

        if token_data['used']:
            return jsonify({'valid': False, 'error': 'Token has already been used'}), 410

        return jsonify({
            'valid': True,
            'expires_at': token_data['expires_at'].isoformat(),
            'customer_id': token_data.get('customer_id'),
            'form_type': token_data.get('form_type')
        }), 200

    except Exception as e:
        current_app.logger.exception("Token validation failed")
        return jsonify({'valid': False, 'error': f'Validation failed: {str(e)}'}), 500


@form_bp.route('/submit-customer-form', methods=['POST'])
def submit_customer_form():
    """Submit customer form (public endpoint)"""
    session = SessionLocal()
    try:
        data = request.get_json(silent=True) or {}
        token = data.get('token')
        form_data = data.get('formData', {})
        is_walkin_mode = data.get('isWalkinMode', False)
 
        if not form_data:
            return jsonify({'success': False, 'error': 'Missing form data'}), 400
 
        client_id = None
        tenant_id = None
        
        # ===== WALK-IN CUSTOMER CREATION =====
        if is_walkin_mode:
            current_app.logger.info("Processing walk-in customer submission")
            
            # Extract customer data from form
            customer_name = form_data.get('customer_name', '').strip()
            customer_phone = form_data.get('customer_phone', '').strip()
            customer_address = form_data.get('customer_address', '').strip()
            customer_postcode = form_data.get('customer_postcode') or form_data.get('postcode', '')
            customer_postcode = customer_postcode.strip() if customer_postcode else ''
            
            # Validate required fields
            if not customer_name:
                return jsonify({'success': False, 'error': 'Customer name is required for walk-in submission'}), 400
            if not customer_phone:
                return jsonify({'success': False, 'error': 'Customer phone is required for walk-in submission'}), 400
            if not customer_address:
                return jsonify({'success': False, 'error': 'Customer address is required for walk-in submission'}), 400
            if not customer_postcode:
                return jsonify({'success': False, 'error': 'Customer postcode is required for walk-in submission'}), 400
            
            # Default tenant for walk-in customers
            tenant_id = '7'  # ← CHANGED from 'tenant_1' to match your actual tenant
            
            # Check if customer already exists (by phone or exact name match)
            existing_customer_query = text("""
                SELECT client_id FROM "StreemLyne_MT"."Client_Master"
                WHERE tenant_id = :tenant_id 
                AND (client_phone = :phone OR client_company_name = :name)
                AND (is_deleted IS NULL OR is_deleted = FALSE)
                LIMIT 1
            """)
            
            existing_customer = session.execute(existing_customer_query, {
                'tenant_id': str(tenant_id),
                'phone': customer_phone,
                'name': customer_name
            }).fetchone()
            
            if existing_customer:
                client_id = existing_customer.client_id
                current_app.logger.info(f"Found existing customer: {client_id}")
            else:
                # Create new customer
                current_app.logger.info(f"Creating new walk-in customer: {customer_name}")
                
                insert_customer_query = text("""
                    INSERT INTO "StreemLyne_MT"."Client_Master"
                    (tenant_id, client_company_name, client_phone, address, post_code, 
                     client_type, created_at, is_deleted)
                    VALUES (:tenant_id, :name, :phone, :address, :postcode,
                            'walk_in', CURRENT_TIMESTAMP, FALSE)
                    RETURNING client_id
                """)
                
                result = session.execute(insert_customer_query, {
                    'tenant_id': str(tenant_id),
                    'name': customer_name,
                    'phone': customer_phone,
                    'address': customer_address,
                    'postcode': customer_postcode
                })
                
                client_id = result.fetchone().client_id
                session.flush()  # Ensure client_id is available
                
                current_app.logger.info(f"Created new customer with ID: {client_id}")
            
            # Update form_data with the client_id
            form_data['customer_id'] = str(client_id)
        
        # ===== EXISTING TOKEN VALIDATION (for non-walk-in) =====
        elif token:
            if token not in form_tokens:
                return jsonify({'success': False, 'error': 'Invalid or expired token'}), 400
 
            token_data = form_tokens[token]
            
            if datetime.now() > token_data['expires_at']:
                del form_tokens[token]
                return jsonify({'success': False, 'error': 'Token has expired'}), 410
                
            if token_data['used']:
                return jsonify({'success': False, 'error': 'Token has already been used'}), 410
 
            client_id = token_data.get('customer_id')
            tenant_id = token_data.get('tenant_id')
            
            if client_id and tenant_id:
                # Verify client exists
                client_query = text("""
                    SELECT client_id FROM "StreemLyne_MT"."Client_Master"
                    WHERE client_id = :client_id AND tenant_id = :tenant_id
                """)
                client = session.execute(client_query, {
                    'client_id': client_id,
                    'tenant_id': str(tenant_id)
                }).fetchone()
                
                if not client:
                    return jsonify({'success': False, 'error': 'Associated customer not found'}), 404
                
                form_tokens[token]['used'] = True
        
        # ===== EXTRACT customer_id FROM form_data IF NOT SET =====
        # CRITICAL FIX: Check form_data for customer_id if still None
        if client_id is None:
            # Try to get from form_data (for forms submitted with customerId in URL)
            customer_id_from_form = form_data.get('customer_id', '')
            if customer_id_from_form and customer_id_from_form.strip():
                client_id = int(customer_id_from_form)
                current_app.logger.info(f"✅ Extracted client_id from form_data: {client_id}")
        
        # Get project_id
        project_id = (
            request.args.get('projectId') or
            data.get('projectId') or
            data.get('project_id') or
            form_data.get('project_id') or
            form_data.get('projectId')
        )
        
        if project_id in ('', 'null', 'undefined'):
            project_id = None
        
        # Use default tenant if still None
        if tenant_id is None:
            tenant_id = '7'  # ← CHANGED from 'tenant_1' to match your actual tenant
        
        # ===== CRITICAL VALIDATION: client_id MUST NOT BE NULL =====
        if client_id is None:
            current_app.logger.error("❌ client_id is None - cannot insert")
            return jsonify({
                'success': False, 
                'error': 'Customer ID is required. Please select a customer or use walk-in mode.'
            }), 400
        
        # Save form submission
        insert_query = text("""
            INSERT INTO "StreemLyne_MT"."Customer_Form_Submissions"
            (tenant_id, client_id, project_id, form_type, form_data,
             token_used, submitted_by, submission_status)
            VALUES (:tenant_id, :client_id, :project_id, :form_type, :form_data,
                    :token, :submitted_by, 'submitted')
            RETURNING form_submission_id
        """)
        
        # Determine form type
        form_type = form_data.get('form_type', 'general')
        if form_type == 'kitchen':
            form_type = 'kitchen_checklist'
        elif form_type == 'bedroom':
            form_type = 'bedroom_checklist'
        
        current_app.logger.info(f"💾 Saving form: tenant_id={tenant_id}, client_id={client_id}, form_type={form_type}")
        
        result = session.execute(insert_query, {
            'tenant_id': str(tenant_id),
            'client_id': int(client_id),  # Ensure it's an integer
            'project_id': int(project_id) if project_id else None,
            'form_type': form_type,
            'form_data': json.dumps(form_data),
            'token': token or '',
            'submitted_by': 'Walk-in Customer' if is_walkin_mode else 'Public Form'
        })
        
        form_id = result.fetchone().form_submission_id
        session.commit()
 
        current_app.logger.info(f"✅ Form submitted successfully: form_id={form_id}")
 
        return jsonify({
            'success': True,
            'customer_id': client_id,  # Return customer_id for frontend redirect
            'client_id': client_id,
            'project_id': project_id,
            'form_submission_id': form_id,
            'message': 'Walk-in customer created and form submitted successfully' if is_walkin_mode else 'Form submitted successfully'
        }), 201
 
    except Exception as e:
        session.rollback()
        current_app.logger.exception(f"❌ Form submission failed: {e}")
        return jsonify({'success': False, 'error': f'Form submission failed: {str(e)}'}), 500
    finally:
        session.close()

@form_bp.route('/cleanup-expired-tokens', methods=['POST'])
def cleanup_expired_tokens():
    """Cleanup expired tokens"""
    try:
        current_time = datetime.now()
        expired_tokens = [t for t, d in form_tokens.items() if current_time > d['expires_at']]
        for t in expired_tokens:
            del form_tokens[t]
        return jsonify({
            'success': True,
            'cleaned_tokens': len(expired_tokens),
            'remaining_tokens': len(form_tokens)
        }), 200
    except Exception as e:
        current_app.logger.exception("Cleanup failed")
        return jsonify({'success': False, 'error': f'Cleanup failed: {str(e)}'}), 500


# ==========================================
# FORM SUBMISSION MANAGEMENT
# ==========================================

@form_bp.route('/form-submissions/<int:submission_id>', methods=['GET', 'PUT', 'DELETE'])
@token_required
@require_tenant
def handle_form_submission(submission_id, tenant_id, employee_id):
    """Get, update, or delete form submission"""
    session = SessionLocal()
    try:
        # Get form submission
        query = text("""
            SELECT * FROM "StreemLyne_MT"."Customer_Form_Submissions"
            WHERE form_submission_id = :form_id AND tenant_id = :tenant_id
        """)
        
        submission = session.execute(query, {
            'form_id': submission_id,
            'tenant_id': str(tenant_id)
        }).fetchone()
        
        if not submission:
            return jsonify({'error': 'Form submission not found'}), 404
        
        # GET
        if request.method == 'GET':
            # Get client info
            client_query = text("""
                SELECT client_company_name FROM "StreemLyne_MT"."Client_Master"
                WHERE client_id = :client_id
            """)
            client = session.execute(client_query, {
                'client_id': submission.client_id
            }).fetchone()
            
            return jsonify({
                'id': submission.form_submission_id,
                'client_id': submission.client_id,
                'customer_name': client.client_company_name if client else 'N/A',
                'form_data': submission.form_data,
                'submitted_at': submission.submitted_at.isoformat() if submission.submitted_at else None
            }), 200
        
        # PUT
        elif request.method == 'PUT':
            data = request.get_json(silent=True) or {}
            updated_form_data = data.get('formData')
            
            if not updated_form_data:
                return jsonify({'error': 'Missing form data'}), 400
            
            update_query = text("""
                UPDATE "StreemLyne_MT"."Customer_Form_Submissions"
                SET form_data = :form_data
                WHERE form_submission_id = :form_id AND tenant_id = :tenant_id
            """)
            
            session.execute(update_query, {
                'form_data': json.dumps(updated_form_data),
                'form_id': submission_id,
                'tenant_id': str(tenant_id)
            })
            session.commit()

            return jsonify({
                'success': True,
                'message': 'Form updated successfully',
                'form_submission_id': submission_id
            }), 200
        
        # DELETE
        elif request.method == 'DELETE':
            delete_query = text("""
                DELETE FROM "StreemLyne_MT"."Customer_Form_Submissions"
                WHERE form_submission_id = :form_id AND tenant_id = :tenant_id
            """)
            
            session.execute(delete_query, {
                'form_id': submission_id,
                'tenant_id': str(tenant_id)
            })
            session.commit()
            
            return jsonify({
                'success': True,
                'message': 'Form submission deleted successfully',
                'id': submission_id
            }), 200

    except Exception as e:
        session.rollback()
        current_app.logger.exception(f"Error handling form submission {submission_id}: {e}")
        return jsonify({'error': f'Operation failed: {str(e)}'}), 500
    finally:
        session.close()

@form_bp.route('/customers', methods=['GET'])
@token_required
@require_tenant
def get_customers_for_forms(tenant_id, employee_id):
    """Get all customers for the current tenant"""
    session = SessionLocal()
    try:
        query = text("""
            SELECT 
                client_id as id,
                client_company_name as name,
                address,
                client_phone as phone,
                client_email as email,
                post_code as postcode
            FROM "StreemLyne_MT"."Client_Master"
            WHERE tenant_id = :tenant_id
            AND (is_deleted IS NULL OR is_deleted = FALSE)
            ORDER BY client_company_name ASC
        """)
        
        customers = session.execute(query, {
            'tenant_id': str(tenant_id)
        }).fetchall()
        
        customers_list = []
        for customer in customers:
            customers_list.append({
                'id': str(customer.id),
                'name': customer.name or 'N/A',
                'address': customer.address or '',
                'phone': customer.phone or '',
                'email': customer.email or '',
                'postcode': customer.postcode or ''
            })
        
        return jsonify(customers_list), 200

    except Exception as e:
        current_app.logger.exception(f"Failed to fetch customers: {e}")
        return jsonify({'error': f'Failed to fetch customers: {str(e)}'}), 500
    finally:
        session.close()