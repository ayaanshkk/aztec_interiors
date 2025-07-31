import os
from google.cloud import vision
import io

def extract_text_from_image(image_path):
    """
    Extract text from an image using Google Cloud Vision API
    
    Args:
        image_path (str): Path to the image file
        
    Returns:
        str: Extracted text from the image
    """
    try:
        # Initialize the Vision API client
        client = vision.ImageAnnotatorClient()
        
        # Read the image file
        with io.open(image_path, 'rb') as image_file:
            content = image_file.read()
        
        # Create image object
        image = vision.Image(content=content)
        
        # Perform text detection
        response = client.text_detection(image=image)
        
        # Check for errors
        if response.error.message:
            raise Exception(f'Vision API error: {response.error.message}')
        
        # Extract text annotations
        texts = response.text_annotations
        
        if texts:
            # Return the full text description (first annotation contains all text)
            return texts[0].description
        else:
            return ""
            
    except Exception as e:
        print(f"Error in text extraction: {str(e)}")
        raise e