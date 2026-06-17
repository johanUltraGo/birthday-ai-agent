import os
from flask import Flask, render_template, request, redirect, url_for, flash
from models import db, Student, Notification
from flask_mail import Mail, Message
from datetime import datetime
from dotenv import load_dotenv

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

# Route to serve files from the persistent data directory
from flask import send_from_directory
@app.route('/media/uploads/<filename>')
def serve_upload(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@app.route('/media/posters/<filename>')
def serve_poster(filename):
    return send_from_directory(app.config['POSTER_FOLDER'], filename)

@app.route('/')
def index():
    students = Student.query.all()
    today = datetime.now().date()
    
    # Simple birthday detection
    birthdays_today = [s for s in students if s.birthday.month == today.month and s.birthday.day == today.day]
    
    # Upcoming birthdays (next 7 days)
    upcoming_birthdays = []
    for s in students:
        # Create a date object for this year's birthday
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
            
            flash('Student added successfully!', 'success')
            return redirect(url_for('index'))
        except Exception as e:
            flash(f'Error: {str(e)}', 'danger')
            return redirect(url_for('add_student'))

    return render_template('add_student.html')

from utils.ai_helper import generate_birthday_quote
from utils.image_helper import create_birthday_poster

@app.route('/generate_poster/<int:student_id>')
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
    # Convert path to web-accessible URL using our new route
    filename = os.path.basename(poster_path)
    poster_url = url_for('serve_poster', filename=filename)
    
    # Log notification
    new_notif = Notification(message=f"Poster generated for {student.name}", status="Completed")
    db.session.add(new_notif)
    db.session.commit()

    return render_template('view_poster.html', student=student, poster_url=poster_url, quote=quote)

@app.route('/email_poster/<int:student_id>', methods=['POST'])
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

@app.route('/reports', methods=['GET'])
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
