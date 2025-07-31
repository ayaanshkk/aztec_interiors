import os
import json
from flask import Flask, request, jsonify, send_file, render_template
from flask_cors import CORS
from werkzeug.utils import secure_filename
from google.cloud import vision
from google.cloud.vision_v1 import types
from openai import OpenAI
from dotenv import load_dotenv
from datetime import datetime
# Placeholder imports - replace with your actual implementations
from pdf_generator import generate_pdf
from excel_exporter import export_to_excel

# Load environment variables
load_dotenv()

# Initialize OpenAI client
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# Initialize Google Vision client
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
vision_client = vision.ImageAnnotatorClient()

# Define your form columns in the exact order they appear on the form
FORM_COLUMNS = [
    # Customer Information Section
    "customer_name",
    "address", 
    "room",
    "tel_mob_number",
    "survey_date",
    "appt_date",
    "pro_inst_date",
    "comp_chk_date",
    "date_deposit_paid",
    
    # Style and Color Section
    "fitting_style",
    "door_style",
    "door_colour",
    "end_panel_colour",
    "plinth_filler_colour",
    "worktop_colour",
    "cabinet_colour",
    "handles_code_qty_size",
    
    # Bedside Cabinets
    "bedside_cabinets_floating",
    "bedside_cabinets_fitted", 
    "bedside_cabinets_freestand",
    "bedside_cabinets_qty",
    
    # Dresser/Desk
    "dresser_desk_yes",
    "dresser_desk_no",
    "dresser_desk_qty_size",
    
    # Internal Mirror
    "internal_mirror_yes",
    "internal_mirror_no", 
    "internal_mirror_qty_size",
    
    # Mirror
    "mirror_silver",
    "mirror_bronze",
    "mirror_grey",
    "mirror_qty",
    
    # Soffit Lights
    "soffit_lights_spot",
    "soffit_lights_strip",
    "soffit_lights_colour",
    "soffit_lights_cool_white",
    "soffit_lights_warm_white",
    "soffit_lights_qty",
    
    # Gable Lights
    "gable_lights_colour",
    "gable_lights_profile_colour",
    "gable_lights_black",
    "gable_lights_white", 
    "gable_lights_qty",
    
    # Other/Misc/Accessories
    "carpet_protection",
    "floor_tile_protection",
    "no_floor",
    
    # Terms and Signature
    "date_terms_conditions_given",
    "gas_electric_installation_terms_given",
    "customer_signature",
    "signature_date"
]

UPLOAD_FOLDER = 'Uploads'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'bmp'}

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size

# Enable CORS for all routes
CORS(app, resources={r"/*": {"origins": "*"}})  # Adjust origins for production

# Create directories if they don't exist
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs('generated_pdfs', exist_ok=True)
os.makedirs('generated_excel', exist_ok=True)

# Temporary store for latest structured data
latest_structured_data = {}

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def extract_text_from_image(file_path):
    """
    Extract text from an image using Google Cloud Vision API
    
    Args:
        file_path (str): Path to the image file
        
    Returns:
        str: Extracted text or empty string if none found
    """
    try:
        with open(file_path, 'rb') as image_file:
            content = image_file.read()
        
        image = types.Image(content=content)
        response = vision_client.text_detection(image=image)
        texts = response.text_annotations
        
        if texts:
            return texts[0].description  # Return the full text
        return ""
    except Exception as e:
        print(f"Google Vision API error: {str(e)}")
        return ""

def structure_data_with_openai(raw_text):
    """
    Use OpenAI API to structure raw text into predefined form columns
    
    Args:
        raw_text (str): Raw text extracted from image
        
    Returns:
        dict: Structured data with form columns as keys
    """
    try:
        print(f"Processing text of length: {len(raw_text)}")
        print(f"Text preview: {raw_text[:300]}...")
        
        # Create the prompt with specific column names
        column_list = ", ".join(FORM_COLUMNS)
        
        prompt = f"""
        You are extracting data from a BEDROOM CHECKLIST form. Extract information and organize it into a JSON format using ONLY these exact field names.

        CRITICAL INSTRUCTIONS FOR CHECKBOXES:
        1. Use ONLY the field names provided below - do not create new fields
        2. For checkbox fields: 
           - Put "✓" ONLY if you can clearly see a checkmark, tick, or X mark in that specific box
           - Put null (not "✗") if the checkbox is empty or unclear
           - DO NOT assume or add "✗" for empty checkboxes
        3. For text fields, extract the exact text written in the form
        4. For empty fields, use null
        5. Return valid JSON only

        FIELD NAMES TO USE:
        {column_list}

        FORM SECTIONS TO EXTRACT:
        
        CUSTOMER INFORMATION:
        - customer_name: Name written in the form
        - address: Address written  
        - room: Room type if specified
        - tel_mob_number: Phone number
        - survey_date, appt_date, pro_inst_date, comp_chk_date, date_deposit_paid: Any dates filled

        STYLE SPECIFICATIONS:
        - fitting_style, door_style: Style selections
        - door_colour, end_panel_colour, plinth_filler_colour, worktop_colour, cabinet_colour: Colors chosen
        - handles_code_qty_size: Handle specifications

        CHECKBOX SECTIONS - ONLY mark as "✓" if you see an actual checkmark/tick/X:
        
        BEDSIDE CABINETS:
        - bedside_cabinets_floating, bedside_cabinets_fitted, bedside_cabinets_freestand: ONLY "✓" if clearly marked
        - bedside_cabinets_qty: Quantity if specified

        DRESSER/DESK:
        - dresser_desk_yes, dresser_desk_no: ONLY "✓" if clearly marked
        - dresser_desk_qty_size: Size/quantity if specified

        INTERNAL MIRROR:
        - internal_mirror_yes, internal_mirror_no: ONLY "✓" if clearly marked
        - internal_mirror_qty_size: Details if specified

        MIRROR OPTIONS:
        - mirror_silver, mirror_bronze, mirror_grey: ONLY "✓" if clearly marked
        - mirror_qty: Quantity

        SOFFIT LIGHTS:
        - soffit_lights_spot, soffit_lights_strip: ONLY "✓" if clearly marked
        - soffit_lights_cool_white, soffit_lights_warm_white: ONLY "✓" if clearly marked
        - soffit_lights_colour, soffit_lights_qty: Other specifications

        GABLE LIGHTS:
        - gable_lights_black, gable_lights_white: ONLY "✓" if clearly marked  
        - gable_lights_colour, gable_lights_profile_colour, gable_lights_qty: Other specifications

        ACCESSORIES:
        - carpet_protection, floor_tile_protection, no_floor: ONLY "✓" if clearly marked

        TERMS AND SIGNATURE:
        - date_terms_conditions_given, gas_electric_installation_terms_given: Dates if filled
        - customer_signature, signature_date: Signature info

        REMEMBER: Empty checkboxes should be null, NOT "✗". Only use "✓" for clearly marked boxes.

        Raw text from form:
        {raw_text}

        Return only the JSON object with the extracted data:
        """

        # Make API call to OpenAI
        print("Sending request to OpenAI...")
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {
                    "role": "system", 
                    "content": "You are a data extraction expert. For checkboxes, only mark as checked (✓) if you clearly see a mark. Leave empty checkboxes as null. Return only valid JSON."
                },
                {
                    "role": "user", 
                    "content": prompt
                }
            ],
            temperature=0.1,  # Lower temperature for more consistent results
            max_tokens=1000
        )

        # Extract the response content
        reply = response.choices[0].message.content.strip()
        print(f"OpenAI response: {reply}")
        
        # Clean up the response (remove any markdown formatting)
        if reply.startswith('```json'):
            reply = reply[7:]
        if reply.endswith('```'):
            reply = reply[:-3]
        reply = reply.strip()

        # Parse JSON response
        try:
            structured_data = json.loads(reply)
            
            # Ensure all expected columns are present and clean up checkbox values
            final_data = {}
            for column in FORM_COLUMNS:
                value = structured_data.get(column, None)
                
                # Clean up checkbox values - remove any "✗" and ensure only "✓" or null
                if column in ['bedside_cabinets_floating', 'bedside_cabinets_fitted', 'bedside_cabinets_freestand',
                             'dresser_desk_yes', 'dresser_desk_no', 'internal_mirror_yes', 'internal_mirror_no',
                             'mirror_silver', 'mirror_bronze', 'mirror_grey', 'soffit_lights_spot', 'soffit_lights_strip',
                             'soffit_lights_cool_white', 'soffit_lights_warm_white', 'gable_lights_black', 'gable_lights_white',
                             'carpet_protection', 'floor_tile_protection', 'no_floor']:
                    if value == "✓":
                        final_data[column] = "✓"
                    else:
                        final_data[column] = None  # Convert anything else to null
                else:
                    final_data[column] = value
            
            # Store the latest structured data
            global latest_structured_data
            latest_structured_data = final_data
            
            return final_data
            
        except json.JSONDecodeError as e:
            print(f"JSON parsing error: {e}")
            print(f"Raw response: {reply}")
            return {
                "error": "Failed to parse JSON response",
                "raw_response": reply,
                "json_error": str(e)
            }
            
    except Exception as e:
        print(f"OpenAI API error: {str(e)}")
        return {
            "error": f"OpenAI API error: {str(e)}",
            "raw_text": raw_text[:500]  # Include first 500 chars for debugging
        }

def update_form_columns(new_columns):
    """
    Update the form columns list (useful for dynamic forms)
    
    Args:
        new_columns (list): List of new column names
    """
    global FORM_COLUMNS
    FORM_COLUMNS = new_columns

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
def upload_image():
    try:
        if 'image' not in request.files:
            return jsonify({'error': 'No file uploaded'}), 400

        file = request.files['image']
        
        if file.filename == '':
            return jsonify({'error': 'No file selected'}), 400
            
        if not allowed_file(file.filename):
            return jsonify({'error': 'Invalid file type. Please upload an image.'}), 400

        filename = secure_filename(file.filename)
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(file_path)

        # Step 1: Extract text using Google Vision API
        print(f"Processing file: {filename}")
        print("Extracting text from image...")
        extracted_text = extract_text_from_image(file_path)
        
        if not extracted_text:
            return jsonify({'success': False, 'error': 'No text found in the image'}), 400

        print(f"Extracted text length: {len(extracted_text)} characters")
        print(f"Extracted text preview: {extracted_text[:200]}...")  # Log first 200 chars

        # Step 2: Structure data using OpenAI API
        print("Structuring data with OpenAI...")
        structured_data = structure_data_with_openai(extracted_text)
        
        if 'error' in structured_data:
            return jsonify({
                'success': False, 
                'error': 'Failed to structure data', 
                'details': structured_data,
                'extracted_text': extracted_text
            }), 500

        # Step 3: Generate PDF from structured data
        print("Generating PDF...")
        pdf_filename = filename.rsplit('.', 1)[0] + '.pdf'
        pdf_path = generate_pdf(structured_data, pdf_filename)

        # Step 4: Generate Excel file
        print("Generating Excel file...")
        customer_name = structured_data.get('customer_name', 'Unknown')
        excel_path = export_to_excel(structured_data, customer_name)

        # Clean up uploaded image
        os.remove(file_path)

        return jsonify({
            'success': True,
            'extracted_text': extracted_text,
            'structured_data': structured_data,
            'pdf_download_url': f'/download/{os.path.basename(pdf_path)}',
            'excel_download_url': f'/download-excel/{os.path.basename(excel_path)}',
            'view_data_url': '/view-data'  # Add URL to view table
        })
        
    except Exception as e:
        print(f"Error processing upload: {str(e)}")
        return jsonify({'error': f'Processing failed: {str(e)}'}), 500

@app.route('/generate-pdf', methods=['POST'])
def generate_pdf_from_form():
    """
    Generate PDF from form data submitted directly
    """
    try:
        data = request.json.get('data', {})
        
        if not data:
            return jsonify({'success': False, 'error': 'No form data provided'}), 400

        # Generate filename
        customer_name = data.get('customer_name', 'Unknown')
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        if customer_name and customer_name != 'Unknown':
            clean_name = "".join(c for c in customer_name if c.isalnum() or c in (' ', '-', '_')).rstrip()
            clean_name = clean_name.replace(' ', '_')
            pdf_filename = f"{clean_name}_{timestamp}.pdf"
        else:
            pdf_filename = f"bedroom_form_{timestamp}.pdf"

        # Generate PDF
        print("Generating PDF from form data...")
        pdf_path = generate_pdf(data, pdf_filename)

        # Store the latest structured data
        global latest_structured_data
        latest_structured_data = data

        return jsonify({
            'success': True,
            'pdf_download_url': f'/download/{os.path.basename(pdf_path)}',
            'message': 'PDF generated successfully'
        })
        
    except Exception as e:
        print(f"Error generating PDF from form: {str(e)}")
        return jsonify({'success': False, 'error': f'PDF generation failed: {str(e)}'}), 500

@app.route('/generate-excel', methods=['POST'])
def generate_excel_from_form():
    """
    Generate Excel from form data submitted directly
    """
    try:
        data = request.json.get('data', {})
        
        if not data:
            return jsonify({'success': False, 'error': 'No form data provided'}), 400

        # Generate Excel file
        print("Generating Excel from form data...")
        customer_name = data.get('customer_name', 'Unknown')
        excel_path = export_to_excel(data, customer_name)

        return jsonify({
            'success': True,
            'excel_download_url': f'/download-excel/{os.path.basename(excel_path)}',
            'message': 'Excel file generated successfully'
        })
        
    except Exception as e:
        print(f"Error generating Excel from form: {str(e)}")
        return jsonify({'success': False, 'error': f'Excel generation failed: {str(e)}'}), 500

@app.route('/download/<filename>')
def download_file(filename):
    try:
        return send_file(f'generated_pdfs/{filename}', as_attachment=True)
    except FileNotFoundError:
        return jsonify({'success': False, 'error': 'File not found'}), 404
    except Exception as e:
        return jsonify({'success': False, 'error': f'Download failed: {str(e)}'}), 500

@app.route('/download-excel/<filename>')
def download_excel_file(filename):
    try:
        return send_file(f'generated_excel/{filename}', as_attachment=True)
    except FileNotFoundError:
        return jsonify({'success': False, 'error': 'Excel file not found'}), 404
    except Exception as e:
        return jsonify({'success': False, 'error': f'Download failed: {str(e)}'}), 500

@app.route('/view-data')
def view_data():
    """
    Render the latest structured data as a styled HTML table
    """
    global latest_structured_data
    if not latest_structured_data:
        return render_template('table.html', columns=FORM_COLUMNS, data=None, error="No data available. Please upload an image first.")
    
    return render_template('table.html', columns=FORM_COLUMNS, data=latest_structured_data, error=None)

if __name__ == '__main__':
    app.run(debug=True)