from flask import render_template, jsonify
from config import app, latest_structured_data, FORM_COLUMNS

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/view-data')
def view_data():
    if not latest_structured_data:
        return render_template('table.html', columns=FORM_COLUMNS, data=None, error="No data available. Please upload an image first.")
    return render_template('table.html', columns=FORM_COLUMNS, data=latest_structured_data, error=None)