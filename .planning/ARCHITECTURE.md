# 🏗️ Technical Architecture

## 🧬 System Overview
The application follows a standard **MVC (Model-View-Controller)** pattern using the Flask framework.

## 🛰️ Component Diagram
1.  **Frontend (View):** Jinja2 templates styled with Bootstrap 5. Handles user interactions and data presentation.
2.  **Backend (Controller):** Flask application logic (`app.py`). Manages routing, business logic (detection), and AI orchestration.
3.  **Database (Model):** SQLite database managed via SQLAlchemy. Stores Student and Notification records.
4.  **AI Engine:** Google Gemini API wrapper for natural language generation.
5.  **Image Engine:** Pillow-based processing unit for dynamic poster creation.

## 🔐 Security & Configuration
*   **Environment Variables:** Managed via `.env` for sensitive keys (Gemini API Key, Flask Secret Key).
*   **Static Assets:** Organized into `uploads/` for student photos and `posters/` for generated media.

## 🔄 Data Flow
1.  **Input:** User submits student data via HTTP POST.
2.  **Storage:** SQLAlchemy persists data to `birthdays.db`.
3.  **Trigger:** Dashboard requests today's birthdays.
4.  **Processing:** 
    *   System fetches data.
    *   Calls `ai_helper.py` for a quote.
    *   Calls `image_helper.py` to bake the PNG poster.
5.  **Output:** Poster is rendered in the browser and saved for sharing.
