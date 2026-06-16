import google.generativeai as genai
import os
from dotenv import load_dotenv

load_dotenv()

genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

def generate_birthday_quote(student_name):
    """
    Generates a personalized birthday quote for a student using Gemini AI.
    """
    model = genai.GenerativeModel('gemini-1.5-flash')
    prompt = f"Write a short, inspiring, and happy birthday wish for a student named {student_name}. Keep it under 20 words and suitable for a school environment."
    
    try:
        response = model.generate_content(prompt)
        return response.text.strip()
    except Exception as e:
        print(f"Error generating quote: {e}")
        return f"Happy Birthday, {student_name}! Have a wonderful day full of joy and learning!"
