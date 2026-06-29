import google.generativeai as genai
import os
from dotenv import load_dotenv
from utils.birthday_data import build_ai_context_prompt

load_dotenv()

genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

def generate_birthday_quote(student_name, student_context=None):
    """
    Generates a creative and personalized birthday wish using Gemini AI.
    """
    model = genai.GenerativeModel('gemini-1.5-flash')
    context_prompt = build_ai_context_prompt(student_context)
    prompt = (
        f"{context_prompt}"
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

def generate_custom_birthday_wish(name, relationship, style, student_context=None):
    """
    Generates a customized birthday wish using Gemini AI.
    """
    model = genai.GenerativeModel('gemini-1.5-flash')
    
    style_guidelines = {
        'Emotional': 'heartwarming, sincere, emotional, and warm',
        'Funny': 'funny, humorous, lighthearted, and witty',
        'Professional': 'professional, polite, encouraging, and respectful',
        'Short': 'very short, punchy, concise, and modern'
    }
    
    selected_guideline = style_guidelines.get(style, 'heartwarming and sincere')
    context_prompt = build_ai_context_prompt(student_context)
    
    prompt = (
        f"{context_prompt}"
        f"Write a birthday wish for my {relationship} named {name}. "
        f"The style of the message must be {selected_guideline}. "
        "Keep the wish short (under 40 words). Do not include any quotes around the message."
    )
    
    try:
        response = model.generate_content(prompt)
        return response.text.strip()
    except Exception as e:
        print(f"Error generating custom wish: {e}")
        # Return a fallback message
        fallback_templates = {
            'Funny': f"Happy Birthday, {name}! Another year older, but let's not count the candles just yet. Have a blast!",
            'Professional': f"Happy Birthday, {name}. Wishing you continued success and a wonderful year ahead in your career and growth.",
            'Short': f"Happy Birthday, {name}! Have an amazing day ahead! 🎉",
            'Emotional': f"Dearest {name}, wishing you the happiest of birthdays. May this year bring you closer to all your dreams and fill your heart with joy."
        }
        return fallback_templates.get(style, f"Happy Birthday, {name}! Wishing you all the very best on your special day.")

