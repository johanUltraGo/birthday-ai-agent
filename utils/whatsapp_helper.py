import os
from twilio.rest import Client
from dotenv import load_dotenv

load_dotenv()

def send_whatsapp_poster(parent_phone, student_name, poster_url):
    """
    Sends a birthday poster via Twilio WhatsApp API.
    Returns: (success_boolean, message_string)
    """
    account_sid = os.getenv("TWILIO_ACCOUNT_SID")
    auth_token = os.getenv("TWILIO_AUTH_TOKEN")
    from_number = os.getenv("TWILIO_WHATSAPP_FROM") # e.g. 'whatsapp:+14155238886'

    if not account_sid or not auth_token or not from_number:
        return False, "Twilio credentials are not fully configured in environment variables."

    # Standardize phone number format
    to_number = parent_phone.strip()
    if not to_number.startswith("whatsapp:"):
        # If it doesn't start with whatsapp:, we prepend it.
        # Ensure it has a '+' and country code. E.g. '+1234567890'
        if not to_number.startswith("+"):
            # Assume a default format or just add it.
            to_number = "+" + to_number
        to_number = f"whatsapp:{to_number}"

    try:
        client = Client(account_sid, auth_token)
        
        # Prepare the message text
        body_text = f"🌟 Happy Birthday, {student_name}! 🎂 Here is your special birthday poster from the school! 🎉"
        
        # Twilio WhatsApp allows sending media. If poster_url is a relative or local URL,
        # Twilio's servers won't be able to fetch it.
        # We check if it is a public URL.
        media_url = None
        if poster_url.startswith("http://") or poster_url.startswith("https://"):
            # If it's a localhost, Twilio can't access it, so we append the URL in text instead of media
            if "localhost" in poster_url or "127.0.0.1" in poster_url:
                body_text += f"\nView Poster: {poster_url}"
            else:
                media_url = [poster_url]
        else:
            body_text += f"\nView Poster: {poster_url}"

        message = client.messages.create(
            body=body_text,
            from_=from_number,
            to=to_number,
            media_url=media_url
        )
        return True, f"Message sent successfully. SID: {message.sid}"
    except Exception as e:
        return False, f"Twilio Error: {str(e)}"
