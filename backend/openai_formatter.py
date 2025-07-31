import os
import json
from openai import OpenAI
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Initialize OpenAI client
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# Define your form columns here - customized for bedroom forms
FORM_COLUMNS = [
    "customer_name",
    "address", 
    "room",
    "tel_mob_number",
    "fitting_style",
    "door_style",
    "door_colour",
    "end_panel_colour",
    "plinth_filler_colour",
    "worktop_colour",
    "cabinet_colour",
    "handles",
    "survey_date",
    "appt_date",
    "pro_inst_date",
    "comp_chk_date",
    "date_deposit_paid",
    "bedside_cabinets_qty",
    "bedside_cabinets_type",  # floating/fitted/freestand
    "dresser_desk",  # yes/no
    "dresser_desk_qty_size",
    "internal_mirror",  # yes/no
    "internal_mirror_qty_size",
    "mirror_colour",  # silver/bronze/grey
    "mirror_qty",
    "soffit_lights_type",  # spot/strip
    "soffit_lights_colour",  # cool white/warm white
    "soffit_lights_qty",
    "gable_lights_profile_colour",  # black/white
    "gable_lights_qty",
    "carpet_protection",
    "floor_tile_protection", 
    "other_misc_accessories",
    "customer_signature",
    "signature_date"
]

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
        You are tasked with extracting information from a kitchen form and organizing it into specific categories.
        
        Extract and categorize the following text into a JSON format using ONLY these column names:
        {column_list}
        
        Rules:
        1. Only use the exact column names provided above
        2. If information for a column is not found, set it to null
        3. Extract the most relevant information for each column
        4. Ensure the output is valid JSON
        5. Do not add any additional fields beyond the specified columns
        
        Raw text from form:
        {raw_text}
        
        Return only the JSON object, no additional text or formatting.
        """

        # Make API call to OpenAI
        print("Sending request to OpenAI...")
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {
                    "role": "system", 
                    "content": "You are a data extraction expert. Return only valid JSON with the requested structure."
                },
                {
                    "role": "user", 
                    "content": prompt
                }
            ],
            temperature=0.3,
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
            
            # Ensure all expected columns are present
            final_data = {}
            for column in FORM_COLUMNS:
                final_data[column] = structured_data.get(column, None)
            
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