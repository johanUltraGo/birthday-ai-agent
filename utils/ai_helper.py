import google.generativeai as genai
import os
from dotenv import load_dotenv

load_dotenv()

genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

def generate_birthday_quote(student_name):
    """
    Generates a creative and personalized birthday wish using Gemini AI.
    """
    model = genai.GenerativeModel('gemini-1.5-flash')
    prompt = (
        f"Write a unique, inspiring, and heartwarming birthday wish for a student named {student_name}. "
        "The wish should be short (max 25 words), mention 'growth' or 'future', and be suitable for a school poster. "
        "Do not use quotes around the message."
    )
    
    try:
        response = model.generate_content(prompt)
        return response.text.strip()
    except Exception as e:
        print(f"Error generating quote: {e}")
        return f"Happy Birthday, {student_name}! May your day be filled with joy and your future with bright success!"
