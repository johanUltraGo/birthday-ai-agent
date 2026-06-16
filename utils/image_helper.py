from PIL import Image, ImageDraw, ImageFont
import os

def create_birthday_poster(student_name, student_class, quote, student_photo_path=None, output_path="static/posters/"):
    """
    Creates a birthday poster using Pillow.
    """
    if not os.path.exists(output_path):
        os.makedirs(output_path)

    # Poster dimensions
    width, height = 800, 1000
    background_color = (255, 255, 255)  # White background
    
    # Create background
    poster = Image.new('RGB', (width, height), color=background_color)
    draw = ImageDraw.Draw(poster)
    
    # Add some decorative elements (placeholder for complex design)
    draw.rectangle([20, 20, width-20, height-20], outline=(0, 123, 255), width=10)
    
    # Load Student Photo
    if student_photo_path and os.path.exists(student_photo_path):
        student_img = Image.open(student_photo_path)
        # Resize student image
        student_img.thumbnail((400, 400))
        poster.paste(student_img, (200, 100))
    else:
        # Placeholder for photo
        draw.rectangle([200, 100, 600, 500], fill=(230, 230, 230))
        draw.text((320, 280), "No Photo", fill=(100, 100, 100))

    # Add Text (Using default font for now as custom fonts might not be available)
    # In a real app, you would load a nice .ttf font
    try:
        font_title = ImageFont.truetype("arial.ttf", 60)
        font_text = ImageFont.truetype("arial.ttf", 30)
    except:
        font_title = ImageFont.load_default()
        font_text = ImageFont.load_default()

    draw.text((width//2, 550), f"HAPPY BIRTHDAY", fill=(0, 123, 255), anchor="mm")
    draw.text((width//2, 630), student_name, fill=(0, 0, 0), anchor="mm")
    draw.text((width//2, 680), f"Class: {student_class}", fill=(100, 100, 100), anchor="mm")
    
    # Wrap and draw quote
    draw.text((width//2, 800), quote, fill=(50, 50, 50), anchor="mm")

    final_path = os.path.join(output_path, f"{student_name.replace(' ', '_')}_poster.png")
    poster.save(final_path)
    return final_path
