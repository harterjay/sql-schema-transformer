#!/usr/bin/env python3
"""
Script to remove background from riptonic_grey.png
"""

from rembg import remove
from PIL import Image
import os

def remove_background(input_path, output_path):
    """
    Remove background from an image using rembg
    
    Args:
        input_path (str): Path to input image
        output_path (str): Path to save output image
    """
    try:
        # Read the input image
        input_image = Image.open(input_path)
        
        # Remove background
        output_image = remove(input_image)
        
        # Save the result
        output_image.save(output_path)
        
        print(f"Background removed successfully!")
        print(f"Input: {input_path}")
        print(f"Output: {output_path}")
        
    except Exception as e:
        print(f"Error removing background: {e}")

if __name__ == "__main__":
    input_file = "riptonic_grey.png"
    output_file = "riptonic_grey_no_bg.png"
    
    if os.path.exists(input_file):
        remove_background(input_file, output_file)
    else:
        print(f"Input file '{input_file}' not found!") 