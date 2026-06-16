import os
from flask import Flask, render_template, request, redirect, url_for, flash
from models import db, Student
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///birthdays.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev-secret-key')
app.config['UPLOAD_FOLDER'] = 'static/uploads'

db.init_app(app)

with app.app_context():
    db.create_all()

@app.route('/')
def index():
    students = Student.query.all()
    today = datetime.now().date()
    
    # Simple birthday detection
    birthdays_today = [s for s in students if s.birthday.month == today.month and s.birthday.day == today.day]
    
    return render_template('index.html', students=students, birthdays_today=birthdays_today)

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
        student.photo_path
    )
    # Convert path to web-accessible URL
    poster_url = poster_path.replace('static/', '')
    return render_template('view_poster.html', student=student, poster_url=poster_url, quote=quote)

if __name__ == '__main__':
    app.run(debug=True)
