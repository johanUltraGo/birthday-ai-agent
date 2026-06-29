import os
import csv
import json
import click
from io import TextIOWrapper
from datetime import datetime
from functools import wraps
from sqlalchemy import inspect, text
from flask import Flask, render_template, request, redirect, url_for, flash, session, send_from_directory
from models import db, Student, Notification, User, GeneratedWish
from flask_mail import Mail, Message
from dotenv import load_dotenv
from utils.ai_helper import generate_birthday_quote, generate_custom_birthday_wish
from utils.image_helper import create_birthday_poster
from utils.whatsapp_helper import send_whatsapp_poster
from utils.sheets_helper import student_sheet_store
from utils.birthday_data import (
    build_ai_context,
    export_students_json,
    fetch_students_from_sheet,
    get_today_birthdays,
    get_upcoming_birthdays,
    lookup_student_by_name,
)

load_dotenv()

app = Flask(__name__)

# Persistent Data Configuration
# On Render, we'll mount a disk to /data
DATA_DIR = os.getenv('DATA_DIR', os.path.join(os.getcwd(), 'data'))
UPLOAD_FOLDER = os.path.join(DATA_DIR, 'uploads')
POSTER_FOLDER = os.path.join(DATA_DIR, 'posters')

# Ensure directories exist
for folder in [UPLOAD_FOLDER, POSTER_FOLDER]:
    if not os.path.exists(folder):
        os.makedirs(folder)

db_url = os.getenv('DATABASE_URL')
if db_url and db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = db_url or f'sqlite:///{os.path.join(DATA_DIR, "birthdays.db")}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev-secret-key')
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['POSTER_FOLDER'] = POSTER_FOLDER

# Mail Configuration
app.config['MAIL_SERVER'] = os.getenv('MAIL_SERVER', 'smtp.gmail.com')
app.config['MAIL_PORT'] = int(os.getenv('MAIL_PORT', 587))
app.config['MAIL_USE_TLS'] = os.getenv('MAIL_USE_TLS', 'True').lower() == 'true'
app.config['MAIL_USERNAME'] = os.getenv('MAIL_USERNAME')
app.config['MAIL_PASSWORD'] = os.getenv('MAIL_PASSWORD')
app.config['MAIL_DEFAULT_SENDER'] = os.getenv('MAIL_DEFAULT_SENDER', app.config['MAIL_USERNAME'])

mail = Mail(app)

db.init_app(app)

# Custom filter for template
@app.template_filter('basename')
def basename_filter(path):
    return os.path.basename(path)

def sync_students_from_sheet():
    if not student_sheet_store.is_configured():
        exported_students = [serialize_student(student) for student in Student.query.order_by(Student.id.asc()).all()]
        export_students_json(exported_students)
        return {"synced": False, "count": len(exported_students), "source": "local"}

    try:
        sheet_students = student_sheet_store.list_students()
        db.session.query(Student).delete()
        for sheet_student in sheet_students:
            db.session.add(Student(**build_student_kwargs({
                "name": sheet_student.name,
                "student_class": sheet_student.student_class,
                "birthday": sheet_student.birthday,
                "father_name": sheet_student.father_name,
                "contact_number_1": sheet_student.contact_number_1,
                "contact_number_2": sheet_student.contact_number_2,
                "corrections": sheet_student.corrections,
                "parent_phone": sheet_student.parent_phone,
                "photo_path": sheet_student.photo_path,
                "created_at": sheet_student.created_at,
            }, student_id=sheet_student.id)))
        db.session.commit()

        exported_students = [serialize_student(student) for student in Student.query.order_by(Student.id.asc()).all()]
        export_students_json(exported_students)
        return {"synced": True, "count": len(exported_students), "source": "google_sheets"}
    except Exception as exc:
        db.session.rollback()
        print(f"Sheets sync skipped: {exc}")
        return {"synced": False, "count": Student.query.count(), "source": "local", "error": str(exc)}


def agent_api_authorized():
    token = request.args.get("token") or request.headers.get("X-Agent-Token")
    configured_token = os.getenv("AGENT_API_TOKEN", "").strip()
    if configured_token and token == configured_token:
        return True
    return "user_id" in session


def serialize_student(student):
    return {
        "id": student.id,
        "name": student.name,
        "student_class": student.student_class,
        "birthday": student.birthday.isoformat() if student.birthday else None,
        "father_name": student.father_name,
        "contact_number_1": student.contact_number_1,
        "contact_number_2": student.contact_number_2,
        "corrections": student.corrections,
        "parent_phone": student.parent_phone,
        "photo_path": student.photo_path,
        "created_at": student.created_at.isoformat() if student.created_at else None,
    }


def build_student_kwargs(student_data, student_id=None):
    birthday_value = student_data["birthday"]
    if isinstance(birthday_value, str):
        for fmt in ('%Y-%m-%d', '%d.%m.%Y', '%d/%m/%Y'):
            try:
                birthday_value = datetime.strptime(birthday_value, fmt).date()
                break
            except ValueError:
                continue
        if isinstance(birthday_value, str):
            birthday_value = datetime.utcnow().date()

    created_at_value = student_data.get("created_at")
    if isinstance(created_at_value, str):
        try:
            created_at_value = datetime.strptime(created_at_value, '%Y-%m-%d %H:%M:%S')
        except ValueError:
            created_at_value = None

    kwargs = {
        "name": student_data["name"],
        "student_class": student_data.get("student_class") or student_data.get("class") or "N/A",
        "birthday": birthday_value,
        "father_name": student_data.get("father_name"),
        "contact_number_1": student_data.get("contact_number_1"),
        "contact_number_2": student_data.get("contact_number_2"),
        "corrections": student_data.get("corrections"),
        "parent_phone": student_data.get("parent_phone") or student_data.get("contact_number_1"),
        "photo_path": student_data.get("photo_path"),
    }
    if created_at_value:
        kwargs["created_at"] = created_at_value
    if student_id is not None:
        kwargs["id"] = student_id
    return kwargs

with app.app_context():
    db.create_all()
    inspector = inspect(db.engine)
    if 'student' in inspector.get_table_names():
        student_columns = {column['name'] for column in inspector.get_columns('student')}
        column_alters = [
            ('father_name', 'ALTER TABLE student ADD COLUMN father_name VARCHAR(120)'),
            ('contact_number_1', 'ALTER TABLE student ADD COLUMN contact_number_1 VARCHAR(30)'),
            ('contact_number_2', 'ALTER TABLE student ADD COLUMN contact_number_2 VARCHAR(30)'),
            ('corrections', 'ALTER TABLE student ADD COLUMN corrections TEXT'),
            ('parent_phone', 'ALTER TABLE student ADD COLUMN parent_phone VARCHAR(30)'),
        ]
        altered = False
        for column_name, alter_sql in column_alters:
            if column_name not in student_columns:
                db.session.execute(text(alter_sql))
                altered = True
        if altered:
            db.session.commit()

    sync_students_from_sheet()

    # Auto-seed initial administrator user if none exists
    if User.query.count() == 0:
        admin_user = User(username='admin', role='Admin', password_hash='')
        db.session.add(admin_user)
        db.session.commit()

# --- Decorators ---
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please log in to access this page.', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def role_required(roles):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if 'user_id' not in session:
                flash('Please log in to access this page.', 'warning')
                return redirect(url_for('login'))
            if session.get('role') not in roles:
                flash('You do not have permission to access this page.', 'danger')
                return redirect(url_for('index'))
            return f(*args, **kwargs)
        return decorated_function
    return decorator

# --- Static File Serving ---
@app.route('/media/uploads/<filename>')
def serve_upload(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@app.route('/media/posters/<filename>')
def serve_poster(filename):
    return send_from_directory(app.config['POSTER_FOLDER'], filename)

# --- Authentication Routes ---
@app.route('/login', methods=['GET', 'POST'])
def login():
    is_initial = User.query.count() == 1 and User.query.first().username == 'admin'
    
    if 'user_id' in session:
        return redirect(url_for('index'))
        
    if request.method == 'POST':
        username = request.form.get('username')
    
        user = User.query.filter_by(username=username).first()
        if user:
            session['user_id'] = user.id
            session['username'] = user.username
            session['role'] = user.role
            flash(f'Welcome back, {user.username}! Logged in as {user.role}.', 'success')
            return redirect(url_for('index'))
        else:
            flash('Invalid username.', 'danger')
            return redirect(url_for('login'))
            
    return render_template('login.html', is_initial=is_initial)

@app.route('/logout')
def logout():
    session.clear()
    flash('Logged out successfully.', 'success')
    return redirect(url_for('login'))

@app.route('/register_user', methods=['GET', 'POST'])
@login_required
@role_required(['Admin'])
def register_user():
    users = User.query.all()
    if request.method == 'POST':
        username = request.form.get('username')
        role = request.form.get('role')
        
        if not username or not role:
            flash('All fields are required!', 'danger')
            return redirect(url_for('register_user'))
            
        existing_user = User.query.filter_by(username=username).first()
        if existing_user:
            flash('Username already exists!', 'danger')
            return redirect(url_for('register_user'))

        new_user = User(username=username, role=role, password_hash='')
        db.session.add(new_user)
        db.session.commit()
        
        # Log notification
        new_notif = Notification(message=f"Registered user: {username} ({role})", status="Completed")
        db.session.add(new_notif)
        db.session.commit()
        
        flash(f'User {username} successfully registered with role {role}!', 'success')
        return redirect(url_for('register_user'))
        
    return render_template('register_user.html', users=users)

@app.route('/delete_user/<int:user_id>', methods=['POST'])
@login_required
@role_required(['Admin'])
def delete_user(user_id):
    user = User.query.get_or_404(user_id)
    if session.get('user_id') == user.id:
        flash('You cannot delete your own account!', 'danger')
        return redirect(url_for('register_user'))
        
    username = user.username
    db.session.delete(user)
    db.session.commit()
    
    # Log notification
    new_notif = Notification(message=f"Deleted user account: {username}", status="Completed")
    db.session.add(new_notif)
    db.session.commit()
    
    flash(f'User {username} successfully deleted!', 'success')
    return redirect(url_for('register_user'))

# --- Core Business Logic Routes ---
@app.route('/')
@login_required
def index():
    sync_students_from_sheet()
    students = Student.query.all()
    today = datetime.now().date()
    
    # Simple birthday detection
    birthdays_today = [s for s in students if s.birthday.month == today.month and s.birthday.day == today.day]
    
    # Upcoming birthdays (next 7 days)
    upcoming_birthdays = []
    for s in students:
        try:
            bday_this_year = datetime(today.year, s.birthday.month, s.birthday.day).date()
        except ValueError: # Leap year case (Feb 29)
            bday_this_year = datetime(today.year, 3, 1).date()
            
        if bday_this_year > today:
            diff = (bday_this_year - today).days
            if 0 < diff <= 7:
                upcoming_birthdays.append(s)
        elif bday_this_year < today:
            # Check for next year if it's already passed this year (for end of year cases)
            try:
                bday_next_year = datetime(today.year + 1, s.birthday.month, s.birthday.day).date()
                diff = (bday_next_year - today).days
                if 0 < diff <= 7:
                    upcoming_birthdays.append(s)
            except ValueError:
                pass

    notifications = Notification.query.order_by(Notification.timestamp.desc()).limit(5).all()
    
    # AI generated messages
    generated_wishes = GeneratedWish.query.order_by(GeneratedWish.timestamp.desc()).limit(10).all()
    generated_wishes_count = GeneratedWish.query.count()

    return render_template('dashboard.html', 
                           students=students, 
                           birthdays_today=birthdays_today, 
                           upcoming_birthdays=upcoming_birthdays,
                           notifications=notifications,
                           generated_wishes=generated_wishes,
                           generated_wishes_count=generated_wishes_count,
                           today=today)

@app.cli.command("sync-sheet")
def sync_sheet_command():
    """Sync Google Sheets data into the local database."""
    result = sync_students_from_sheet()
    print(f"Synced {result['count']} students from {result['source']}.")


@app.cli.command("export-students")
def export_students_command():
    """Print the synced student registry as JSON for agent use."""
    result = sync_students_from_sheet()
    students = Student.query.order_by(Student.id.asc()).all()
    payload = {
        "synced": result.get("synced", False),
        "source": result.get("source", "local"),
        "count": len(students),
        "students": [serialize_student(student) for student in students],
    }
    print(json.dumps(payload, indent=2))


@app.cli.command("import-roster")
@click.argument("path")
@click.option("--wipe/--no-wipe", default=True, help="Replace existing student rows before importing.")
def import_roster_command(path, wipe):
    """Import a roster text/CSV export into the local database."""
    if not os.path.isfile(path):
        raise click.ClickException(f"File not found: {path}")

    ext = os.path.splitext(path)[1].lower()
    imported = 0

    if wipe:
        db.session.query(Student).delete()
        db.session.commit()

    if ext == ".csv":
        with open(path, "r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                name = (row.get("name") or row.get("students name") or row.get("student name") or "").strip()
                student_class = (row.get("class") or row.get("student_class") or row.get("grade") or "N/A").strip() or "N/A"
                birthday = (row.get("birthday") or row.get("dob") or row.get("date of birth") or "").strip()
                if not name or not birthday:
                    continue
                student = Student(**build_student_kwargs({
                    "name": name,
                    "student_class": student_class,
                    "birthday": birthday,
                    "father_name": (row.get("father_name") or row.get("fathers name") or row.get("father name")),
                    "contact_number_1": (row.get("contact_number_1") or row.get("contact number 1") or row.get("contact number1")),
                    "contact_number_2": (row.get("contact_number_2") or row.get("contact number 2") or row.get("contact number2")),
                    "corrections": row.get("corrections"),
                    "parent_phone": (row.get("parent_phone") or row.get("parent phone") or row.get("parent whatsapp number")),
                    "photo_path": None,
                }))
                db.session.add(student)
                imported += 1
    else:
        with open(path, "r", encoding="utf-8") as handle:
            lines = [line.strip() for line in handle if line.strip()]

        skip_tokens = {
            "s.no",
            "s no",
            "students name",
            "student name",
            "dob",
            "date of birth",
            "fathers name",
            "father name",
            "contact number 1",
            "contact number1",
            "contact number 2",
            "contact number2",
            "corrections",
        }

        records = []
        current = None
        for line in lines:
            normalized = line.strip().lower()
            if normalized in skip_tokens:
                continue
            if normalized.isdigit():
                if current:
                    records.append(current)
                current = {"id": int(normalized), "values": []}
                continue
            if current is None:
                continue
            current["values"].append(line)

        if current:
            records.append(current)

        for record in records:
            values = record["values"]
            if len(values) < 2:
                continue
            name = values[0]
            birthday = values[1]
            father_name = values[2] if len(values) > 2 else None
            contact_number_1 = values[3] if len(values) > 3 else None
            contact_number_2 = values[4] if len(values) > 4 else None
            corrections = values[5] if len(values) > 5 else None

            student = Student(**build_student_kwargs({
                "name": name,
                "student_class": "N/A",
                "birthday": birthday,
                "father_name": father_name,
                "contact_number_1": contact_number_1,
                "contact_number_2": contact_number_2,
                "corrections": corrections,
                "parent_phone": contact_number_1,
                "photo_path": None,
            }, student_id=record["id"]))
            db.session.add(student)
            imported += 1

    db.session.commit()
    print(f"Imported {imported} student records.")

@app.route('/api/generate_wish', methods=['POST'])
@login_required
def api_generate_wish():
    data = request.get_json() or {}
    name = data.get('name', '').strip()
    relationship = data.get('relationship', 'Student').strip()
    style = data.get('style', 'Emotional').strip()

    if not name:
        return {"success": False, "error": "Name is required"}, 400

    sheet_students = fetch_students_from_sheet()
    matched_student = lookup_student_by_name(name, sheet_students)
    if not matched_student:
        db_student = Student.query.filter(Student.name.ilike(name)).first()
        if db_student:
            matched_student = serialize_student(db_student)

    student_context = build_ai_context(matched_student)
    wish_text = generate_custom_birthday_wish(name, relationship, style, student_context)
    
    new_wish = GeneratedWish(
        recipient_name=name,
        relationship=relationship,
        style=style,
        wish_text=wish_text
    )
    db.session.add(new_wish)
    
    new_notif = Notification(
        message=f"AI birthday wish generated for {name} ({relationship})",
        status="Completed"
    )
    db.session.add(new_notif)
    db.session.commit()

    return {
        "success": True,
        "wish": wish_text,
        "recipient_name": name,
        "relationship": relationship,
        "style": style,
        "student_context": student_context,
        "timestamp": new_wish.timestamp.strftime('%d %b %H:%M')
    }

@app.route('/api/students', methods=['GET'])
def api_students():
    if not agent_api_authorized():
        return {"success": False, "error": "Unauthorized"}, 401

    sync_result = sync_students_from_sheet()
    students = [serialize_student(student) for student in Student.query.order_by(Student.id.asc()).all()]
    return {
        "success": True,
        "sync": sync_result,
        "count": len(students),
        "students": students,
    }


@app.route('/api/birthdays/today', methods=['GET'])
def api_birthdays_today():
    if not agent_api_authorized():
        return {"success": False, "error": "Unauthorized"}, 401

    sync_students_from_sheet()
    students = [serialize_student(student) for student in Student.query.all()]
    today = datetime.now().date()
    birthdays_today = get_today_birthdays(students, today)
    return {
        "success": True,
        "date": today.isoformat(),
        "count": len(birthdays_today),
        "birthdays_today": birthdays_today,
    }


@app.route('/api/birthdays/upcoming', methods=['GET'])
def api_birthdays_upcoming():
    if not agent_api_authorized():
        return {"success": False, "error": "Unauthorized"}, 401

    days = request.args.get("days", 7, type=int)
    sync_students_from_sheet()
    students = [serialize_student(student) for student in Student.query.all()]
    today = datetime.now().date()
    upcoming = get_upcoming_birthdays(students, days=days, today=today)
    return {
        "success": True,
        "date": today.isoformat(),
        "days": days,
        "count": len(upcoming),
        "upcoming_birthdays": upcoming,
    }


@app.route('/api/sync-sheet', methods=['POST'])
def api_sync_sheet():
    if not agent_api_authorized():
        return {"success": False, "error": "Unauthorized"}, 401

    result = sync_students_from_sheet()
    return {"success": True, **result}

@app.route('/add', methods=['GET', 'POST'])
@login_required
@role_required(['Admin', 'Teacher', 'Office'])
def add_student():
    if request.method == 'POST':
        name = request.form.get('name')
        student_class = request.form.get('class')
        birthday_str = request.form.get('birthday')
        father_name = request.form.get('father_name', '').strip() or None
        contact_number_1 = request.form.get('contact_number_1', '').strip() or None
        contact_number_2 = request.form.get('contact_number_2', '').strip() or None
        corrections = request.form.get('corrections', '').strip() or None
        parent_phone = request.form.get('parent_phone', '').strip() or None
        photo = request.files.get('photo')

        if not name or not student_class or not birthday_str:
            flash('All fields are required!', 'danger')
            return redirect(url_for('add_student'))

        try:
            birthday = datetime.strptime(birthday_str, '%Y-%m-%d').date()
            
            photo_path = None
            if photo:
                filename = f"{datetime.now().timestamp()}_{photo.filename}"
                photo_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                photo.save(photo_path)

            if student_sheet_store.is_configured():
                try:
                    student_sheet_store.add_student({
                        "name": name,
                        "student_class": student_class,
                        "birthday": birthday.strftime('%Y-%m-%d'),
                        "father_name": father_name,
                        "contact_number_1": contact_number_1,
                        "contact_number_2": contact_number_2,
                        "corrections": corrections,
                        "parent_phone": parent_phone,
                        "photo_path": photo_path,
                        "created_at": datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S'),
                    })
                    sync_students_from_sheet()
                except Exception as exc:
                    print(f"Sheets add failed, using local DB: {exc}")
                    new_student = Student(**build_student_kwargs({
                        "name": name,
                        "student_class": student_class,
                        "birthday": birthday,
                        "father_name": father_name,
                        "contact_number_1": contact_number_1,
                        "contact_number_2": contact_number_2,
                        "corrections": corrections,
                        "parent_phone": parent_phone,
                        "photo_path": photo_path,
                    }))
                    db.session.add(new_student)
                    db.session.commit()
            else:
                new_student = Student(**build_student_kwargs({
                    "name": name,
                    "student_class": student_class,
                    "birthday": birthday,
                    "father_name": father_name,
                    "contact_number_1": contact_number_1,
                    "contact_number_2": contact_number_2,
                    "corrections": corrections,
                    "parent_phone": parent_phone,
                    "photo_path": photo_path,
                }))
                db.session.add(new_student)
                db.session.commit()
            
            # Log notification
            new_notif = Notification(message=f"Added student registry: {name}", status="Completed")
            db.session.add(new_notif)
            db.session.commit()
            
            flash('Student added successfully!', 'success')
            return redirect(url_for('index'))
        except Exception as e:
            flash(f'Error: {str(e)}', 'danger')
            return redirect(url_for('add_student'))

    return render_template('add_student.html')

@app.route('/edit/<int:student_id>', methods=['GET', 'POST'])
@login_required
@role_required(['Admin', 'Teacher', 'Office'])
def edit_student(student_id):
    sync_students_from_sheet()
    student = Student.query.get_or_404(student_id)
    if request.method == 'POST':
        name = request.form.get('name')
        student_class = request.form.get('class')
        birthday_str = request.form.get('birthday')
        father_name = request.form.get('father_name', '').strip() or None
        contact_number_1 = request.form.get('contact_number_1', '').strip() or None
        contact_number_2 = request.form.get('contact_number_2', '').strip() or None
        corrections = request.form.get('corrections', '').strip() or None
        parent_phone = request.form.get('parent_phone', '').strip() or None
        photo = request.files.get('photo')
        
        if not name or not student_class or not birthday_str:
            flash('All fields are required!', 'danger')
            return redirect(url_for('edit_student', student_id=student.id))
            
        try:
            birthday = datetime.strptime(birthday_str, '%Y-%m-%d').date()
            photo_path = student.photo_path
            
            if photo:
                # Remove old photo if exists
                if student.photo_path and os.path.exists(student.photo_path):
                    try:
                        os.remove(student.photo_path)
                    except Exception:
                        pass

                filename = f"{datetime.now().timestamp()}_{photo.filename}"
                photo_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                photo.save(photo_path)

            if student_sheet_store.is_configured():
                try:
                    student_sheet_store.update_student(student.id, {
                        "name": name,
                        "student_class": student_class,
                        "birthday": birthday.strftime('%Y-%m-%d'),
                        "father_name": father_name,
                        "contact_number_1": contact_number_1,
                        "contact_number_2": contact_number_2,
                        "corrections": corrections,
                        "parent_phone": parent_phone,
                        "photo_path": photo_path,
                        "created_at": student.created_at.strftime('%Y-%m-%d %H:%M:%S') if student.created_at else datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S'),
                    })
                    sync_students_from_sheet()
                except Exception as exc:
                    print(f"Sheets update failed, using local DB: {exc}")
                    student.name = name
                    student.student_class = student_class
                    student.birthday = birthday
                    student.father_name = father_name
                    student.contact_number_1 = contact_number_1
                    student.contact_number_2 = contact_number_2
                    student.corrections = corrections
                    student.parent_phone = parent_phone
                    student.photo_path = photo_path
                    db.session.commit()
            else:
                student.name = name
                student.student_class = student_class
                student.birthday = birthday
                student.father_name = father_name
                student.contact_number_1 = contact_number_1
                student.contact_number_2 = contact_number_2
                student.corrections = corrections
                student.parent_phone = parent_phone
                student.photo_path = photo_path
                db.session.commit()
            
            # Log notification
            new_notif = Notification(message=f"Student details updated for {student.name}", status="Completed")
            db.session.add(new_notif)
            db.session.commit()
            
            flash('Student updated successfully!', 'success')
            return redirect(url_for('index'))
        except Exception as e:
            flash(f'Error: {str(e)}', 'danger')
            return redirect(url_for('edit_student', student_id=student.id))
            
    return render_template('edit_student.html', student=student)

@app.route('/delete/<int:student_id>', methods=['POST'])
@login_required
@role_required(['Admin', 'Teacher', 'Office'])
def delete_student(student_id):
    sync_students_from_sheet()
    student = Student.query.get_or_404(student_id)
    name = student.name
    
    # Remove photo if exists
    if student.photo_path and os.path.exists(student.photo_path):
        try:
            os.remove(student.photo_path)
        except Exception:
            pass
            
    if student_sheet_store.is_configured():
        try:
            student_sheet_store.delete_student(student.id)
            sync_students_from_sheet()
        except Exception as exc:
            print(f"Sheets delete failed, using local DB: {exc}")
            db.session.delete(student)
            db.session.commit()
    else:
        db.session.delete(student)
        db.session.commit()
    
    # Log notification
    new_notif = Notification(message=f"Student record deleted: {name}", status="Completed")
    db.session.add(new_notif)
    db.session.commit()
    
    flash('Student deleted successfully!', 'success')
    return redirect(url_for('index'))

@app.route('/import', methods=['GET', 'POST'])
@login_required
@role_required(['Admin', 'Teacher', 'Office'])
def import_students():
    if request.method == 'POST':
        csv_file = request.files.get('csv_file')
        if not csv_file or not csv_file.filename.endswith('.csv'):
            flash('Please upload a valid CSV file.', 'danger')
            return redirect(url_for('import_students'))
            
        try:
            wipe_db = request.form.get('wipe_db') == 'true'
            if wipe_db:
                db.session.query(Student).delete()
                db.session.commit()

            csv_file_text = TextIOWrapper(csv_file.stream, encoding='utf-8')
            reader = csv.DictReader(csv_file_text)
            
            success_count = 0
            error_count = 0
            errors = []
            used_local_fallback = False

            def get_cell(row, *keys):
                for key in keys:
                    value = row.get(key)
                    if value is not None and str(value).strip():
                        return str(value).strip()
                return ""
            
            for line_no, row in enumerate(reader, start=2):
                name = get_cell(row, 'name', 'students name', 'student name')
                student_class = get_cell(row, 'class', 'student_class', 'grade') or 'N/A'
                birthday_str = get_cell(row, 'birthday', 'dob', 'date of birth')
                father_name = get_cell(row, 'father_name', 'fathers name', 'father name') or None
                contact_number_1 = get_cell(row, 'contact_number_1', 'contact number 1', 'contact number1') or None
                contact_number_2 = get_cell(row, 'contact_number_2', 'contact number 2', 'contact number2') or None
                corrections = get_cell(row, 'corrections') or None
                parent_phone = get_cell(row, 'parent_phone', 'parent phone', 'parent whatsapp number') or contact_number_1
                
                if not name or not student_class or not birthday_str:
                    errors.append(f"Row {line_no}: Missing required values.")
                    error_count += 1
                    continue
                    
                try:
                    birthday = build_student_kwargs({"name": name, "student_class": student_class, "birthday": birthday_str}).get("birthday")
                    if student_sheet_store.is_configured():
                        try:
                            student_sheet_store.add_student({
                                "name": name,
                                "student_class": student_class,
                                "birthday": birthday.strftime('%Y-%m-%d'),
                                "father_name": father_name,
                                "contact_number_1": contact_number_1,
                                "contact_number_2": contact_number_2,
                                "corrections": corrections,
                                "parent_phone": parent_phone,
                                "photo_path": None,
                                "created_at": datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S'),
                            })
                        except Exception as exc:
                            print(f"Sheets import failed, using local DB: {exc}")
                            used_local_fallback = True
                            new_student = Student(**build_student_kwargs({
                                "name": name,
                                "student_class": student_class,
                                "birthday": birthday,
                                "father_name": father_name,
                                "contact_number_1": contact_number_1,
                                "contact_number_2": contact_number_2,
                                "corrections": corrections,
                                "parent_phone": parent_phone,
                                "photo_path": None,
                            }))
                            db.session.add(new_student)
                    else:
                        used_local_fallback = True
                        new_student = Student(**build_student_kwargs({
                            "name": name,
                            "student_class": student_class,
                            "birthday": birthday,
                            "father_name": father_name,
                            "contact_number_1": contact_number_1,
                            "contact_number_2": contact_number_2,
                            "corrections": corrections,
                            "parent_phone": parent_phone,
                            "photo_path": None,
                        }))
                        db.session.add(new_student)
                    success_count += 1
                except ValueError:
                    errors.append(f"Row {line_no}: Invalid date format for '{birthday_str}' (expected YYYY-MM-DD).")
                    error_count += 1

            if used_local_fallback or not student_sheet_store.is_configured():
                db.session.commit()
            else:
                sync_students_from_sheet()
            
            # Log notification
            new_notif = Notification(message=f"Bulk imported {success_count} students (errors: {error_count})", status="Completed")
            db.session.add(new_notif)
            db.session.commit()
            
            if error_count > 0:
                flash(f"Import finished: {success_count} succeeded, {error_count} failed. Errors: " + "; ".join(errors[:5]), 'warning')
            else:
                flash(f"Successfully imported {success_count} students!", 'success')
                
            return redirect(url_for('index'))
        except Exception as e:
            flash(f"Error reading CSV: {str(e)}", 'danger')
            return redirect(url_for('import_students'))
            
    return render_template('import_students.html')

@app.route('/generate_poster/<int:student_id>')
@login_required
@role_required(['Admin', 'Media Team'])
def generate_poster(student_id):
    sync_students_from_sheet()
    student = Student.query.get_or_404(student_id)
    student_context = build_ai_context(serialize_student(student))
    quote = generate_birthday_quote(student.name, student_context)
    poster_path = create_birthday_poster(
        student.name, 
        student.student_class, 
        quote, 
        student.photo_path,
        output_path=app.config['POSTER_FOLDER']
    )
    # Convert path to web-accessible URL
    filename = os.path.basename(poster_path)
    poster_url = url_for('serve_poster', filename=filename)
    
    # Log notification
    generated_quote = GeneratedWish(
        recipient_name=student.name,
        relationship='Student',
        style='Poster Quote',
        wish_text=quote
    )
    db.session.add(generated_quote)
    new_notif = Notification(message=f"Poster generated for {student.name}", status="Completed")
    db.session.add(new_notif)
    db.session.commit()

    return render_template('view_poster.html', student=student, poster_url=poster_url, quote=quote)

@app.route('/email_poster/<int:student_id>', methods=['POST'])
@login_required
@role_required(['Admin', 'Media Team'])
def email_poster(student_id):
    sync_students_from_sheet()
    student = Student.query.get_or_404(student_id)
    recipient_email = request.form.get('email')
    poster_filename = request.form.get('poster_filename')
    
    if not recipient_email:
        flash('Recipient email is required!', 'danger')
        return redirect(url_for('generate_poster', student_id=student.id))

    try:
        poster_path = os.path.join(app.config['POSTER_FOLDER'], poster_filename)
        
        msg = Message(
            f"Happy Birthday {student.name}! 🎂",
            recipients=[recipient_email]
        )
        msg.body = f"Hello,\n\nPlease find the birthday poster for {student.name} attached.\n\nBest regards,\nBirthday AI Agent"
        
        with app.open_resource(poster_path) as fp:
            msg.attach(poster_filename, "image/png", fp.read())
            
        mail.send(msg)
        
        # Log notification
        new_notif = Notification(message=f"Poster emailed to {recipient_email} for {student.name}", status="Sent")
        db.session.add(new_notif)
        db.session.commit()
        
        flash(f'Poster successfully sent to {recipient_email}!', 'success')
    except Exception as e:
        flash(f'Error sending email: {str(e)}', 'danger')
        
    return redirect(url_for('generate_poster', student_id=student.id))

@app.route('/whatsapp_poster/<int:student_id>', methods=['POST'])
@login_required
@role_required(['Admin', 'Media Team'])
def whatsapp_poster(student_id):
    sync_students_from_sheet()
    student = Student.query.get_or_404(student_id)
    phone = request.form.get('phone', '').strip() or student.parent_phone
    poster_url = request.form.get('poster_url')
    
    if not phone:
        flash('Parent phone number is required!', 'danger')
        return redirect(url_for('generate_poster', student_id=student.id))
        
    success, msg = send_whatsapp_poster(phone, student.name, poster_url)
    
    if success:
        # Log notification
        new_notif = Notification(message=f"WhatsApp poster sent to parents ({phone}) for {student.name}", status="Sent")
        db.session.add(new_notif)
        db.session.commit()
        flash('WhatsApp message sent successfully via Twilio!', 'success')
    else:
        # Log notification
        new_notif = Notification(message=f"WhatsApp send failed for {student.name}: {msg}", status="Failed")
        db.session.add(new_notif)
        db.session.commit()
        flash(f'Failed to send WhatsApp message: {msg}', 'danger')
        
    return redirect(url_for('generate_poster', student_id=student.id))

@app.route('/send_daily_summary', methods=['GET', 'POST'])
def send_daily_summary():
    # Authorize either by session (for logged in admins/teachers manually triggering)
    # or by daily security token (for automated schedulers/cron calls)
    token = request.args.get('token')
    configured_token = os.getenv('DAILY_EMAIL_TOKEN', 'dev-token')
    
    authorized = False
    if 'user_id' in session and session.get('role') in ['Admin', 'Teacher']:
        authorized = True
    elif token and token == configured_token:
        authorized = True
        
    if not authorized:
        flash('Unauthorized! Please log in or provide a valid daily email security token.', 'danger')
        return redirect(url_for('login'))
        
    students = Student.query.all()
    today = datetime.now().date()
    
    birthdays_today = [s for s in students if s.birthday.month == today.month and s.birthday.day == today.day]
    
    upcoming_birthdays = []
    for s in students:
        try:
            bday_this_year = datetime(today.year, s.birthday.month, s.birthday.day).date()
        except ValueError:
            bday_this_year = datetime(today.year, 3, 1).date()
            
        if bday_this_year > today:
            diff = (bday_this_year - today).days
            if 0 < diff <= 7:
                upcoming_birthdays.append(s)
        elif bday_this_year < today:
            try:
                bday_next_year = datetime(today.year + 1, s.birthday.month, s.birthday.day).date()
                diff = (bday_next_year - today).days
                if 0 < diff <= 7:
                    upcoming_birthdays.append(s)
            except ValueError:
                pass

    recipient_emails_str = os.getenv('TEACHER_EMAILS')
    if recipient_emails_str:
        recipients = [email.strip() for email in recipient_emails_str.split(',') if email.strip()]
    else:
        recipients = [app.config['MAIL_DEFAULT_SENDER']]
        
    if not recipients or not recipients[0]:
        flash('Recipient emails not configured. Please set TEACHER_EMAILS in .env', 'danger')
        return redirect(url_for('index'))

    try:
        html_content = render_template('email_summary.html', 
                                       today=today, 
                                       birthdays_today=birthdays_today, 
                                       upcoming_birthdays=upcoming_birthdays)
        
        msg = Message(
            f"📅 School Birthday Daily Summary - {today.strftime('%d %b %Y')}",
            recipients=recipients
        )
        msg.html = html_content
        mail.send(msg)
        
        # Log notification
        new_notif = Notification(message=f"Daily summary email sent to {', '.join(recipients)}", status="Sent")
        db.session.add(new_notif)
        db.session.commit()
        
        flash('Daily summary email sent successfully!', 'success')
    except Exception as e:
        flash(f'Error sending daily email: {str(e)}', 'danger')
        
    return redirect(url_for('index'))

@app.route('/reports', methods=['GET'])
@login_required
def reports():
    sync_students_from_sheet()
    month = request.args.get('month', datetime.now().month, type=int)
    students = Student.query.all()
    
    # Filter students by the selected month
    monthly_birthdays = [s for s in students if s.birthday.month == month]
    # Sort by day
    monthly_birthdays.sort(key=lambda x: x.birthday.day)
    
    months = [
        "January", "February", "March", "April", "May", "June",
        "July", "August", "September", "October", "November", "December"
    ]
    
    return render_template('reports.html', 
                           students=monthly_birthdays, 
                           current_month=month, 
                           month_name=months[month-1],
                           months=months)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
