import json

from utils.birthday_data import export_students_json
from utils.sheets_helper import student_sheet_store


def main():
    if not student_sheet_store.is_configured():
        raise SystemExit(
            "Google Sheets is not configured. Set GOOGLE_SERVICE_ACCOUNT_FILE or GOOGLE_SERVICE_ACCOUNT_JSON."
        )

    students = student_sheet_store.list_student_dicts()
    export_path = export_students_json(students)
    print(json.dumps({"count": len(students), "export_path": export_path, "students": students}, indent=2))


if __name__ == "__main__":
    main()
