from fpdf import FPDF


class PDF(FPDF):
    """Shared PDF base class with Aztec Interiors header and page-number footer."""

    def __init__(self, *args, **kwargs):
        self.show_header = kwargs.pop('show_header', True)
        super().__init__(*args, **kwargs)
        self.doc_title = ''

    def header(self):
        if not self.show_header:
            return
        self.set_font('Arial', 'B', 16)
        self.cell(0, 10, 'AZTEC INTERIORS LEICESTER LTD', 0, 1, 'C')
        self.set_font('Arial', '', 10)
        self.cell(0, 5, '127 Barkby Rd, Leicester LE4 9LG', 0, 1, 'C')
        self.cell(0, 5, 'Tel: 0116 2761866 | Email: aztecinteriors@hotmail.co.uk', 0, 1, 'C')
        self.ln(5)

        if self.doc_title:
            self.set_font('Arial', 'B', 14)
            self.cell(0, 8, self.doc_title, 0, 1, 'C')
            self.ln(5)

    def footer(self):
        self.set_y(-15)
        self.set_font('Arial', 'I', 8)
        self.cell(0, 10, f'Page {self.page_no()}/{{nb}}', 0, 0, 'C')