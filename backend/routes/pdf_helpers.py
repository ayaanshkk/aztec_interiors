import struct
from fpdf import FPDF


def _png_dimensions(path):
    """Return (width_px, height_px) from PNG IHDR without Pillow."""
    try:
        with open(path, 'rb') as f:
            data = f.read(24)
        w = struct.unpack('>I', data[16:20])[0]
        h = struct.unpack('>I', data[20:24])[0]
        return w, h
    except Exception:
        return None, None


# ── Colour palette ─────────────────────────────────────────────────────────────
_BLACK  = (0,   0,   0)
_DARK   = (30,  30,  30)
_MID    = (80,  80,  80)
_LIGHT  = (130, 130, 130)
_RULE   = (200, 200, 200)   # thin separator lines
_SUBROW = (248, 248, 248)   # sub-item row tint (not used for fill, kept for reference)


class PDF(FPDF):
    """Atelier Luxe Interiors shared PDF base — clean, minimal design."""

    def __init__(self, *args, **kwargs):
        self.show_header = kwargs.pop('show_header', True)
        super().__init__(*args, **kwargs)
        self.doc_title   = ''
        self.include_vat = True  # set to False when vat_rate == 0

    # ── Page header ────────────────────────────────────────────────────────────

    def header(self):
        if not self.show_header:
            return

        import os
        self.set_text_color(*_BLACK)
        self.set_draw_color(*_BLACK)
        self.set_line_width(0.2)

        logo_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            '..', 'static', 'images', 'logo-full.png'
        )

        y_start = 8
        logo_w  = 100   # mm — width of logo on page

        # Compute proportional height so the logo is never stretched
        logo_h = 26     # safe default
        if os.path.exists(logo_path):
            img_w_px, img_h_px = _png_dimensions(logo_path)
            if img_w_px:
                logo_h = round(logo_w * img_h_px / img_w_px, 1)
            self.image(logo_path, x=10, y=y_start, w=logo_w, h=logo_h)

        # Right: company info — vertically centre against logo
        right_x = 120
        right_w = self.w - right_x - 10
        info_block_h = 5 + 4 * 3   # 1 bold line + 3 regular lines
        info_y = y_start + max(0, (logo_h - info_block_h) / 2)
        self.set_xy(right_x, info_y)
        self.set_font('Arial', 'B', 9)
        self.set_text_color(*_BLACK)
        self.cell(right_w, 5, 'Atelier Luxe Interiors Ltd', 0, 2, 'R')
        self.set_font('Arial', '', 8)
        self.set_text_color(*_MID)
        lines = [
            '127c Barkby Road, Leicester, LE4 9LG',
            'M: 07821 328849',
            'E: accounts@atelierluxe.co.uk',
            'Registered in England No. 17200862',
        ]
        if self.include_vat:
            lines.append('VAT Reg No: 528 7517 62')
        for line in lines:
            self.cell(right_w, 4, self._enc(line), 0, 2, 'R')

        # Thick black rule below header — sits below whichever side is taller
        rule_y = y_start + logo_h + 4
        self.set_y(rule_y)
        self.set_draw_color(*_BLACK)
        self.set_line_width(0.5)
        self.line(10, rule_y, self.w - 10, rule_y)
        self.set_line_width(0.2)
        self.set_draw_color(*_RULE)

        self.ln(6)

        if self.doc_title:
            self.set_font('Arial', 'B', 16)
            self.set_text_color(*_BLACK)
            self.cell(0, 8, self.doc_title.upper(), 0, 1, 'C')
            self.ln(4)

        self.set_text_color(*_BLACK)
        self.set_font('Arial', '', 9)

    # ── Page footer ────────────────────────────────────────────────────────────

    def footer(self):
        self.set_y(-13)
        self.set_font('Arial', '', 7)
        self.set_text_color(*_LIGHT)
        self.cell(0, 5, f'Page {self.page_no()}/{{nb}}', 0, 0, 'C')
        self.set_text_color(*_BLACK)

    # ── Shared drawing helpers ─────────────────────────────────────────────────

    def _enc(self, s):
        return (s or '').encode('latin-1', errors='ignore').decode('latin-1')

    def thin_rule(self, x1=None, x2=None):
        """Draw a light thin horizontal rule at current y."""
        if x1 is None:
            x1 = 10
        if x2 is None:
            x2 = self.w - 10
        y = self.get_y()
        self.set_draw_color(*_RULE)
        self.set_line_width(0.2)
        self.line(x1, y, x2, y)
        self.set_draw_color(*_RULE)

    def thick_rule(self, x1=None, x2=None):
        """Draw a thick black horizontal rule at current y."""
        if x1 is None:
            x1 = 10
        if x2 is None:
            x2 = self.w - 10
        y = self.get_y()
        self.set_draw_color(*_BLACK)
        self.set_line_width(0.5)
        self.line(x1, y, x2, y)
        self.set_line_width(0.2)
        self.set_draw_color(*_RULE)

    def draw_two_col_customer(self, left_title, left_rows, right_title, right_rows):
        """
        Draw a 2-column customer section.
        left_rows  : list of plain strings (name, address, postcode, phone, …)
        right_rows : list of (label, value) tuples (doc no, date, order ref, colours, …)
        """
        left_x  = 10
        right_x = 110
        col_w   = 90
        row_h   = 5.5
        label_w = 36

        start_y = self.get_y()

        # ── Left column ────────────────────────────────────────────────────────
        self.set_xy(left_x, start_y)
        self.set_font('Arial', '', 7)
        self.set_text_color(*_LIGHT)
        self.cell(col_w, 4, left_title.upper(), 0, 1, 'L')

        for i, text in enumerate(left_rows):
            text = self._enc(text)
            self.set_xy(left_x, self.get_y())
            if i == 0:
                self.set_font('Arial', 'B', 10)
                self.set_text_color(*_BLACK)
            else:
                self.set_font('Arial', '', 9)
                self.set_text_color(*_DARK)
            self.cell(col_w, row_h, text[:55], 0, 1, 'L')
            self.set_draw_color(*_RULE)
            self.set_line_width(0.2)
            self.line(left_x, self.get_y(), left_x + col_w, self.get_y())

        left_end_y = self.get_y()

        # ── Right column ───────────────────────────────────────────────────────
        self.set_xy(right_x, start_y)
        self.set_font('Arial', '', 7)
        self.set_text_color(*_LIGHT)
        self.cell(col_w, 4, right_title.upper(), 0, 1, 'L')

        for label, value in right_rows:
            label = self._enc(label)
            value = self._enc(value)
            self.set_xy(right_x, self.get_y())
            self.set_font('Arial', '', 7)
            self.set_text_color(*_LIGHT)
            self.cell(label_w, row_h, label.upper(), 0, 0, 'L')
            self.set_font('Arial', '', 9)
            self.set_text_color(*_DARK)
            self.cell(col_w - label_w, row_h, value, 0, 1, 'L')
            self.set_xy(right_x, self.get_y())
            self.set_draw_color(*_RULE)
            self.set_line_width(0.2)
            self.line(right_x, self.get_y(), right_x + col_w, self.get_y())

        right_end_y = self.get_y()

        # Move past both columns (no separator — spec strip follows directly)
        end_y = max(left_end_y, right_end_y) + 4
        self.set_y(end_y)
        self.set_text_color(*_BLACK)

    def draw_spec_strip(self, spec_rows):
        """
        Draw spec fields (Order Ref, colours, etc.) as a compact horizontal strip
        spanning the full page width, between the customer block and bank details.
        spec_rows: list of (label, value) tuples
        """
        if not spec_rows:
            return
        strip_x = 10
        strip_w = self.w - 20
        pad     = 3
        row_h   = 5.5
        strip_y = self.get_y()
        strip_h = pad + row_h + pad

        # Light grey background
        self.set_fill_color(250, 250, 250)
        self.set_draw_color(*_RULE)
        self.set_line_width(0.2)
        self.rect(strip_x, strip_y, strip_w, strip_h, 'FD')

        # Spread the fields evenly across the strip
        col_w = strip_w / len(spec_rows)
        self.set_y(strip_y + pad)
        for i, (label, value) in enumerate(spec_rows):
            x = strip_x + i * col_w
            cell_w = col_w - 4
            self.set_xy(x + 2, strip_y + pad)
            self.set_font('Arial', '', 6.5)
            self.set_text_color(*_LIGHT)
            self.cell(cell_w, row_h * 0.5, self._enc(label).upper(), 0, 2, 'L')
            self.set_font('Arial', '', 8.5)
            self.set_text_color(*_DARK)
            # Truncate value to prevent overflow into adjacent column
            encoded_val = self._enc(value)
            original_val = encoded_val
            while encoded_val and self.get_string_width(encoded_val) > cell_w:
                encoded_val = encoded_val[:-1]
            if encoded_val != original_val and encoded_val:
                encoded_val = encoded_val[:-2] + '...'
            self.cell(cell_w, row_h * 0.6, encoded_val, 0, 0, 'L')

        self.set_y(strip_y + strip_h + 4)
        self.set_text_color(*_BLACK)

    def draw_bank_details_box(self):
        """Draw bank details in a compact 2-column highlighted box."""
        box_x  = 10
        box_w  = self.w - 20
        pad    = 3
        row_h  = 5.0
        # Left column: 3 rows | Right column: 3 rows (same height)
        left_rows  = [
            ('BACS Payment', 'Atelier Luxe Interiors LTD'),
            ('Bank',         'ClearBank'),
            ('Reference',    'Your name / road'),
        ]
        right_rows = [
            ('Sort Code',  '04-06-05'),
            ('Account No', '31621197'),
        ]
        n_rows = max(len(left_rows), len(right_rows))
        box_h  = pad + n_rows * row_h + pad
        box_y  = self.get_y()

        self.set_fill_color(245, 245, 245)
        self.set_draw_color(210, 210, 210)
        self.set_line_width(0.3)
        self.rect(box_x, box_y, box_w, box_h, 'FD')

        col_w   = box_w / 2
        label_w = 28

        for col_i, rows in enumerate([left_rows, right_rows]):
            col_x = box_x + col_i * col_w
            for row_i, (label, value) in enumerate(rows):
                y = box_y + pad + row_i * row_h
                self.set_xy(col_x + pad, y)
                self.set_font('Arial', '', 6.5)
                self.set_text_color(*_LIGHT)
                self.cell(label_w, row_h, label.upper(), 0, 0, 'L')
                self.set_font('Arial', '', 8.5)
                self.set_text_color(*_DARK)
                self.cell(col_w - label_w - pad * 2, row_h, value, 0, 0, 'L')

        self.set_y(box_y + box_h + 4)
        self.set_text_color(*_BLACK)

    def draw_section_label(self, name):
        """Section heading: small gray label + extending thin rule (Modern SaaS style)."""
        # Need room for label (6) + header (7) + at least two rows (~12) = 25mm
        if self.get_y() > self.h - self.b_margin - 25:
            self.add_page()
        text = name.upper()
        self.set_font('Arial', 'B', 7)
        self.set_text_color(*_LIGHT)
        tw = self.get_string_width(text)
        x0, y0 = self.get_x(), self.get_y()
        self.cell(tw + 3, 5, text, 0, 0, 'L')
        self.set_draw_color(*_RULE)
        self.set_line_width(0.2)
        self.line(x0 + tw + 5, y0 + 2.5, self.w - 10, y0 + 2.5)
        self.ln(6)
        self.set_text_color(*_BLACK)

    def draw_table_header(self, headers, widths):
        """Stone-tinted table header with thin bottom rule."""
        self.set_fill_color(245, 243, 240)
        self.set_font('Arial', 'B', 6)
        self.set_text_color(120, 113, 108)
        x0 = self.get_x()
        for h, w in zip(headers, widths):
            align = 'C' if h in ('QTY', 'W', 'H', 'D', 'DISC %') else ('R' if h in ('PRICE', 'AMOUNT', 'FINAL') else 'L')
            self.cell(w, 7, h.upper(), 0, 0, align, fill=True)
        self.ln()
        y = self.get_y()
        self.set_draw_color(214, 211, 209)
        self.set_line_width(0.2)
        self.line(x0, y, x0 + sum(widths), y)
        self.set_draw_color(*_RULE)
        self.set_fill_color(255, 255, 255)
        self.set_text_color(*_BLACK)
        self.set_font('Arial', '', 9)

    def draw_section_total_block(self, section, raw, discount_amt, total, x=120):
        """Section totals: stone-tinted rows, dark-filled total row."""
        label_w = 50
        val_w   = 30
        lh      = 5

        self.set_fill_color(250, 250, 249)
        self.set_font('Arial', '', 8)
        self.set_text_color(*_MID)
        self.set_x(x)
        self.cell(label_w, lh, f'{section} Subtotal', 0, 0, 'R', fill=True)
        self.set_text_color(*_DARK)
        self.cell(val_w, lh, f'\xa3{raw:.2f}', 0, 1, 'R', fill=True)

        if discount_amt > 0.005:
            self.set_x(x)
            self.set_font('Arial', '', 8)
            self.set_text_color(*_MID)
            self.cell(label_w, lh, 'Item Discounts', 0, 0, 'R', fill=True)
            self.set_text_color(200, 50, 50)
            self.cell(val_w, lh, f'-\xa3{discount_amt:.2f}', 0, 1, 'R', fill=True)
            self.set_text_color(*_BLACK)

        self.set_x(x)
        self.set_fill_color(23, 23, 23)
        self.set_text_color(255, 255, 255)
        self.set_font('Arial', 'B', 9)
        self.cell(label_w, lh + 2, f'{section} Total', 0, 0, 'R', fill=True)
        self.cell(val_w, lh + 2, f'\xa3{total:.2f}', 0, 1, 'R', fill=True)
        self.set_fill_color(255, 255, 255)
        self.set_text_color(*_BLACK)
        self.ln(4)

    def draw_grand_totals(self, rows, balance_label, balance_value, x=105):
        """
        rows         : list of (label, value_str) — subtotal, VAT, discount, etc.
        balance_label: e.g. 'TOTAL', 'BALANCE DUE'
        balance_value: e.g. '£1,234.00'
        """
        label_w = 55
        val_w   = 30
        lh      = 5.5

        self.set_fill_color(250, 250, 249)
        for label, value in rows:
            self.set_x(x)
            self.set_font('Arial', '', 9)
            self.set_text_color(*_MID)
            self.cell(label_w, lh, label, 0, 0, 'R', fill=True)
            self.set_font('Arial', '', 9)
            self.set_text_color(*_DARK)
            self.cell(val_w, lh, value, 0, 1, 'R', fill=True)

        # Dark-filled balance row
        self.set_x(x)
        self.set_fill_color(23, 23, 23)
        self.set_text_color(255, 255, 255)
        self.set_font('Arial', 'B', 11)
        self.cell(label_w, 8, balance_label, 0, 0, 'R', fill=True)
        self.cell(val_w, 8, balance_value, 0, 1, 'R', fill=True)
        self.set_fill_color(255, 255, 255)
        self.ln(6)
        self.set_text_color(*_BLACK)

    def draw_signature_lines(self, labels=None):
        """Draw signature/date lines at the bottom."""
        if labels is None:
            labels = ['Customer Signature', 'Customer Name', 'Date']
        self.set_font('Arial', '', 9)
        self.set_text_color(*_MID)
        for label in labels:
            self.cell(45, 6, label + ':', 0, 0, 'L')
            self.set_draw_color(*_RULE)
            self.cell(145, 6, '', 'B', 1, 'L')
            self.ln(3)
        self.set_text_color(*_BLACK)

    def draw_signature_data(self, sig_type='none', sig_image='', sig_text='', sig_name='', sig_date=''):
        """Render actual signature data in the PDF."""
        import base64, tempfile, os as _os
        if self.get_y() + 40 > self.h - 20:
            self.add_page()
        self.ln(4)
        self.set_font('Arial', 'B', 8)
        self.set_text_color(150, 150, 150)
        self.cell(0, 5, 'AUTHORISATION', 0, 1, 'L')
        self.set_text_color(0, 0, 0)
        self.ln(2)
        self.set_draw_color(*_RULE)

        # Row 1: Customer Name (full width)
        self.set_font('Arial', '', 9)
        self.set_text_color(*_MID)
        self.cell(45, 6, 'Customer Name:', 0, 0, 'L')
        self.set_text_color(30, 30, 30) if sig_name else self.set_text_color(*_MID)
        self.cell(145, 6, self._enc(sig_name) if sig_name else '', 'B', 1, 'L')
        self.ln(4)

        # Row 2: Customer Signature (left ~60%) | Date (right ~40%)
        self.set_font('Arial', '', 9)
        self.set_text_color(*_MID)
        label_w  = 45
        sig_w    = 95
        gap      = 10
        date_lbl = 15
        date_w   = self.w - 10 - label_w - sig_w - gap - date_lbl - 10

        self.cell(label_w, 6, 'Customer Signature:', 0, 0, 'L')
        sig_x = self.get_x()
        sig_y = self.get_y()

        if sig_type == 'draw' and sig_image and sig_image.startswith('data:image'):
            try:
                _, b64data = sig_image.split(',', 1)
                tmp = tempfile.NamedTemporaryFile(suffix='.png', delete=False)
                tmp.write(base64.b64decode(b64data))
                tmp.close()
                self.image(tmp.name, x=sig_x, y=sig_y - 2, w=sig_w, h=14)
                _os.unlink(tmp.name)
                self.line(sig_x, sig_y + 6, sig_x + sig_w, sig_y + 6)
                self.set_xy(sig_x + sig_w + gap, sig_y)
            except Exception:
                self.cell(sig_w, 6, '', 'B', 0, 'L')
                self.set_x(self.get_x() + gap)
        elif sig_type == 'type' and sig_text:
            self.set_font('Helvetica', 'I', 14)
            self.set_text_color(26, 26, 46)
            self.cell(sig_w, 8, self._enc(sig_text), 'B', 0, 'L')
            self.set_font('Arial', '', 9)
            self.set_text_color(*_MID)
            self.set_x(self.get_x() + gap)
        else:
            self.cell(sig_w, 6, '', 'B', 0, 'L')
            self.set_x(self.get_x() + gap)

        # Date — same row
        self.set_font('Arial', '', 9)
        self.set_text_color(*_MID)
        self.cell(date_lbl, 6, 'Date:', 0, 0, 'L')
        self.set_text_color(30, 30, 30) if sig_date else self.set_text_color(*_MID)
        self.cell(date_w, 6, self._enc(sig_date) if sig_date else '', 'B', 1, 'L')
        self.set_text_color(*_BLACK)
