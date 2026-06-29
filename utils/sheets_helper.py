import json
import os
from dataclasses import dataclass
from datetime import datetime

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build


SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
DEFAULT_HEADERS = [
    "id",
    "name",
    "student_class",
    "birthday",
    "father_name",
    "contact_number_1",
    "contact_number_2",
    "corrections",
    "parent_phone",
    "photo_path",
    "created_at",
]
DEFAULT_SPREADSHEET_ID = "1mVwoFAnLyHi-3Z5JqeEGw9je6Wvr367d"
HEADER_ALIASES = {
    "s.no": "id",
    "s no": "id",
    "students name": "name",
    "student name": "name",
    "dob": "birthday",
    "date of birth": "birthday",
    "fathers name": "father_name",
    "father name": "father_name",
    "contact number 1": "contact_number_1",
    "contact number1": "contact_number_1",
    "contact number 2": "contact_number_2",
    "contact number2": "contact_number_2",
    "corrections": "corrections",
    "class": "student_class",
    "grade": "student_class",
    "parent phone": "parent_phone",
    "parent whatsapp number": "parent_phone",
}


@dataclass
class SheetStudent:
    id: int
    name: str
    student_class: str
    birthday: str
    father_name: str | None = None
    contact_number_1: str | None = None
    contact_number_2: str | None = None
    corrections: str | None = None
    parent_phone: str | None = None
    photo_path: str | None = None
    created_at: str | None = None


class StudentSheetStore:
    def __init__(self):
        self.spreadsheet_id = os.getenv("GOOGLE_SHEETS_SPREADSHEET_ID", DEFAULT_SPREADSHEET_ID).strip()
        self.sheet_name = os.getenv("GOOGLE_SHEETS_TAB_NAME", "").strip() or None
        self.creds = self._load_credentials()
        self.service = build("sheets", "v4", credentials=self.creds, cache_discovery=False) if self.creds and self.spreadsheet_id else None

    def is_configured(self):
        return self.service is not None

    def _load_credentials(self):
        service_account_file = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", "").strip()
        service_account_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()

        try:
            candidate_file = self._resolve_service_account_file(service_account_file)
            if candidate_file:
                return Credentials.from_service_account_file(candidate_file, scopes=SCOPES)
            if service_account_json:
                return Credentials.from_service_account_info(json.loads(service_account_json), scopes=SCOPES)
        except Exception as exc:
            print(f"Google Sheets credentials error: {exc}")
            return None

        if service_account_file and not os.path.isfile(service_account_file):
            print(f"Google Sheets credentials file not found: {service_account_file}")
        return None

    def _resolve_service_account_file(self, configured_path):
        candidate_paths = []
        if configured_path:
            candidate_paths.append(configured_path)

        repo_root = os.getcwd()
        candidate_paths.append(os.path.join(repo_root, "service_account.json"))
        candidate_paths.append(os.path.join(repo_root, "service_account.json", "service_account.json"))

        for candidate_path in candidate_paths:
            if os.path.isfile(candidate_path):
                return candidate_path
            if os.path.isdir(candidate_path):
                json_files = sorted(
                    file_path for file_path in (
                        os.path.join(candidate_path, entry)
                        for entry in os.listdir(candidate_path)
                    )
                    if file_path.lower().endswith(".json") and os.path.isfile(file_path)
                )
                if json_files:
                    return json_files[0]
        return None

    def _resolve_sheet_name(self):
        if self.sheet_name:
            return self.sheet_name

        metadata = self.service.spreadsheets().get(spreadsheetId=self.spreadsheet_id).execute()
        sheets = metadata.get("sheets", [])
        if sheets:
            self.sheet_name = sheets[0].get("properties", {}).get("title", "Students")
        else:
            self.sheet_name = "Students"
        return self.sheet_name

    def _worksheets(self):
        return self.service.spreadsheets()

    def _ensure_worksheet(self):
        self._resolve_sheet_name()
        try:
            self._worksheets().values().get(
                spreadsheetId=self.spreadsheet_id,
                range=f"{self.sheet_name}!A1:A1",
            ).execute()
        except Exception:
            self.service.spreadsheets().batchUpdate(
                spreadsheetId=self.spreadsheet_id,
                body={
                    "requests": [
                        {
                            "addSheet": {
                                "properties": {
                                    "title": self.sheet_name
                                }
                            }
                        }
                    ]
                },
            ).execute()

    def _range(self, row_start, row_end, col_end="K"):
        return f"{self.sheet_name}!A{row_start}:{col_end}{row_end}"

    def ensure_headers(self):
        self._ensure_worksheet()
        header_range = f"{self.sheet_name}!A1:K1"
        response = self._worksheets().values().get(
            spreadsheetId=self.spreadsheet_id,
            range=header_range,
        ).execute()
        values = response.get("values", [])
        if not values:
            self._worksheets().values().update(
                spreadsheetId=self.spreadsheet_id,
                range=header_range,
                valueInputOption="RAW",
                body={"values": [DEFAULT_HEADERS]},
            ).execute()
            return

        existing_headers = values[0]
        normalized_existing = [self._normalize_header(header) for header in existing_headers]
        if normalized_existing != DEFAULT_HEADERS:
            merged_headers = []
            for header in DEFAULT_HEADERS:
                if header not in normalized_existing:
                    merged_headers.append(header)
            final_headers = existing_headers + merged_headers
            self._worksheets().values().update(
                spreadsheetId=self.spreadsheet_id,
                range=f"{self.sheet_name}!A1:{self._column_letter(len(final_headers))}1",
                valueInputOption="RAW",
                body={"values": [final_headers]},
            ).execute()

    def list_students(self):
        if not self.is_configured():
            return []

        self.ensure_headers()
        response = self._worksheets().values().get(
            spreadsheetId=self.spreadsheet_id,
            range=f"{self.sheet_name}!A1:K",
        ).execute()
        values = response.get("values", [])
        if len(values) <= 1:
            return []

        headers = values[0]
        normalized_headers = [self._normalize_header(header) for header in headers]
        students = []
        for row in values[1:]:
            row_data = {normalized_headers[index]: row[index] if index < len(row) else "" for index in range(len(normalized_headers))}
            if not row_data.get("id"):
                continue
            students.append(self._row_to_student(row_data))
        return students

    def list_student_dicts(self):
        return [
            {
                "id": student.id,
                "name": student.name,
                "student_class": student.student_class,
                "birthday": student.birthday,
                "father_name": student.father_name,
                "contact_number_1": student.contact_number_1,
                "contact_number_2": student.contact_number_2,
                "corrections": student.corrections,
                "parent_phone": student.parent_phone,
                "photo_path": student.photo_path,
                "created_at": student.created_at,
            }
            for student in self.list_students()
        ]

    def next_student_id(self):
        students = self.list_students()
        ids = [student.id for student in students if student.id is not None]
        return max(ids, default=0) + 1

    def add_student(self, student_data):
        self.ensure_headers()
        student_id = self.next_student_id()
        row = self._student_to_row(
            SheetStudent(
                id=student_id,
                name=student_data["name"],
                student_class=student_data["student_class"],
                birthday=student_data["birthday"],
                father_name=student_data.get("father_name"),
                contact_number_1=student_data.get("contact_number_1"),
                contact_number_2=student_data.get("contact_number_2"),
                corrections=student_data.get("corrections"),
                parent_phone=student_data.get("parent_phone"),
                photo_path=student_data.get("photo_path"),
                created_at=student_data.get("created_at"),
            )
        )
        self._worksheets().values().append(
            spreadsheetId=self.spreadsheet_id,
            range=f"{self.sheet_name}!A:K",
            valueInputOption="USER_ENTERED",
            insertDataOption="INSERT_ROWS",
            body={"values": [row]},
        ).execute()
        return student_id

    def update_student(self, student_id, student_data):
        self.ensure_headers()
        row_index = self._find_row_index(student_id)
        if row_index is None:
            raise ValueError(f"Student id {student_id} not found in Sheets.")

        row = self._student_to_row(
            SheetStudent(
                id=student_id,
                name=student_data["name"],
                student_class=student_data["student_class"],
                birthday=student_data["birthday"],
                father_name=student_data.get("father_name"),
                contact_number_1=student_data.get("contact_number_1"),
                contact_number_2=student_data.get("contact_number_2"),
                corrections=student_data.get("corrections"),
                parent_phone=student_data.get("parent_phone"),
                photo_path=student_data.get("photo_path"),
                created_at=student_data.get("created_at"),
            )
        )
        self._worksheets().values().update(
            spreadsheetId=self.spreadsheet_id,
            range=self._range(row_index, row_index),
            valueInputOption="USER_ENTERED",
            body={"values": [row]},
        ).execute()

    def delete_student(self, student_id):
        self.ensure_headers()
        row_index = self._find_row_index(student_id)
        if row_index is None:
            raise ValueError(f"Student id {student_id} not found in Sheets.")

        self._worksheets().batchUpdate(
            spreadsheetId=self.spreadsheet_id,
            body={
                "requests": [
                    {
                        "deleteDimension": {
                            "range": {
                                "sheetId": self._sheet_id(),
                                "dimension": "ROWS",
                                "startIndex": row_index - 1,
                                "endIndex": row_index,
                            }
                        }
                    }
                ]
            },
        ).execute()

    def _find_row_index(self, student_id):
        response = self._worksheets().values().get(
            spreadsheetId=self.spreadsheet_id,
            range=f"{self.sheet_name}!A2:A",
        ).execute()
        values = response.get("values", [])
        for offset, row in enumerate(values, start=2):
            if row and str(row[0]).strip() == str(student_id):
                return offset
        return None

    def _sheet_id(self):
        metadata = self.service.spreadsheets().get(spreadsheetId=self.spreadsheet_id).execute()
        for sheet in metadata.get("sheets", []):
            props = sheet.get("properties", {})
            if props.get("title") == self.sheet_name:
                return props.get("sheetId")
        return None

    def _student_to_row(self, student):
        return [
            str(student.id),
            student.name,
            student.student_class,
            student.birthday,
            student.father_name or "",
            student.contact_number_1 or "",
            student.contact_number_2 or "",
            student.corrections or "",
            student.parent_phone or "",
            student.photo_path or "",
            student.created_at or "",
        ]

    def _row_to_student(self, row_data):
        birthday_value = row_data.get("birthday", "")
        created_at_value = row_data.get("created_at", "")

        birthday_value = self._normalize_birthday_value(birthday_value)

        return SheetStudent(
            id=int(row_data.get("id")),
            name=row_data.get("name", ""),
            student_class=row_data.get("student_class", "") or "N/A",
            birthday=birthday_value,
            father_name=row_data.get("father_name") or None,
            contact_number_1=row_data.get("contact_number_1") or None,
            contact_number_2=row_data.get("contact_number_2") or None,
            corrections=row_data.get("corrections") or None,
            parent_phone=row_data.get("parent_phone") or row_data.get("contact_number_1") or None,
            photo_path=row_data.get("photo_path") or None,
            created_at=created_at_value or None,
        )

    def _column_letter(self, index):
        letters = ""
        while index:
            index, remainder = divmod(index - 1, 26)
            letters = chr(65 + remainder) + letters
        return letters

    def _looks_like_iso_date(self, value):
        if not isinstance(value, str) or len(value) != 10:
            return False
        try:
            datetime.strptime(value, "%Y-%m-%d")
            return True
        except ValueError:
            return False

    def _normalize_header(self, header):
        normalized = str(header or "").strip().lower()
        normalized = normalized.replace(".", "").replace("_", " ")
        normalized = " ".join(normalized.split())
        return HEADER_ALIASES.get(normalized, normalized)

    def _normalize_birthday_value(self, value):
        if not value:
            return ""
        if self._looks_like_iso_date(value):
            return value
        for fmt in ("%d.%m.%Y", "%d/%m/%Y", "%Y-%m-%d"):
            try:
                return datetime.strptime(value, fmt).date().isoformat()
            except ValueError:
                continue
        return value


student_sheet_store = StudentSheetStore()
