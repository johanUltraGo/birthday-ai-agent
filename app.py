import os
import csv
from io import TextIOWrapper
from datetime import datetime
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, flash, session, send_from_directory
from models import db, Student, Notification, User
from flask_mail import Mail, Message
from dotenv import load_dotenv
from utils.ai_helper import generate_birthday_quote
from utils.image_helper import create_birthday_poster
from utils.whatsapp_helper import send_whatsapp_poster

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

with app.app_context():
    db.create_all()
    # Auto-seed initial administrator user if none exists
    if User.query.count() == 0:
        admin_user = User(username='admin', role='Admin')
        admin_user.set_password('admin123')
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
        password = request.form.get('password')
        
        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            session['user_id'] = user.id
            session['username'] = user.username
            session['role'] = user.role
            flash(f'Welcome back, {user.username}! Logged in as {user.role}.', 'success')
            return redirect(url_for('index'))
        else:
            flash('Invalid username or password.', 'danger')
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
        password = request.form.get('password')
        role = request.form.get('role')
        
        if not username or not password or not role:
            flash('All fields are required!', 'danger')
            return redirect(url_for('register_user'))
            
        existing_user = User.query.filter_by(username=username).first()
        if existing_user:
            flash('Username already exists!', 'danger')
            return redirect(url_for('register_user'))
            
        new_user = User(username=username, role=role)
        new_user.set_password(password)
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

    return render_template('index.html', 
                           students=students, 
                           birthdays_today=birthdays_today, 
                           upcoming_birthdays=upcoming_birthdays,
                           notifications=notifications)

@app.route('/add', methods=['GET', 'POST'])
@login_required
@role_required(['Admin', 'Teacher', 'Office'])
def add_student():
    if request.method == 'POST':
        name = request.form.get('name')
        student_class = request.form.get('class')
        birthday_str = request.form.get('birthday')
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

            new_student = Student(
                name=name, 
                student_class=student_class, 
                birthday=birthday, 
                photo_path=photo_path
            )
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
    student = Student.query.get_or_404(student_id)
    if request.method == 'POST':
        name = request.form.get('name')
        student_class = request.form.get('class')
        birthday_str = request.form.get('birthday')
        photo = request.files.get('photo')
        
        if not name or not student_class or not birthday_str:
            flash('All fields are required!', 'danger')
            return redirect(url_for('edit_student', student_id=student.id))
            
        try:
            birthday = datetime.strptime(birthday_str, '%Y-%m-%d').date()
            student.name = name
            student.student_class = student_class
            student.birthday = birthday
            
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
    student = Student.query.get_or_404(student_id)
    name = student.name
    
    # Remove photo if exists
    if student.photo_path and os.path.exists(student.photo_path):
        try:
            os.remove(student.photo_path)
        except Exception:
            pass
            
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
            csv_file_text = TextIOWrapper(csv_file.stream, encoding='utf-8')
            reader = csv.DictReader(csv_file_text)
            
            # Verify columns
            required_cols = {'name', 'class', 'birthday'}
            if not required_cols.issubset(set(reader.fieldnames or [])):
                flash('CSV file must contain columns: name, class, birthday', 'danger')
                return redirect(url_for('import_students'))
                
            success_count = 0
            error_count = 0
            errors = []
            
            for line_no, row in enumerate(reader, start=2):
                name = row.get('name', '').strip()
                student_class = row.get('class', '').strip()
                birthday_str = row.get('birthday', '').strip()
                
                if not name or not student_class or not birthday_str:
                    errors.append(f"Row {line_no}: Missing required values.")
                    error_count += 1
                    continue
                    
                try:
                    birthday = datetime.strptime(birthday_str, '%Y-%m-%d').date()
                    new_student = Student(
                        name=name,
                        student_class=student_class,
                        birthday=birthday
                    )
                    db.session.add(new_student)
                    success_count += 1
                except ValueError:
                    errors.append(f"Row {line_no}: Invalid date format for '{birthday_str}' (expected YYYY-MM-DD).")
                    error_count += 1
                    
            db.session.commit()
            
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
    student = Student.query.get_or_404(student_id)
    quote = generate_birthday_quote(student.name)
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
    new_notif = Notification(message=f"Poster generated for {student.name}", status="Completed")
    db.session.add(new_notif)
    db.session.commit()

    return render_template('view_poster.html', student=student, poster_url=poster_url, quote=quote)

@app.route('/email_poster/<int:student_id>', methods=['POST'])
@login_required
@role_required(['Admin', 'Media Team'])
def email_poster(student_id):
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
    student = Student.query.get_or_404(student_id)
    phone = request.form.get('phone')
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
    app.run(debug=True)
