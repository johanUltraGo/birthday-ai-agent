from PIL import Image, ImageDraw, ImageFont
import os
def create_birthday_poster(student_name, student_class, quote, student_photo_path=None, output_path="static/posters/"):
    """
    Creates a professionally styled birthday poster using Pillow.
    """
    if not os.path.exists(output_path):
        os.makedirs(output_path)

    # Poster dimensions (A4-ish ratio)
    width, height = 800, 1100

    # Gradient-like background (Light Blue to White)
    poster = Image.new('RGB', (width, height), color=(240, 248, 255))
    draw = ImageDraw.Draw(poster)

    # Add a stylish border
    border_color = (0, 102, 204) # Deep Blue
    draw.rectangle([15, 15, width-15, height-15], outline=border_color, width=15)
    draw.rectangle([35, 35, width-35, height-35], outline=border_color, width=2)

    # Load and process Student Photo
    if student_photo_path and os.path.exists(student_photo_path):
        student_img = Image.open(student_photo_path)
        # Force square crop for a modern look
        img_w, img_h = student_img.size
        min_dim = min(img_w, img_h)
        student_img = student_img.crop(((img_w - min_dim) // 2, (img_h - min_dim) // 2, (img_w + min_dim) // 2, (img_h + min_dim) // 2))
        student_img.thumbnail((450, 450))

        # Center the photo
        photo_x = (width - student_img.width) // 2
        poster.paste(student_img, (photo_x, 120))
    else:
        # Placeholder circle/rect if no photo
        draw.rectangle([200, 120, 600, 520], fill=(220, 220, 220), outline=border_color, width=2)
        draw.text((width//2, 320), "Student Photo", fill=(100, 100, 100), anchor="mm")

    # Typography (Falling back to default if fonts missing, but designed for center alignment)
    try:
        # You might need to adjust paths for Linux/Windows fonts
        font_h1 = ImageFont.truetype("arialbd.ttf", 70) # Bold
        font_name = ImageFont.truetype("arial.ttf", 55)
        font_class = ImageFont.truetype("arial.ttf", 35)
        font_quote = ImageFont.truetype("ariali.ttf", 32) # Italic
    except:
        font_h1 = font_name = font_class = font_quote = ImageFont.load_default()

    # Draw Text
    draw.text((width//2, 630), "HAPPY BIRTHDAY!", fill=border_color, font=font_h1, anchor="mm")
    draw.text((width//2, 720), student_name.upper(), fill=(0, 0, 0), font=font_name, anchor="mm")
    draw.text((width//2, 780), f"Grade: {student_class}", fill=(80, 80, 80), font=font_class, anchor="mm")

    # Wrap Quote text
    import textwrap
    lines = textwrap.wrap(quote, width=40)
    y_text = 880
    for line in lines:
        draw.text((width//2, y_text), line, fill=(50, 50, 50), font=font_quote, anchor="mm")
        y_text += 40

    # Add a small school footer or star icons
    draw.text((width//2, 1040), "✨ Celebrating Excellence & Growth ✨", fill=border_color, anchor="mm")

    final_path = os.path.join(output_path, f"{student_name.replace(' ', '_')}_poster.png")
    poster.save(final_path)
    return final_path

