from fpdf import FPDF


class PDF(FPDF):
    """Shared PDF base class with Atelier Luxe Interiors header and page-number footer."""

    def __init__(self, *args, **kwargs):
        self.show_header = kwargs.pop('show_header', True)
        super().__init__(*args, **kwargs)
        self.doc_title = ''

    def header(self):
        if not self.show_header:
            return

        # Reset colours before drawing header
        self.set_text_color(0, 0, 0)
        self.set_draw_color(0, 0, 0)

        import os
        logo_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'static', 'images', 'logo3.png')

        logo_w = 18
        logo_h = 18
        name_text = 'ATELIER LUXE INTERIORS'

        # Measure text width to calculate total block width
        self.set_font('Arial', 'B', 18)
        text_w = self.get_string_width(name_text)
        gap = 3
        total_w = logo_w + gap + text_w

        # Center the whole block
        start_x = (self.w - total_w) / 2
        y_start = 8

        if os.path.exists(logo_path):
            self.image(logo_path, x=start_x, y=y_start, w=logo_w, h=logo_h)

        self.set_xy(start_x + logo_w + gap, y_start + 3)
        self.set_font('Arial', 'B', 18)
        self.cell(text_w, 12, name_text, 0, 1, 'L')

        self.ln(2)
        self.set_font('Arial', '', 9)
        self.cell(0, 5, '127 Barkby Rd, Leicester LE4 9LG', 0, 1, 'C')
        self.cell(0, 5, 'Tel: 07821 328849 | Email: info@atelierluxe.co.uk', 0, 1, 'C')
        self.ln(5)

        if self.doc_title:
            self.set_font('Arial', 'B', 14)
            self.cell(0, 8, self.doc_title, 0, 1, 'C')
            self.ln(5)

        # Always reset to black after header
        self.set_text_color(0, 0, 0)
        self.set_font('Arial', '', 9)

    def footer(self):
        self.set_y(-15)
        self.set_font('Arial', 'I', 8)
        self.cell(0, 10, f'Page {self.page_no()}/{{nb}}', 0, 0, 'C')