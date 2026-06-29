import json
import os
from datetime import datetime, timedelta

from utils.sheets_helper import student_sheet_store

STUDENTS_JSON_PATH = os.path.join(
    os.getenv("DATA_DIR", os.path.join(os.getcwd(), "data")),
    "students.json",
)


def parse_birthday(value):
    if not value:
        return None
    if hasattr(value, "month"):
        return value
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(str(value), fmt).date()
        except ValueError:
            continue
    return None


def serialize_student(student):
    birthday = student.get("birthday")
    if hasattr(birthday, "isoformat"):
        birthday = birthday.isoformat()
    return {
        "id": student.get("id"),
        "name": student.get("name"),
        "student_class": student.get("student_class"),
        "birthday": birthday,
        "father_name": student.get("father_name"),
        "contact_number_1": student.get("contact_number_1"),
        "contact_number_2": student.get("contact_number_2"),
        "corrections": student.get("corrections"),
        "parent_phone": student.get("parent_phone"),
        "photo_path": student.get("photo_path"),
        "created_at": student.get("created_at"),
    }


def fetch_students_from_sheet():
    if not student_sheet_store.is_configured():
        return []
    return [serialize_student(student) for student in student_sheet_store.list_student_dicts()]


def export_students_json(students, path=None):
    target_path = path or STUDENTS_JSON_PATH
    os.makedirs(os.path.dirname(target_path), exist_ok=True)
    payload = {
        "synced_at": datetime.utcnow().isoformat() + "Z",
        "source": "google_sheets" if student_sheet_store.is_configured() else "local",
        "count": len(students),
        "students": students,
    }
    with open(target_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
    return target_path


def load_students_json(path=None):
    target_path = path or STUDENTS_JSON_PATH
    if not os.path.isfile(target_path):
        return []
    with open(target_path, encoding="utf-8") as handle:
        payload = json.load(handle)
    return payload.get("students", [])


def lookup_student_by_name(name, students=None):
    if not name:
        return None
    name_lower = name.strip().lower()
    source = students if students is not None else fetch_students_from_sheet()
    for student in source:
        if str(student.get("name", "")).strip().lower() == name_lower:
            return student
    return None


def birthday_this_year(birthday, today):
    try:
        return datetime(today.year, birthday.month, birthday.day).date()
    except ValueError:
        return datetime(today.year, 3, 1).date()


def get_today_birthdays(students, today=None):
    today = today or datetime.now().date()
    matches = []
    for student in students:
        birthday = parse_birthday(student.get("birthday"))
        if birthday and birthday.month == today.month and birthday.day == today.day:
            matches.append(student)
    return matches


def get_upcoming_birthdays(students, days=7, today=None):
    today = today or datetime.now().date()
    upcoming = []
    for student in students:
        birthday = parse_birthday(student.get("birthday"))
        if not birthday:
            continue

        bday_this_year = birthday_this_year(birthday, today)
        diff = (bday_this_year - today).days
        if 0 < diff <= days:
            upcoming.append({**student, "days_until": diff})
            continue

        if bday_this_year <= today:
            try:
                bday_next_year = datetime(today.year + 1, birthday.month, birthday.day).date()
            except ValueError:
                bday_next_year = datetime(today.year + 1, 3, 1).date()
            diff = (bday_next_year - today).days
            if 0 < diff <= days:
                upcoming.append({**student, "days_until": diff})

    upcoming.sort(key=lambda item: item.get("days_until", 999))
    return upcoming


def build_ai_context(student):
    if not student:
        return None

    birthday = parse_birthday(student.get("birthday"))
    age = None
    if birthday:
        today = datetime.now().date()
        age = today.year - birthday.year
        if (today.month, today.day) < (birthday.month, birthday.day):
            age -= 1

    context = {
        "name": student.get("name"),
        "student_class": student.get("student_class"),
        "birthday": birthday.isoformat() if birthday else student.get("birthday"),
    }
    if age is not None and age >= 0:
        context["age"] = age
    if student.get("father_name"):
        context["father_name"] = student.get("father_name")
    return context


def build_ai_context_prompt(student_context):
    if not student_context:
        return ""

    parts = []
    if student_context.get("student_class"):
        parts.append(f"class {student_context['student_class']}")
    if student_context.get("birthday"):
        parts.append(f"birthday on {student_context['birthday']}")
    if student_context.get("age") is not None:
        parts.append(f"turning {student_context['age']}")
    if student_context.get("father_name"):
        parts.append(f"father's name is {student_context['father_name']}")

    if not parts:
        return ""
    return "Student details from the school roster: " + ", ".join(parts) + ". "
