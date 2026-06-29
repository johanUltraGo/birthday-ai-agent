from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=True, default="")
    role = db.Column(db.String(50), nullable=False, default='Teacher') # Admin, Teacher, Office, Media Team

    def __repr__(self):
        return f'<User {self.username} ({self.role})>'

class Student(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    student_class = db.Column(db.String(50), nullable=False)
    birthday = db.Column(db.Date, nullable=False)
    father_name = db.Column(db.String(120), nullable=True)
    contact_number_1 = db.Column(db.String(30), nullable=True)
    contact_number_2 = db.Column(db.String(30), nullable=True)
    corrections = db.Column(db.Text, nullable=True)
    parent_phone = db.Column(db.String(30), nullable=True)
    photo_path = db.Column(db.String(200), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<Student {self.name}>'

class Notification(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    message = db.Column(db.String(200), nullable=False)
    status = db.Column(db.String(50), default='Sent')
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<Notification {self.message}>'

class GeneratedWish(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    recipient_name = db.Column(db.String(100), nullable=False)
    relationship = db.Column(db.String(50), nullable=False)
    style = db.Column(db.String(50), nullable=False)
    wish_text = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<GeneratedWish to {self.recipient_name} ({self.style})>'


