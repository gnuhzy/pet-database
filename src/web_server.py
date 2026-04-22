"""
HTTP API for the PawTrack frontend.

The server uses the existing schema and CSV seed files to initialize a local
SQLite database, then exposes JSON endpoints for the single-page frontend.
"""

from __future__ import annotations

import argparse
import csv
import json
import mimetypes
import re
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import llm_sql_assistant
from query_registry import (
    StoredQuery,
    is_read_only_query,
    load_query_registry,
    match_query_from_prompt,
)


ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
SCHEMA_PATH = ROOT_DIR / "src" / "schema" / "table.sql"
INDEXING_PATH = ROOT_DIR / "src" / "schema" / "indexing.sql"
DB_PATH = ROOT_DIR / "pet_database.db"
FRONTEND_PATH = ROOT_DIR / "pawtrack_demo.html"

SEED_FILES = [
    ("SHELTER", "Shelter.csv"),
    ("APPLICANT", "Applicant.csv"),
    ("VOLUNTEER", "Volunteer.csv"),
    ("PET", "Pet.csv"),
    ("VACCINATION", "Vaccination.csv"),
    ("MEDICAL_RECORD", "MedicalRecord.csv"),
    ("CARE_ASSIGNMENT", "CareAssignment.csv"),
    ("ADOPTION_APPLICATION", "AdoptionApplication.csv"),
    ("ADOPTION_RECORD", "AdoptionRecord.csv"),
    ("FOLLOW_UP", "FollowUp.csv"),
]

PET_STATUS_LABELS = {
    "available": "Available",
    "reserved": "Reserved",
    "adopted": "Adopted",
    "medical_hold": "Medical hold",
    "medical hold": "Medical hold",
}

PET_STATUS_DB_VALUES = {
    "Available": "available",
    "Reserved": "reserved",
    "Adopted": "adopted",
    "Medical hold": "medical_hold",
}

APPLICATION_STATUS_LABELS = {
    "under review": "Pending",
    "pending": "Pending",
    "approved": "Approved",
    "rejected": "Rejected",
}

PET_STATUS_VALUES = {"available", "reserved", "adopted", "medical_hold"}
SPECIES_VALUES = {"Dog", "Cat", "Rabbit", "Bird"}
SEX_VALUES = {"Male", "Female", "Unknown"}
HOUSING_TYPE_VALUES = {
    "Apartment",
    "Condo",
    "House",
    "Townhouse",
    "House with garden",
    "House without garden",
    "Shared housing",
}
MEDICAL_RECORD_TYPES = {"Check-up", "Surgery", "Treatment", "Injury", "Dental"}
CARE_ASSIGNMENT_STATUSES = {"Scheduled", "Completed", "Cancelled"}
CARE_SHIFTS = {"Morning", "Afternoon", "Evening"}
CARE_TASK_TYPES = {"Cleaning", "Feeding", "Grooming", "Socializing", "Walking", "Medical support"}
FOLLOWUP_TYPES = {"Phone Check", "Home Visit", "Vet Check"}
FOLLOWUP_RESULT_STATUSES = {"Excellent", "Good", "Satisfactory", "Needs Improvement"}
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PHONE_RE = re.compile(r"^[+()0-9][+()0-9\s-]{2,24}$")
SCHEMA_MARKERS = (
    "chk_pet_status",
    "chk_adoption_application_status",
    "chk_adoption_record_fee_nonnegative",
    "chk_followup_result_status",
    "CREATE TABLE SYSTEM_LOG",
)
APP_TIMEZONE = timezone(timedelta(hours=8), name="Asia/Shanghai")
APP_TIMEZONE_NAME = "Asia/Shanghai"
DATETIME_COLUMNS = (
    ("APPLICANT", "created_at"),
    ("VOLUNTEER", "join_date"),
    ("PET", "estimated_birth_date"),
    ("PET", "intake_date"),
    ("VACCINATION", "vaccination_date"),
    ("VACCINATION", "next_due_date"),
    ("MEDICAL_RECORD", "visit_date"),
    ("CARE_ASSIGNMENT", "assignment_date"),
    ("ADOPTION_APPLICATION", "application_date"),
    ("ADOPTION_APPLICATION", "reviewed_date"),
    ("ADOPTION_RECORD", "adoption_date"),
    ("FOLLOW_UP", "followup_date"),
)
RESOURCE_EVENT_TYPES = {
    "shelters": "shelter",
    "pets": "pet",
    "applicants": "applicant",
    "medical-records": "medical",
    "vaccinations": "vaccination",
    "volunteers": "volunteer",
    "care-assignments": "care_assignment",
    "follow-ups": "follow_up",
}


class ApiError(Exception):
    def __init__(self, status: HTTPStatus, message: str, payload: dict[str, Any] | None = None):
        super().__init__(message)
        self.status = status
        self.message = message
        self.payload = payload or {}


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def managed_connection():
    conn = connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def local_now() -> datetime:
    return datetime.now(APP_TIMEZONE)


def local_today() -> date:
    return local_now().date()


def local_today_iso() -> str:
    return local_today().isoformat()


def local_now_iso() -> str:
    return local_now().strftime("%Y-%m-%d %H:%M")


def begin_write(conn: sqlite3.Connection) -> None:
    """Serialize write operations so validation and mutation stay atomic."""
    conn.execute("BEGIN IMMEDIATE")


def schema_is_current(conn: sqlite3.Connection) -> bool:
    schema_sql = "\n".join(
        row["sql"] or ""
        for row in conn.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
    )
    return all(marker in schema_sql for marker in SCHEMA_MARKERS)


def database_is_ready() -> bool:
    if not DB_PATH.exists():
        return False
    try:
        with managed_connection() as conn:
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'PET'"
            ).fetchone()
            if not row:
                return False
            count = conn.execute("SELECT COUNT(*) AS count FROM PET").fetchone()["count"]
            return count > 0 and schema_is_current(conn)
    except sqlite3.Error:
        return False


def clean_csv_value(value: str | None):
    if value is None:
        return None
    value = value.strip()
    return value if value else None


def normalize_stored_dates(conn: sqlite3.Connection) -> None:
    """Keep stored date-like values at minute precision without discarding time."""
    for table_name, column_name in DATETIME_COLUMNS:
        conn.execute(
            f"""
            UPDATE {table_name}
            SET {column_name} = CASE
                WHEN length({column_name}) = 10 THEN {column_name} || ' 00:00'
                WHEN length({column_name}) >= 16 THEN substr({column_name}, 1, 16)
                ELSE {column_name}
            END
            WHERE {column_name} IS NOT NULL
            """
        )


def seed_system_activity_log(conn: sqlite3.Connection) -> None:
    """Backfill dashboard activity from seed data once, then rely on runtime logs."""
    existing_activity_count = conn.execute(
        """
        SELECT COUNT(*) AS count
        FROM SYSTEM_LOG
        WHERE event_type NOT LIKE 'delete_%'
        """
    ).fetchone()["count"]
    if existing_activity_count:
        return

    conn.execute(
        """
        INSERT INTO SYSTEM_LOG (event_date, event_type, event_id, text, dot_class, sort_priority)
        SELECT event_date, event_type, event_id, text, dot_class, sort_priority
        FROM (
            SELECT
                ar.adoption_date AS event_date,
                'adoption' AS event_type,
                ar.adoption_id AS event_id,
                'Adoption finalized: ' || p.name || ' with ' || ap.full_name AS text,
                'dot-green' AS dot_class,
                20 AS sort_priority
            FROM ADOPTION_RECORD ar
            JOIN ADOPTION_APPLICATION aa ON ar.application_id = aa.application_id
            JOIN APPLICANT ap ON aa.applicant_id = ap.applicant_id
            JOIN PET p ON aa.pet_id = p.pet_id

            UNION ALL

            SELECT
                aa.reviewed_date AS event_date,
                'application_review' AS event_type,
                aa.application_id AS event_id,
                'Application ' || printf('APP-%03d', aa.application_id) || ' status updated to ' || aa.status AS text,
                'dot-amber' AS dot_class,
                30 AS sort_priority
            FROM ADOPTION_APPLICATION aa
            WHERE aa.reviewed_date IS NOT NULL

            UNION ALL

            SELECT
                aa.application_date AS event_date,
                'application' AS event_type,
                aa.application_id AS event_id,
                'Application ' || printf('APP-%03d', aa.application_id) || ' submitted for ' || p.name || ' by ' || ap.full_name AS text,
                'dot-amber' AS dot_class,
                40 AS sort_priority
            FROM ADOPTION_APPLICATION aa
            JOIN APPLICANT ap ON aa.applicant_id = ap.applicant_id
            JOIN PET p ON aa.pet_id = p.pet_id

            UNION ALL

            SELECT
                ap.created_at AS event_date,
                'applicant' AS event_type,
                ap.applicant_id AS event_id,
                'Applicant profile created for ' || ap.full_name AS text,
                'dot-blue' AS dot_class,
                90 AS sort_priority
            FROM APPLICANT ap
            WHERE ap.created_at IS NOT NULL

            UNION ALL

            SELECT
                m.visit_date AS event_date,
                'medical' AS event_type,
                m.record_id AS event_id,
                'Medical record added for ' || p.name || CASE
                    WHEN m.record_type IS NOT NULL AND m.record_type != '' THEN ' (' || m.record_type || ')'
                    ELSE ''
                END AS text,
                'dot-blue' AS dot_class,
                60 AS sort_priority
            FROM MEDICAL_RECORD m
            JOIN PET p ON m.pet_id = p.pet_id

            UNION ALL

            SELECT
                v.vaccination_date AS event_date,
                'vaccination' AS event_type,
                v.vaccination_id AS event_id,
                'Vaccination record added for ' || p.name AS text,
                'dot-blue' AS dot_class,
                70 AS sort_priority
            FROM VACCINATION v
            JOIN PET p ON v.pet_id = p.pet_id

            UNION ALL

            SELECT
                c.assignment_date AS event_date,
                'care_assignment' AS event_type,
                c.assignment_id AS event_id,
                'Care assignment scheduled for ' || v.full_name || ' with ' || p.name AS text,
                'dot-blue' AS dot_class,
                50 AS sort_priority
            FROM CARE_ASSIGNMENT c
            JOIN VOLUNTEER v ON c.volunteer_id = v.volunteer_id
            JOIN PET p ON c.pet_id = p.pet_id

            UNION ALL

            SELECT
                f.followup_date AS event_date,
                'follow_up' AS event_type,
                f.followup_id AS event_id,
                'Follow-up completed for ' || p.name AS text,
                'dot-green' AS dot_class,
                10 AS sort_priority
            FROM FOLLOW_UP f
            JOIN ADOPTION_RECORD ar ON f.adoption_id = ar.adoption_id
            JOIN ADOPTION_APPLICATION aa ON ar.application_id = aa.application_id
            JOIN PET p ON aa.pet_id = p.pet_id

            UNION ALL

            SELECT
                vol.join_date AS event_date,
                'volunteer' AS event_type,
                vol.volunteer_id AS event_id,
                'Volunteer joined: ' || vol.full_name AS text,
                'dot-blue' AS dot_class,
                100 AS sort_priority
            FROM VOLUNTEER vol
            WHERE vol.join_date IS NOT NULL

            UNION ALL

            SELECT
                p.intake_date AS event_date,
                'pet' AS event_type,
                p.pet_id AS event_id,
                'Pet intake recorded for ' || p.name AS text,
                'dot-blue' AS dot_class,
                80 AS sort_priority
            FROM PET p
        )
        WHERE event_date IS NOT NULL
        ORDER BY datetime(event_date), sort_priority, event_id
        """
    )


def reconcile_pet_workflow_states(conn: sqlite3.Connection, pet_id: int | None = None) -> None:
    """Keep pet availability aligned with adoption application workflow state."""
    params: tuple = (pet_id,) if pet_id is not None else ()
    pet_filter = "AND pet_id = ?" if pet_id is not None else ""
    exists_pet_filter = "AND a.pet_id = PET.pet_id"

    conn.execute(
        f"""
        UPDATE PET
        SET status = 'reserved'
        WHERE EXISTS (
            SELECT 1
            FROM ADOPTION_APPLICATION a
            WHERE a.status = 'Under Review'
              {exists_pet_filter}
        )
        {pet_filter}
        """,
        params,
    )
    conn.execute(
        f"""
        UPDATE PET
        SET status = 'adopted'
        WHERE EXISTS (
            SELECT 1
            FROM ADOPTION_APPLICATION a
            WHERE a.status = 'Approved'
              {exists_pet_filter}
        )
          AND NOT EXISTS (
            SELECT 1
            FROM ADOPTION_APPLICATION a
            WHERE a.status = 'Under Review'
              {exists_pet_filter}
        )
        {pet_filter}
        """,
        params,
    )
    conn.execute(
        f"""
        UPDATE PET
        SET status = 'available'
        WHERE lower(status) = 'reserved'
          AND NOT EXISTS (
            SELECT 1
            FROM ADOPTION_APPLICATION a
            WHERE a.pet_id = PET.pet_id
              AND a.status IN ('Under Review', 'Approved')
          )
        {pet_filter}
        """,
        params,
    )


def initialize_database(reset: bool = False) -> None:
    if reset and DB_PATH.exists():
        DB_PATH.unlink()
    if database_is_ready():
        with managed_connection() as conn:
            normalize_stored_dates(conn)
            conn.executescript(INDEXING_PATH.read_text(encoding="utf-8"))
            seed_system_activity_log(conn)
            assert_startup_integrity(conn)
        return
    if DB_PATH.exists():
        DB_PATH.unlink()

    with managed_connection() as conn:
        schema = SCHEMA_PATH.read_text(encoding="utf-8")
        conn.executescript(schema)
        conn.executescript(INDEXING_PATH.read_text(encoding="utf-8"))

        for table_name, file_name in SEED_FILES:
            csv_path = DATA_DIR / file_name
            with csv_path.open("r", encoding="utf-8-sig", newline="") as fh:
                reader = csv.DictReader(fh)
                if not reader.fieldnames:
                    continue
                columns = reader.fieldnames
                placeholders = ", ".join("?" for _ in columns)
                column_sql = ", ".join(columns)
                sql = f"INSERT INTO {table_name} ({column_sql}) VALUES ({placeholders})"
                rows = [
                    tuple(clean_csv_value(row.get(column)) for column in columns)
                    for row in reader
                ]
                if rows:
                    conn.executemany(sql, rows)
        normalize_stored_dates(conn)
        seed_system_activity_log(conn)
        assert_startup_integrity(conn)


def pet_status_label(status: str | None) -> str:
    if not status:
        return ""
    key = status.strip().lower().replace("-", "_")
    return PET_STATUS_LABELS.get(key, status.strip().replace("_", " ").title())


def application_status_label(status: str | None) -> str:
    if not status:
        return ""
    key = status.strip().lower().replace("_", " ")
    return APPLICATION_STATUS_LABELS.get(key, status.strip())


def yes_no(value) -> str:
    return "Yes" if str(value) in {"1", "true", "True"} else "No"


def display_id(prefix: str, value) -> str:
    return f"{prefix}-{int(value):03d}"


def row_dict(row: sqlite3.Row | None) -> dict:
    return dict(row) if row else {}


def db_date_str(value) -> str:
    return str(value)[:10] if value else ""


def execute_read_only_query(conn: sqlite3.Connection, query: StoredQuery) -> list[dict[str, Any]]:
    if not is_read_only_query(query):
        raise ApiError(HTTPStatus.BAD_REQUEST, "Only read-only predefined SELECT queries can run from the LLM assistant.")
    rows = conn.execute(query.sql).fetchall()
    return [dict(row) for row in rows]


def fetch_pets(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        """
        SELECT p.*, s.name AS shelter_name
        FROM PET p
        LEFT JOIN SHELTER s ON p.shelter_id = s.shelter_id
        ORDER BY p.pet_id
        """
    ).fetchall()
    return [format_pet(row) for row in rows]


def format_pet(row: sqlite3.Row) -> dict:
    raw = row_dict(row)
    status_label = pet_status_label(raw["status"])
    return {
        "petId": raw["pet_id"],
        "shelterId": raw["shelter_id"],
        "id": display_id("P", raw["pet_id"]),
        "name": raw["name"],
        "species": raw["species"],
        "breed": raw["breed"] or "",
        "sex": raw["sex"] or "",
        "color": raw["color"] or "",
        "birth": db_date_str(raw["estimated_birth_date"]),
        "intake": db_date_str(raw["intake_date"]),
        "status": status_label,
        "statusLabel": status_label,
        "rawStatus": raw["status"],
        "sterilized": yes_no(raw["is_sterilized"]),
        "special": raw["special_needs"] or "None",
        "shelter": raw.get("shelter_name") or "",
    }


def fetch_shelters(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        """
        SELECT
            s.*,
            COUNT(DISTINCT p.pet_id) AS current_pet_count,
            COUNT(DISTINCT v.volunteer_id) AS volunteer_count
        FROM SHELTER s
        LEFT JOIN PET p
            ON s.shelter_id = p.shelter_id
           AND lower(p.status) IN ('available', 'reserved', 'medical_hold')
        LEFT JOIN VOLUNTEER v ON s.shelter_id = v.shelter_id
        GROUP BY s.shelter_id, s.name, s.address, s.phone, s.capacity
        ORDER BY s.shelter_id
        """
    ).fetchall()
    return [
        {
            "shelterId": row["shelter_id"],
            "id": display_id("S", row["shelter_id"]),
            "name": row["name"],
            "address": row["address"] or "",
            "phone": row["phone"] or "",
            "capacity": row["capacity"],
            "currentPetCount": row["current_pet_count"] or 0,
            "volunteerCount": row["volunteer_count"] or 0,
            "occupancyRate": round((row["current_pet_count"] or 0) * 100 / row["capacity"], 2)
            if row["capacity"]
            else 0,
        }
        for row in rows
    ]


def fetch_applicants(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        """
        SELECT *
        FROM APPLICANT
        ORDER BY full_name
        """
    ).fetchall()
    return [
        {
            "applicantId": row["applicant_id"],
            "id": display_id("A", row["applicant_id"]),
            "name": row["full_name"],
            "phone": row["phone"] or "",
            "email": row["email"] or "",
            "address": row["address"] or "",
            "housingType": row["housing_type"] or "",
            "hasPetExperience": bool(row["has_pet_experience"]),
            "createdAt": db_date_str(row["created_at"]),
        }
        for row in rows
    ]


def application_query(where_clause: str = "", params: tuple = ()) -> tuple[str, tuple]:
    sql = f"""
        SELECT
            a.*,
            ap.full_name AS applicant_name,
            ap.phone AS applicant_phone,
            ap.email AS applicant_email,
            ap.address AS applicant_address,
            ap.housing_type,
            ap.has_pet_experience,
            ap.created_at AS applicant_created_at,
            p.name AS pet_name,
            p.species AS pet_species,
            p.breed AS pet_breed
        FROM ADOPTION_APPLICATION a
        JOIN APPLICANT ap ON a.applicant_id = ap.applicant_id
        JOIN PET p ON a.pet_id = p.pet_id
        {where_clause}
        ORDER BY a.application_date DESC, a.application_id DESC
    """
    return sql, params


def fetch_applications(conn: sqlite3.Connection) -> list[dict]:
    sql, params = application_query()
    return [format_application(row) for row in conn.execute(sql, params).fetchall()]


def fetch_application(conn: sqlite3.Connection, application_id: int) -> dict | None:
    sql, params = application_query("WHERE a.application_id = ?", (application_id,))
    row = conn.execute(sql, params).fetchone()
    return format_application(row) if row else None


def format_application(row: sqlite3.Row) -> dict:
    raw = row_dict(row)
    status_label = application_status_label(raw["status"])
    return {
        "applicationId": raw["application_id"],
        "applicantId": raw["applicant_id"],
        "petId": raw["pet_id"],
        "id": display_id("APP", raw["application_id"]),
        "applicant": raw["applicant_name"],
        "applicantPhone": raw["applicant_phone"] or "",
        "applicantEmail": raw["applicant_email"] or "",
        "applicantAddress": raw["applicant_address"] or "",
        "hasPetExperience": bool(raw["has_pet_experience"]),
        "applicantCreatedAt": db_date_str(raw["applicant_created_at"]),
        "pet": raw["pet_name"],
        "petSpecies": raw["pet_species"],
        "petBreed": raw["pet_breed"] or "",
        "date": db_date_str(raw["application_date"]),
        "status": status_label,
        "statusLabel": status_label,
        "rawStatus": raw["status"],
        "reason": raw["reason"] or "",
        "reviewedDate": db_date_str(raw["reviewed_date"]),
        "reviewer": raw["reviewer_name"] or "-",
        "decision": raw["decision_note"] or "-",
        "housingType": raw["housing_type"] or "",
    }


def format_adoption_record(row: sqlite3.Row) -> dict:
    return {
        "adoptionId": row["adoption_id"],
        "id": display_id("AR", row["adoption_id"]),
        "applicationId": row["application_id"],
        "applicationCode": display_id("APP", row["application_id"]),
        "adoptionDate": db_date_str(row["adoption_date"]),
        "finalAdoptionFee": row["final_adoption_fee"],
        "handoverNote": row["handover_note"] or "",
        "applicantId": row["applicant_id"],
        "applicant": row["applicant_name"],
        "petId": row["pet_id"],
        "pet": row["pet_name"],
        "petSpecies": row["pet_species"],
        "followupCount": row["followup_count"] or 0,
        "lastFollowupDate": db_date_str(row["last_followup_date"]),
    }


def fetch_adoption_records(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        """
        SELECT
            ar.*,
            aa.applicant_id,
            aa.pet_id,
            ap.full_name AS applicant_name,
            p.name AS pet_name,
            p.species AS pet_species,
            COUNT(f.followup_id) AS followup_count,
            MAX(f.followup_date) AS last_followup_date
        FROM ADOPTION_RECORD ar
        JOIN ADOPTION_APPLICATION aa ON ar.application_id = aa.application_id
        JOIN APPLICANT ap ON aa.applicant_id = ap.applicant_id
        JOIN PET p ON aa.pet_id = p.pet_id
        LEFT JOIN FOLLOW_UP f ON ar.adoption_id = f.adoption_id
        GROUP BY
            ar.adoption_id,
            ar.application_id,
            ar.adoption_date,
            ar.final_adoption_fee,
            ar.handover_note,
            aa.applicant_id,
            aa.pet_id,
            ap.full_name,
            p.name,
            p.species
        ORDER BY ar.adoption_date DESC, ar.adoption_id DESC
        """
    ).fetchall()
    return [format_adoption_record(row) for row in rows]


def format_followup(row: sqlite3.Row) -> dict:
    result_status = row["result_status"] or ""
    return {
        "followupId": row["followup_id"],
        "id": display_id("FU", row["followup_id"]),
        "adoptionId": row["adoption_id"],
        "adoptionCode": display_id("AR", row["adoption_id"]),
        "followupDate": db_date_str(row["followup_date"]),
        "followupType": row["followup_type"] or "",
        "petCondition": row["pet_condition"] or "",
        "adopterFeedback": row["adopter_feedback"] or "",
        "resultStatus": result_status,
        "resultStatusLabel": result_status,
        "rawResultStatus": result_status,
        "staffNote": row["staff_note"] or "",
        "applicationId": row["application_id"],
        "applicationCode": display_id("APP", row["application_id"]),
        "applicant": row["applicant_name"],
        "petId": row["pet_id"],
        "pet": row["pet_name"],
    }


def fetch_followups(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        """
        SELECT
            f.*,
            ar.application_id,
            aa.pet_id,
            ap.full_name AS applicant_name,
            p.name AS pet_name
        FROM FOLLOW_UP f
        JOIN ADOPTION_RECORD ar ON f.adoption_id = ar.adoption_id
        JOIN ADOPTION_APPLICATION aa ON ar.application_id = aa.application_id
        JOIN APPLICANT ap ON aa.applicant_id = ap.applicant_id
        JOIN PET p ON aa.pet_id = p.pet_id
        ORDER BY f.followup_date DESC, f.followup_id DESC
        """
    ).fetchall()
    return [format_followup(row) for row in rows]


def fetch_medical_records(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        """
        SELECT m.*, p.name AS pet_name
        FROM MEDICAL_RECORD m
        JOIN PET p ON m.pet_id = p.pet_id
        ORDER BY m.visit_date DESC, m.record_id DESC
        """
    ).fetchall()
    return [
        {
            "recordId": row["record_id"],
            "id": display_id("MR", row["record_id"]),
            "petId": row["pet_id"],
            "pet": row["pet_name"],
            "date": db_date_str(row["visit_date"]),
            "type": row["record_type"] or "",
            "diagnosis": row["diagnosis"] or "",
            "treatment": row["treatment"] or "",
            "vet": row["vet_name"] or "",
            "notes": row["notes"] or "",
        }
        for row in rows
    ]


def fetch_vaccinations(conn: sqlite3.Connection, upcoming_only: bool = False) -> list[dict]:
    params: tuple[Any, ...] = ()
    where = ""
    if upcoming_only:
        today_iso = local_today_iso()
        upcoming_cutoff = (local_today() + timedelta(days=30)).isoformat()
        where = """
        WHERE v.next_due_date IS NOT NULL
          AND date(v.next_due_date) BETWEEN date(?) AND date(?)
        """
        params = (today_iso, upcoming_cutoff)
    rows = conn.execute(
        f"""
        SELECT v.*, p.name AS pet_name
        FROM VACCINATION v
        JOIN PET p ON v.pet_id = p.pet_id
        {where}
        ORDER BY date(v.next_due_date), v.vaccination_id
        """,
        params,
    ).fetchall()
    return [
        {
            "vaccinationId": row["vaccination_id"],
            "id": display_id("V", row["vaccination_id"]),
            "petId": row["pet_id"],
            "pet": row["pet_name"],
            "vaccine": row["vaccine_name"],
            "doseNo": row["dose_no"],
            "vaccinationDate": db_date_str(row["vaccination_date"]),
            "dueDate": db_date_str(row["next_due_date"]),
            "vet": row["vet_name"] or "",
            "notes": row["notes"] or "",
        }
        for row in rows
    ]


def fetch_volunteers(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        """
        SELECT
            v.*,
            s.name AS shelter_name,
            GROUP_CONCAT(DISTINCT p.name) AS assigned_pets,
            SUM(CASE WHEN c.status != 'Cancelled' THEN 1 ELSE 0 END) AS active_assignment_count
        FROM VOLUNTEER v
        JOIN SHELTER s ON v.shelter_id = s.shelter_id
        LEFT JOIN CARE_ASSIGNMENT c ON v.volunteer_id = c.volunteer_id
        LEFT JOIN PET p ON c.pet_id = p.pet_id AND c.status != 'Cancelled'
        GROUP BY v.volunteer_id
        ORDER BY v.full_name
        """
    ).fetchall()
    return [
        {
            "volunteerId": row["volunteer_id"],
            "shelterId": row["shelter_id"],
            "id": display_id("VLT", row["volunteer_id"]),
            "name": row["full_name"],
            "email": row["email"] or "",
            "phone": row["phone"] or "",
            "joined": db_date_str(row["join_date"]),
            "availability": row["availability_note"] or "",
            "shelter": row["shelter_name"] or "",
            "assignedPets": (row["assigned_pets"] or "-").replace(",", ", "),
            "status": "Active" if (row["active_assignment_count"] or 0) > 0 else "Inactive",
        }
        for row in rows
    ]


def fetch_care_assignments(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        """
        SELECT c.*, v.full_name AS volunteer_name, p.name AS pet_name
        FROM CARE_ASSIGNMENT c
        JOIN VOLUNTEER v ON c.volunteer_id = v.volunteer_id
        JOIN PET p ON c.pet_id = p.pet_id
        ORDER BY c.assignment_date DESC, c.assignment_id DESC
        """
    ).fetchall()
    return [
        {
            "assignmentId": row["assignment_id"],
            "id": display_id("CA", row["assignment_id"]),
            "volunteerId": row["volunteer_id"],
            "petId": row["pet_id"],
            "volunteer": row["volunteer_name"],
            "pet": row["pet_name"],
            "date": db_date_str(row["assignment_date"]),
            "shift": row["shift"] or "",
            "task": row["task_type"] or "",
            "status": row["status"] or "",
            "statusLabel": row["status"] or "",
            "rawStatus": row["status"] or "",
            "notes": row["notes"] or "",
        }
        for row in rows
    ]


def fetch_dashboard(conn: sqlite3.Connection) -> dict:
    total_pets = conn.execute("SELECT COUNT(*) AS count FROM PET").fetchone()["count"]
    shelter_count = conn.execute("SELECT COUNT(*) AS count FROM SHELTER").fetchone()["count"]
    available_count = conn.execute(
        "SELECT COUNT(*) AS count FROM PET WHERE lower(status) = 'available'"
    ).fetchone()["count"]
    pending_count = conn.execute(
        """
        SELECT COUNT(*) AS count
        FROM ADOPTION_APPLICATION
        WHERE status = 'Under Review'
        """
    ).fetchone()["count"]
    month_prefix = local_today().strftime("%Y-%m")
    month_adoptions = conn.execute(
        """
        SELECT COUNT(*) AS count
        FROM ADOPTION_RECORD
        WHERE adoption_date LIKE ?
        """,
        (f"{month_prefix}%",),
    ).fetchone()["count"]

    status_rows = conn.execute(
        """
        SELECT status, COUNT(*) AS count
        FROM PET
        GROUP BY status
        ORDER BY count DESC, status
        """
    ).fetchall()
    status_overview = [
        {
            "status": pet_status_label(row["status"]),
            "statusLabel": pet_status_label(row["status"]),
            "rawStatus": row["status"],
            "count": row["count"],
            "share": round(row["count"] * 100 / total_pets) if total_pets else 0,
        }
        for row in status_rows
    ]

    activities = fetch_recent_activity(conn)
    return {
        "timezone": APP_TIMEZONE_NAME,
        "stats": {
            "totalPets": total_pets,
            "shelterCount": shelter_count,
            "availablePets": available_count,
            "pendingApplications": pending_count,
            "monthlyAdoptions": month_adoptions,
        },
        "statusOverview": status_overview,
        "activities": activities,
    }


def fetch_recent_activity(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        """
        SELECT
            strftime('%Y-%m-%d %H:%M', event_date) AS formatted_date,
            event_type,
            event_id,
            text,
            dot_class
        FROM SYSTEM_LOG
        WHERE event_date IS NOT NULL
        ORDER BY datetime(event_date) DESC, log_id DESC
        """
    ).fetchall()
    return [
        {
            "eventType": row["event_type"],
            "eventId": row["event_id"],
            "text": row["text"],
            "time": row["formatted_date"],
            "dotClass": row["dot_class"],
        }
        for row in rows
    ]


def log_activity(
    conn: sqlite3.Connection,
    event_type: str,
    event_id: int | None,
    text: str,
    dot_class: str = "dot-blue",
    sort_priority: int = 50,
    event_date: str | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO SYSTEM_LOG (event_date, event_type, event_id, text, dot_class, sort_priority)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (event_date or local_now_iso(), event_type, event_id, text, dot_class, sort_priority),
    )


def resource_activity_context(conn: sqlite3.Connection, resource: str, item_id: int) -> dict[str, Any]:
    if resource == "shelters":
        row = conn.execute("SELECT name FROM SHELTER WHERE shelter_id = ?", (item_id,)).fetchone()
        return {"code": display_id("S", item_id), "name": row["name"] if row else display_id("S", item_id)}
    if resource == "pets":
        row = conn.execute("SELECT name FROM PET WHERE pet_id = ?", (item_id,)).fetchone()
        return {"code": display_id("P", item_id), "name": row["name"] if row else display_id("P", item_id)}
    if resource == "applicants":
        row = conn.execute("SELECT full_name FROM APPLICANT WHERE applicant_id = ?", (item_id,)).fetchone()
        return {"code": display_id("A", item_id), "name": row["full_name"] if row else display_id("A", item_id)}
    if resource == "volunteers":
        row = conn.execute("SELECT full_name FROM VOLUNTEER WHERE volunteer_id = ?", (item_id,)).fetchone()
        return {"code": display_id("VLT", item_id), "name": row["full_name"] if row else display_id("VLT", item_id)}
    if resource == "medical-records":
        row = conn.execute(
            """
            SELECT m.record_type, p.name AS pet_name
            FROM MEDICAL_RECORD m
            LEFT JOIN PET p ON m.pet_id = p.pet_id
            WHERE m.record_id = ?
            """,
            (item_id,),
        ).fetchone()
        return {
            "code": display_id("MR", item_id),
            "pet": row["pet_name"] if row else "unknown pet",
            "detail": row["record_type"] if row and row["record_type"] else "",
        }
    if resource == "vaccinations":
        row = conn.execute(
            """
            SELECT v.vaccine_name, p.name AS pet_name
            FROM VACCINATION v
            LEFT JOIN PET p ON v.pet_id = p.pet_id
            WHERE v.vaccination_id = ?
            """,
            (item_id,),
        ).fetchone()
        return {
            "code": display_id("V", item_id),
            "pet": row["pet_name"] if row else "unknown pet",
            "detail": row["vaccine_name"] if row and row["vaccine_name"] else "",
        }
    if resource == "care-assignments":
        row = conn.execute(
            """
            SELECT v.full_name AS volunteer_name, p.name AS pet_name
            FROM CARE_ASSIGNMENT c
            LEFT JOIN VOLUNTEER v ON c.volunteer_id = v.volunteer_id
            LEFT JOIN PET p ON c.pet_id = p.pet_id
            WHERE c.assignment_id = ?
            """,
            (item_id,),
        ).fetchone()
        return {
            "code": display_id("CA", item_id),
            "volunteer": row["volunteer_name"] if row else "unknown volunteer",
            "pet": row["pet_name"] if row else "unknown pet",
        }
    if resource == "follow-ups":
        row = conn.execute(
            """
            SELECT p.name AS pet_name
            FROM FOLLOW_UP f
            LEFT JOIN ADOPTION_RECORD ar ON f.adoption_id = ar.adoption_id
            LEFT JOIN ADOPTION_APPLICATION aa ON ar.application_id = aa.application_id
            LEFT JOIN PET p ON aa.pet_id = p.pet_id
            WHERE f.followup_id = ?
            """,
            (item_id,),
        ).fetchone()
        return {"code": display_id("FU", item_id), "pet": row["pet_name"] if row else "unknown pet"}
    return {"code": str(item_id), "name": str(item_id)}


def resource_activity_text(conn: sqlite3.Connection, resource: str, item_id: int, action: str) -> str:
    ctx = resource_activity_context(conn, resource, item_id)
    if resource == "shelters":
        return f"Shelter {action}: {ctx['name']} ({ctx['code']})"
    if resource == "pets":
        if action == "created":
            return f"Pet intake recorded for {ctx['name']} ({ctx['code']})"
        return f"Pet profile {action}: {ctx['name']} ({ctx['code']})"
    if resource == "applicants":
        return f"Applicant profile {action} for {ctx['name']} ({ctx['code']})"
    if resource == "volunteers":
        return f"Volunteer profile {action}: {ctx['name']} ({ctx['code']})"
    if resource == "medical-records":
        detail = f" ({ctx['detail']})" if ctx["detail"] else ""
        verb = "added" if action == "created" else action
        return f"Medical record {verb} for {ctx['pet']}{detail} ({ctx['code']})"
    if resource == "vaccinations":
        detail = f" ({ctx['detail']})" if ctx["detail"] else ""
        verb = "added" if action == "created" else action
        return f"Vaccination record {verb} for {ctx['pet']}{detail} ({ctx['code']})"
    if resource == "care-assignments":
        verb = "scheduled" if action == "created" else action
        return f"Care assignment {verb} for {ctx['volunteer']} with {ctx['pet']} ({ctx['code']})"
    if resource == "follow-ups":
        verb = "completed" if action == "created" else action
        return f"Follow-up {verb} for {ctx['pet']} ({ctx['code']})"
    return f"{resource} {action}: {ctx['code']}"


def log_resource_activity(conn: sqlite3.Connection, resource: str, item_id: int, action: str) -> None:
    dot_class = {"created": "dot-blue", "updated": "dot-amber", "removed": "dot-red"}[action]
    sort_priority = {"created": 50, "updated": 30, "removed": 5}[action]
    log_activity(
        conn,
        RESOURCE_EVENT_TYPES[resource],
        item_id,
        resource_activity_text(conn, resource, item_id, action),
        dot_class,
        sort_priority,
    )


def application_activity_context(conn: sqlite3.Connection, application_id: int) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT aa.application_id, aa.status, ap.full_name AS applicant_name, p.name AS pet_name
        FROM ADOPTION_APPLICATION aa
        JOIN APPLICANT ap ON aa.applicant_id = ap.applicant_id
        JOIN PET p ON aa.pet_id = p.pet_id
        WHERE aa.application_id = ?
        """,
        (application_id,),
    ).fetchone()
    if not row:
        return {
            "code": display_id("APP", application_id),
            "status": "",
            "applicant": "unknown applicant",
            "pet": "unknown pet",
        }
    return {
        "code": display_id("APP", application_id),
        "status": row["status"],
        "applicant": row["applicant_name"],
        "pet": row["pet_name"],
    }


def log_application_submitted(conn: sqlite3.Connection, application_id: int) -> None:
    ctx = application_activity_context(conn, application_id)
    log_activity(
        conn,
        "application",
        application_id,
        f"Application {ctx['code']} submitted for {ctx['pet']} by {ctx['applicant']}",
        "dot-amber",
        40,
    )


def log_application_status_update(
    conn: sqlite3.Connection, application_id: int, status: str, note: str = ""
) -> None:
    ctx = application_activity_context(conn, application_id)
    suffix = f" ({note})" if note else ""
    log_activity(
        conn,
        "application_review",
        application_id,
        f"Application {ctx['code']} status updated to {status}{suffix}",
        "dot-amber",
        30,
    )


def log_pet_status_update(conn: sqlite3.Connection, pet_id: int, status: str, reason: str = "") -> None:
    row = conn.execute("SELECT name FROM PET WHERE pet_id = ?", (pet_id,)).fetchone()
    name = row["name"] if row else display_id("P", pet_id)
    suffix = f" ({reason})" if reason else ""
    log_activity(
        conn,
        "pet",
        pet_id,
        f"Pet status updated to {pet_status_label(status)} for {name}{suffix}",
        "dot-amber",
        35,
    )


def fetch_analytics(conn: sqlite3.Connection) -> dict:
    occupancy_rows = conn.execute(
        """
        SELECT
            s.shelter_id,
            s.name AS shelter_name,
            s.capacity,
            COUNT(p.pet_id) AS current_pet_count,
            ROUND(COUNT(p.pet_id) * 100.0 / s.capacity, 2) AS occupancy_rate
        FROM SHELTER s
        LEFT JOIN PET p
            ON s.shelter_id = p.shelter_id
           AND lower(p.status) IN ('available', 'reserved', 'medical_hold')
        GROUP BY s.shelter_id, s.name, s.capacity
        ORDER BY occupancy_rate DESC
        """
    ).fetchall()

    long_stay_rows = conn.execute(
        """
        SELECT
            pet_id,
            name,
            species,
            breed,
            shelter_id,
            intake_date,
            CAST(julianday(?) - julianday(date(intake_date)) AS INTEGER) AS days_in_shelter
        FROM PET
        WHERE lower(status) = 'available'
        ORDER BY days_in_shelter DESC
        LIMIT 10
        """,
        (local_today_iso(),),
    ).fetchall()

    housing_rows = conn.execute(
        """
        SELECT
            ap.housing_type,
            COUNT(a.application_id) AS total_applications,
            SUM(CASE WHEN a.status = 'Approved' THEN 1 ELSE 0 END) AS approved_count,
            SUM(CASE WHEN a.status = 'Rejected' THEN 1 ELSE 0 END) AS rejected_count,
            ROUND(
                SUM(CASE WHEN a.status = 'Approved' THEN 1 ELSE 0 END) * 100.0
                / COUNT(a.application_id),
                2
            ) AS approval_rate
        FROM APPLICANT ap
        JOIN ADOPTION_APPLICATION a ON ap.applicant_id = a.applicant_id
        GROUP BY ap.housing_type
        ORDER BY approval_rate DESC
        """
    ).fetchall()

    species_rows = conn.execute(
        """
        SELECT
            p.species,
            COUNT(aa.application_id) AS total_applications,
            COUNT(ar.adoption_id) AS successful_adoptions,
            ROUND(COUNT(ar.adoption_id) * 100.0 / COUNT(aa.application_id), 2) AS adoption_success_rate
        FROM PET p
        JOIN ADOPTION_APPLICATION aa ON p.pet_id = aa.pet_id
        LEFT JOIN ADOPTION_RECORD ar ON aa.application_id = ar.application_id
        GROUP BY p.species
        ORDER BY total_applications DESC, adoption_success_rate DESC
        """
    ).fetchall()

    workload_rows = conn.execute(
        """
        SELECT
            v.volunteer_id,
            v.full_name,
            COUNT(c.assignment_id) AS total_assignments,
            SUM(CASE WHEN c.status = 'Completed' THEN 1 ELSE 0 END) AS completed_tasks,
            SUM(CASE WHEN c.status = 'Cancelled' THEN 1 ELSE 0 END) AS cancelled_tasks,
            SUM(CASE WHEN c.status = 'Scheduled' THEN 1 ELSE 0 END) AS scheduled_tasks
        FROM VOLUNTEER v
        LEFT JOIN CARE_ASSIGNMENT c ON v.volunteer_id = c.volunteer_id
        GROUP BY v.volunteer_id, v.full_name
        ORDER BY completed_tasks DESC, total_assignments DESC
        """
    ).fetchall()

    followup_rows = conn.execute(
        """
        SELECT
            f.result_status,
            COUNT(f.followup_id) AS total_followups
        FROM FOLLOW_UP f
        GROUP BY f.result_status
        ORDER BY total_followups DESC
        """
    ).fetchall()

    return {
        "occupancy": [
            {
                "shelterId": row["shelter_id"],
                "shelter": row["shelter_name"],
                "capacity": row["capacity"],
                "currentPetCount": row["current_pet_count"],
                "occupancyRate": row["occupancy_rate"],
            }
            for row in occupancy_rows
        ],
        "longStayPets": [
            {
                "petId": row["pet_id"],
                "id": display_id("P", row["pet_id"]),
                "name": row["name"],
                "species": row["species"],
                "breed": row["breed"] or "",
                "shelterId": row["shelter_id"],
                "intakeDate": db_date_str(row["intake_date"]),
                "daysInShelter": row["days_in_shelter"],
            }
            for row in long_stay_rows
        ],
        "housingApproval": [
            {
                "housingType": row["housing_type"] or "Unknown",
                "totalApplications": row["total_applications"],
                "approvedCount": row["approved_count"] or 0,
                "rejectedCount": row["rejected_count"] or 0,
                "approvalRate": row["approval_rate"] or 0,
            }
            for row in housing_rows
        ],
        "speciesDemand": [
            {
                "species": row["species"],
                "totalApplications": row["total_applications"],
                "successfulAdoptions": row["successful_adoptions"],
                "adoptionSuccessRate": row["adoption_success_rate"] or 0,
            }
            for row in species_rows
        ],
        "volunteerWorkload": [
            {
                "volunteerId": row["volunteer_id"],
                "id": display_id("VLT", row["volunteer_id"]),
                "name": row["full_name"],
                "totalAssignments": row["total_assignments"],
                "completedTasks": row["completed_tasks"] or 0,
                "cancelledTasks": row["cancelled_tasks"] or 0,
                "scheduledTasks": row["scheduled_tasks"] or 0,
            }
            for row in workload_rows
        ],
        "followupOutcomes": [
            {
                "resultStatus": row["result_status"] or "Unknown",
                "totalFollowups": row["total_followups"],
            }
            for row in followup_rows
        ],
    }


def fetch_check_rows(conn: sqlite3.Connection, sql: str) -> dict:
    rows = [dict(row) for row in conn.execute(sql).fetchall()]
    return {
        "count": len(rows),
        "sampleRows": rows[:5],
    }


def fetch_integrity_audit(conn: sqlite3.Connection) -> list[dict]:
    checks = [
        {
            "id": "invalid_pet_status",
            "title": "PET.status domain validation",
            "severity": "high",
            "enforcementLayer": "schema",
            "llmRationale": "An LLM schema review flagged free-text status fields as a common source of inconsistent workflow states.",
            "sql": """
                SELECT pet_id, name, status
                FROM PET
                WHERE lower(status) NOT IN ('available', 'reserved', 'adopted', 'medical_hold')
            """,
            "refinement": "Schema CHECK guarantees the allowed pet workflow states.",
        },
        {
            "id": "invalid_application_status",
            "title": "ADOPTION_APPLICATION.status domain validation",
            "severity": "high",
            "enforcementLayer": "schema",
            "llmRationale": "The review identified application status as a controlled workflow attribute, not arbitrary text.",
            "sql": """
                SELECT application_id, status
                FROM ADOPTION_APPLICATION
                WHERE status NOT IN ('Under Review', 'Approved', 'Rejected')
            """,
            "refinement": "Schema CHECK constrains the application review workflow to three valid states.",
        },
        {
            "id": "invalid_structured_domains",
            "title": "Structured operational domain validation",
            "severity": "medium",
            "enforcementLayer": "schema",
            "llmRationale": "The LLM review recommended turning repeated dropdown values into durable domain constraints rather than relying on display text.",
            "sql": """
                SELECT 'PET.species' AS field_name, pet_id AS record_id, species AS value
                FROM PET
                WHERE species NOT IN ('Dog', 'Cat', 'Rabbit', 'Bird')
                UNION ALL
                SELECT 'PET.sex', pet_id, sex
                FROM PET
                WHERE sex IS NOT NULL AND sex NOT IN ('Male', 'Female', 'Unknown')
                UNION ALL
                SELECT 'MEDICAL_RECORD.record_type', record_id, record_type
                FROM MEDICAL_RECORD
                WHERE record_type IS NOT NULL
                  AND record_type NOT IN ('Check-up', 'Surgery', 'Treatment', 'Injury', 'Dental')
                UNION ALL
                SELECT 'CARE_ASSIGNMENT.status', assignment_id, status
                FROM CARE_ASSIGNMENT
                WHERE status IS NULL OR status NOT IN ('Scheduled', 'Completed', 'Cancelled')
                UNION ALL
                SELECT 'CARE_ASSIGNMENT.shift', assignment_id, shift
                FROM CARE_ASSIGNMENT
                WHERE shift IS NULL OR shift NOT IN ('Morning', 'Afternoon', 'Evening')
                UNION ALL
                SELECT 'CARE_ASSIGNMENT.task_type', assignment_id, task_type
                FROM CARE_ASSIGNMENT
                WHERE task_type IS NULL
                  OR task_type NOT IN ('Cleaning', 'Feeding', 'Grooming', 'Socializing', 'Walking', 'Medical support')
                UNION ALL
                SELECT 'FOLLOW_UP.followup_type', followup_id, followup_type
                FROM FOLLOW_UP
                WHERE followup_type IS NULL OR followup_type NOT IN ('Phone Check', 'Home Visit', 'Vet Check')
                UNION ALL
                SELECT 'FOLLOW_UP.result_status', followup_id, result_status
                FROM FOLLOW_UP
                WHERE result_status IS NULL
                  OR result_status NOT IN ('Excellent', 'Good', 'Satisfactory', 'Needs Improvement')
            """,
            "refinement": "Schema CHECK constraints now back the controlled vocabularies used by the UI and analytics.",
        },
        {
            "id": "invalid_housing_type",
            "title": "Applicant housing type domain validation",
            "severity": "medium",
            "enforcementLayer": "application",
            "llmRationale": "Housing type drives analytics and review context, so the application keeps it within a controlled set even though the ER model leaves it as a free attribute.",
            "sql": """
                SELECT 'APPLICANT.housing_type' AS field_name, applicant_id AS record_id, housing_type AS value
                FROM APPLICANT
                WHERE housing_type IS NOT NULL
                  AND housing_type NOT IN (
                    'Apartment', 'Condo', 'House', 'Townhouse',
                    'House with garden', 'House without garden', 'Shared housing'
                  )
            """,
            "refinement": "CRUD validation keeps housing_type aligned with the UI-controlled vocabulary used by analytics.",
        },
        {
            "id": "invalid_email_format",
            "title": "Email format validation",
            "severity": "medium",
            "enforcementLayer": "application",
            "llmRationale": "Email fields should remain syntactically usable for contact and review workflows even though uniqueness is not part of the formal schema design.",
            "sql": """
                SELECT 'APPLICANT.email' AS field_name, applicant_id AS record_id, email AS value
                FROM APPLICANT
                WHERE email IS NOT NULL
                  AND email != ''
                  AND email NOT LIKE '%_@_%._%'
                UNION ALL
                SELECT 'VOLUNTEER.email', volunteer_id, email
                FROM VOLUNTEER
                WHERE email IS NOT NULL
                  AND email != ''
                  AND email NOT LIKE '%_@_%._%'
            """,
            "refinement": "Application validation rejects malformed email values without introducing new uniqueness semantics.",
        },
        {
            "id": "capacity_exceeded",
            "title": "Shelter capacity consistency",
            "severity": "high",
            "enforcementLayer": "application",
            "llmRationale": "Capacity is a business rule that cannot be fully expressed by foreign keys alone.",
            "sql": """
                SELECT s.shelter_id, s.name, s.capacity, COUNT(p.pet_id) AS active_pet_count
                FROM SHELTER s
                JOIN PET p ON s.shelter_id = p.shelter_id
                WHERE lower(p.status) IN ('available', 'reserved', 'medical_hold')
                GROUP BY s.shelter_id, s.name, s.capacity
                HAVING COUNT(p.pet_id) > s.capacity
            """,
            "refinement": "The application blocks pet intake and shelter edits that would exceed capacity; the audit catches drift from direct SQL writes.",
        },
        {
            "id": "schema_level_temporal_ordering",
            "title": "Schema-level temporal consistency",
            "severity": "high",
            "enforcementLayer": "schema",
            "llmRationale": "Several same-row date relationships can be hardened directly in SQLite without changing the ER structure.",
            "sql": """
                SELECT 'PET.birth_after_intake' AS issue, pet_id AS record_id, estimated_birth_date AS first_date, intake_date AS second_date
                FROM PET
                WHERE estimated_birth_date IS NOT NULL
                  AND date(estimated_birth_date) > date(intake_date)
                UNION ALL
                SELECT 'APPLICATION.review_before_apply', application_id, reviewed_date, application_date
                FROM ADOPTION_APPLICATION
                WHERE reviewed_date IS NOT NULL
                  AND date(reviewed_date) < date(application_date)
                UNION ALL
                SELECT 'VACCINATION.due_before_given', vaccination_id, next_due_date, vaccination_date
                FROM VACCINATION
                WHERE next_due_date IS NOT NULL
                  AND date(next_due_date) < date(vaccination_date)
            """,
            "refinement": "SQLite CHECK constraints now enforce the intra-row date relationships.",
        },
        {
            "id": "cross_table_temporal_ordering",
            "title": "Cross-table temporal consistency",
            "severity": "high",
            "enforcementLayer": "application",
            "llmRationale": "Cross-table timelines still need application-side validation because SQLite CHECK constraints cannot compare parent and child rows directly.",
            "sql": """
                SELECT 'MEDICAL.before_intake' AS issue, m.record_id AS record_id, m.visit_date AS first_date, p.intake_date AS second_date
                FROM MEDICAL_RECORD m
                JOIN PET p ON m.pet_id = p.pet_id
                WHERE date(m.visit_date) < date(p.intake_date)
                UNION ALL
                SELECT 'VACCINATION.before_intake', v.vaccination_id, v.vaccination_date, p.intake_date
                FROM VACCINATION v
                JOIN PET p ON v.pet_id = p.pet_id
                WHERE date(v.vaccination_date) < date(p.intake_date)
                UNION ALL
                SELECT 'FOLLOW_UP.before_adoption', f.followup_id, f.followup_date, ar.adoption_date
                FROM FOLLOW_UP f
                JOIN ADOPTION_RECORD ar ON f.adoption_id = ar.adoption_id
                WHERE date(f.followup_date) < date(ar.adoption_date)
                UNION ALL
                SELECT 'CARE.after_adoption', c.assignment_id, c.assignment_date, ar.adoption_date
                FROM CARE_ASSIGNMENT c
                JOIN ADOPTION_APPLICATION aa ON c.pet_id = aa.pet_id AND aa.status = 'Approved'
                JOIN ADOPTION_RECORD ar ON aa.application_id = ar.application_id
                WHERE c.status != 'Cancelled'
                  AND date(c.assignment_date) >= date(ar.adoption_date)
            """,
            "refinement": "CRUD validation enforces pet intake, follow-up, and care-assignment timelines across related tables.",
        },
        {
            "id": "application_before_pet_intake",
            "title": "Application cannot predate pet intake",
            "severity": "high",
            "enforcementLayer": "application",
            "llmRationale": "Applications for a pet that has not yet entered the shelter create an invalid operational timeline.",
            "sql": """
                SELECT a.application_id, a.pet_id, a.application_date, p.intake_date
                FROM ADOPTION_APPLICATION a
                JOIN PET p ON a.pet_id = p.pet_id
                WHERE date(a.application_date) < date(p.intake_date)
            """,
            "refinement": "Application creation and pet intake edits now reject timelines that would place an application before intake.",
        },
        {
            "id": "cross_shelter_care_assignment",
            "title": "Care assignments must stay within one shelter",
            "severity": "high",
            "enforcementLayer": "application",
            "llmRationale": "Volunteers and pets each belong to exactly one shelter, so cross-shelter care assignments indicate broken relationship semantics.",
            "sql": """
                SELECT c.assignment_id, c.volunteer_id, v.shelter_id AS volunteer_shelter_id, c.pet_id, p.shelter_id AS pet_shelter_id
                FROM CARE_ASSIGNMENT c
                JOIN VOLUNTEER v ON c.volunteer_id = v.volunteer_id
                JOIN PET p ON c.pet_id = p.pet_id
                WHERE v.shelter_id != p.shelter_id
            """,
            "refinement": "The application blocks cross-shelter assignments and blocks shelter edits that would retroactively break existing assignments.",
        },
        {
            "id": "care_assignment_before_volunteer_join",
            "title": "Care assignment cannot predate volunteer join date",
            "severity": "medium",
            "enforcementLayer": "application",
            "llmRationale": "Assignments before a volunteer officially joins the shelter are timeline anomalies.",
            "sql": """
                SELECT c.assignment_id, c.assignment_date, v.volunteer_id, v.join_date
                FROM CARE_ASSIGNMENT c
                JOIN VOLUNTEER v ON c.volunteer_id = v.volunteer_id
                WHERE v.join_date IS NOT NULL
                  AND date(c.assignment_date) < date(v.join_date)
            """,
            "refinement": "The application checks volunteer join dates during assignment creation and volunteer edits.",
        },
        {
            "id": "reserved_without_pending_application",
            "title": "Reserved pet must have a pending application",
            "severity": "medium",
            "enforcementLayer": "application",
            "llmRationale": "Workflow consistency requires reserved pets to be linked to an active adoption review.",
            "sql": """
                SELECT p.pet_id, p.name, p.status
                FROM PET p
                WHERE lower(p.status) = 'reserved'
                  AND NOT EXISTS (
                    SELECT 1
                    FROM ADOPTION_APPLICATION a
                    WHERE a.pet_id = p.pet_id
                      AND a.status = 'Under Review'
                  )
            """,
            "refinement": "Application review updates PET.status transactionally so the reserve state remains workflow-derived.",
        },
        {
            "id": "pending_application_pet_not_reserved",
            "title": "Pending application should reserve the pet",
            "severity": "medium",
            "enforcementLayer": "application",
            "llmRationale": "The LLM review connected application workflow state to pet availability state.",
            "sql": """
                SELECT a.application_id, p.pet_id, p.name, p.status
                FROM ADOPTION_APPLICATION a
                JOIN PET p ON a.pet_id = p.pet_id
                WHERE a.status = 'Under Review'
                  AND lower(p.status) != 'reserved'
            """,
            "refinement": "Application creation and review keep PET.status aligned with the active review queue.",
        },
        {
            "id": "adopted_pet_without_approved_application",
            "title": "Adopted pet must have an approved application",
            "severity": "high",
            "enforcementLayer": "application",
            "llmRationale": "Pet status should be derived from the adoption workflow, not edited independently.",
            "sql": """
                SELECT p.pet_id, p.name, p.status
                FROM PET p
                WHERE lower(p.status) = 'adopted'
                  AND NOT EXISTS (
                    SELECT 1
                    FROM ADOPTION_APPLICATION a
                    WHERE a.pet_id = p.pet_id
                      AND a.status = 'Approved'
                  )
            """,
            "refinement": "Direct PET edits cannot produce adopted status without an approved application.",
        },
        {
            "id": "adoption_record_without_approved_application",
            "title": "Adoption record must reference an approved application",
            "severity": "high",
            "enforcementLayer": "application",
            "llmRationale": "A final adoption should not exist unless the corresponding application reached Approved.",
            "sql": """
                SELECT ar.adoption_id, ar.application_id, aa.status
                FROM ADOPTION_RECORD ar
                JOIN ADOPTION_APPLICATION aa ON ar.application_id = aa.application_id
                WHERE aa.status != 'Approved'
            """,
            "refinement": "The approval workflow inserts adoption records only after the application reaches Approved.",
        },
        {
            "id": "approved_application_without_adoption_record",
            "title": "Approved application must generate an adoption record",
            "severity": "high",
            "enforcementLayer": "application",
            "llmRationale": "The ER relationship results_in means an approved adoption decision should produce the final ADOPTION_RECORD used for follow-ups.",
            "sql": """
                SELECT aa.application_id, aa.pet_id, aa.reviewed_date
                FROM ADOPTION_APPLICATION aa
                LEFT JOIN ADOPTION_RECORD ar ON aa.application_id = ar.application_id
                WHERE aa.status = 'Approved'
                  AND ar.adoption_id IS NULL
            """,
            "refinement": "Application approval inserts the adoption record in the same write transaction, and startup now audits instead of silently repairing drift.",
        },
        {
            "id": "multiple_approved_applications_for_one_pet",
            "title": "Only one application may be finally approved for a pet",
            "severity": "high",
            "enforcementLayer": "application",
            "llmRationale": "The ER rules allow multiple applications over time, but only one can end as the accepted adoption for a pet.",
            "sql": """
                SELECT pet_id, COUNT(*) AS approved_application_count
                FROM ADOPTION_APPLICATION
                WHERE status = 'Approved'
                GROUP BY pet_id
                HAVING COUNT(*) > 1
            """,
            "refinement": "Approval checks for an existing approved application for the same pet inside a serialized write transaction.",
        },
        {
            "id": "multiple_adoption_records_for_one_application",
            "title": "One application can create at most one adoption record",
            "severity": "high",
            "enforcementLayer": "schema",
            "llmRationale": "The ER relationship between AdoptionApplication and AdoptionRecord is 1:0..1, so duplicate final records are invalid.",
            "sql": """
                SELECT application_id, COUNT(*) AS adoption_record_count
                FROM ADOPTION_RECORD
                GROUP BY application_id
                HAVING COUNT(*) > 1
            """,
            "refinement": "A UNIQUE constraint on ADOPTION_RECORD.application_id now hardens the 1:0..1 relationship in SQLite itself.",
        },
        {
            "id": "duplicate_active_applications",
            "title": "Avoid multiple pending applications by the same applicant for the same pet",
            "severity": "low",
            "enforcementLayer": "application",
            "llmRationale": "The LLM review suggested detecting duplicate active workflow records that could confuse staff decisions even when they are not formal ER violations.",
            "sql": """
                SELECT applicant_id, pet_id, COUNT(*) AS active_application_count
                FROM ADOPTION_APPLICATION
                WHERE status = 'Under Review'
                GROUP BY applicant_id, pet_id
                HAVING COUNT(*) > 1
            """,
            "refinement": "The application rejects duplicate active applicant-pet reviews without changing the underlying ER design.",
        },
    ]

    audited = []
    for check in checks:
        result = fetch_check_rows(conn, check["sql"])
        audited.append(
            {
                **{key: value for key, value in check.items() if key != "sql"},
                "sql": " ".join(check["sql"].split()),
                "findingCount": result["count"],
                "sampleRows": result["sampleRows"],
                "status": "Pass" if result["count"] == 0 else "Review",
            }
        )
    return audited


def assert_startup_integrity(conn: sqlite3.Connection) -> None:
    critical_failures = [
        check
        for check in fetch_integrity_audit(conn)
        if check["severity"] == "high" and check["findingCount"] > 0
    ]
    if not critical_failures:
        return
    summary = ", ".join(
        f"{check['id']}={check['findingCount']}" for check in critical_failures
    )
    raise RuntimeError(
        "Database startup audit failed with critical findings: "
        f"{summary}. Rebuild with --reset-db after fixing the source data or direct SQL drift."
    )


def fetch_llm_bonus(conn: sqlite3.Connection) -> dict:
    queries = load_query_registry()
    integrity_audit = fetch_integrity_audit(conn)
    issue_count = sum(check["findingCount"] for check in integrity_audit)
    prompt_cases = llm_sql_assistant.read_prompt_cases()
    prompt_results = llm_sql_assistant.read_prompt_results()

    architecture_refinements = [
        {
            "area": "Status domains",
            "originalDesign": "Core workflow and dropdown attributes were modeled as plain text columns.",
            "llmRefinement": "Harden the repeated operational vocabularies with SQLite CHECK constraints and keep the UI bound to raw values.",
            "implementation": "table.sql now constrains PET.status, ADOPTION_APPLICATION.status, CARE_ASSIGNMENT domains, FOLLOW_UP.result_status, and other structured enums.",
            "benefit": "Prevents spelling drift, keeps analytics stable, and makes database-level guarantees explicit.",
        },
        {
            "area": "Workflow integrity",
            "originalDesign": "Application and pet status could be updated independently.",
            "llmRefinement": "Treat PET.status as a workflow derivative that is updated inside the same transaction as application creation and review.",
            "implementation": "POST /api/applications and PATCH /api/applications/{id}/review keep PET, ADOPTION_APPLICATION, and ADOPTION_RECORD aligned in one transaction.",
            "benefit": "Removes UI-only assumptions and keeps the adoption workflow internally consistent.",
        },
        {
            "area": "Anomaly detection",
            "originalDesign": "Foreign keys catch missing parent rows but not business anomalies.",
            "llmRefinement": "Separate data-quality checks by enforcement layer so the report can explain which rules are hardened and which are monitored.",
            "implementation": "GET /api/llm-bonus returns executable audit checks with severity, enforcementLayer, finding counts, and sample rows.",
            "benefit": "Makes the bonus auditable and presentation-ready instead of relying on narrative claims.",
        },
        {
            "area": "Efficient access",
            "originalDesign": "Index recommendations existed as a standalone file but were not applied to the running database.",
            "llmRefinement": "Promote the documented indexes into the real startup path so performance guidance and runtime state match.",
            "implementation": "initialize_database now executes src/schema/indexing.sql for rebuilt and existing databases.",
            "benefit": "Aligns documentation, schema artifacts, and the running SQLite instance.",
        },
        {
            "area": "LLM query safety",
            "originalDesign": "Natural-language querying and MCP documentation implied safe routing, but mutation examples still lived beside query registry content.",
            "llmRefinement": "Expose only reviewed SELECT statements through one shared query registry for Web and MCP surfaces.",
            "implementation": "query_registry.py now loads only *_queries.sql read-only statements, and both /api/llm-query and mcp_server.py use that registry.",
            "benefit": "Turns the bonus from a documentation claim into a verifiable read-only execution model.",
        },
    ]

    prompt_patterns = [
        {
            "pattern": "Intent first",
            "prompt": "Show pets whose vaccination is due soon.",
            "routingLogic": "Maps keywords such as vaccination due or vaccine soon to the vaccination reminder query.",
            "expectedQuery": "view_pets_whose_vaccination_due_date_is_approaching",
        },
        {
            "pattern": "Schema-grounded entity wording",
            "prompt": "Analyze adoption approval rate by applicant housing type.",
            "routingLogic": "Mentions housing type and approval rate, so it maps to the housing approval analytical query.",
            "expectedQuery": "analyze_adoption_application_results_by_housing_type",
        },
        {
            "pattern": "Metric-oriented question",
            "prompt": "Which volunteers completed the most care tasks?",
            "routingLogic": "Mentions volunteers and completed tasks, so it maps to volunteer workload analysis.",
            "expectedQuery": "analyze_volunteer_workload_based_on_care_assignments",
        },
        {
            "pattern": "Safety instruction",
            "prompt": "List available pets for adoption.",
            "routingLogic": "The assistant chooses a reviewed SELECT query instead of inventing SQL.",
            "expectedQuery": "view_all_pets_that_are_currently_available_for_adoption",
        },
    ]

    prompt_engineering_methods = [
        {
            "method": "zero_shot",
            "purpose": "Baseline prompt with only the user question, output contract, and strict read-only rule.",
            "bestFor": "Quick demonstrations and measuring how much schema context improves accuracy.",
        },
        {
            "method": "schema_grounded",
            "purpose": "Adds live SQLite table, column, key, index, and domain context before SQL generation.",
            "bestFor": "Default production demo path because it reduces invented table and column names.",
        },
        {
            "method": "few_shot",
            "purpose": "Adds reviewed operational and analytical SQL examples from the official query registry.",
            "bestFor": "Teaching the model the expected SQLite style and result-shaping conventions.",
        },
        {
            "method": "self_check_repair",
            "purpose": "Asks GLM to self-check before returning SQL and allows one SQLite-error-guided repair attempt.",
            "bestFor": "Harder analytical prompts where a first draft may need syntax or join repair.",
        },
    ]

    refined_constraints = [
        {
            "name": "Pet status CHECK",
            "sql": "CHECK (status IN ('available', 'reserved', 'adopted', 'medical_hold'))",
            "reason": "Hardens the official pet workflow states at the SQLite layer.",
        },
        {
            "name": "Application status CHECK",
            "sql": "CHECK (status IN ('Under Review', 'Approved', 'Rejected'))",
            "reason": "Hardens the adoption review state machine.",
        },
        {
            "name": "Adoption record uniqueness",
            "sql": "application_id INT NOT NULL UNIQUE",
            "reason": "Preserves the ER rule that one application can generate at most one adoption record.",
        },
        {
            "name": "Temporal row checks",
            "sql": "CHECK (reviewed_date IS NULL OR reviewed_date >= application_date), CHECK (next_due_date IS NULL OR next_due_date >= vaccination_date)",
            "reason": "Makes same-row date order rules explicit in the database.",
        },
        {
            "name": "Operational domain checks",
            "sql": "CHECK constraints for care-assignment domains, medical record type, pet species/sex, and follow-up result status",
            "reason": "Stabilizes UI dropdown data and analytics aggregations.",
        },
        {
            "name": "Runtime indexes",
            "sql": "CREATE INDEX IF NOT EXISTS ... from src/schema/indexing.sql",
            "reason": "Ensures the documented index set is actually applied to the running SQLite database.",
        },
        {
            "name": "Startup audit gate",
            "sql": "Critical high-severity findings abort startup instead of being silently repaired",
            "reason": "Keeps the generated SQLite database honest and presentation-ready.",
        },
    ]

    return {
        "summary": {
            "bonusGoal": "LLM + Database",
            "architectureRefinementCount": len(architecture_refinements),
            "integrityCheckCount": len(integrity_audit),
            "openFindingCount": issue_count,
            "safeReadOnlyQueryCount": len(queries),
            "promptCaseCount": len(prompt_cases),
            "promptMethodCount": len(prompt_engineering_methods),
            "method": "LLM-assisted design review plus GLM prompt-to-SQL generation guarded by read-only SQL validation.",
        },
        "architectureRefinements": architecture_refinements,
        "refinedConstraints": refined_constraints,
        "integrityAudit": integrity_audit,
        "promptPatterns": prompt_patterns,
        "promptEngineeringMethods": prompt_engineering_methods,
        "promptEvaluation": {
            "generatedAt": prompt_results.get("generatedAt"),
            "summary": prompt_results.get("summary", {}),
            "methods": prompt_results.get("methods", []),
            "sampleCases": prompt_cases[:6],
        },
        "llmReadiness": {
            "provider": "zhipu-glm",
            "defaultModel": llm_sql_assistant.DEFAULT_MODEL,
            "apiKeyConfigured": bool(llm_sql_assistant.LlmConfig.from_env().api_key),
            "generatedSqlEndpoint": "POST /api/llm-generate-query",
            "reviewedTemplateEndpoint": "POST /api/llm-query",
        },
        "queryCatalog": [
            {
                "name": query.name,
                "title": query.title,
                "description": query.description,
                "category": query.category,
                "readOnly": True,
            }
            for query in queries
        ],
    }


def run_llm_query(conn: sqlite3.Connection, payload: dict) -> dict:
    prompt = (payload.get("prompt") or "").strip()
    if not prompt:
        raise ApiError(HTTPStatus.BAD_REQUEST, "Prompt is required.")

    queries = load_query_registry()
    if not queries:
        raise ApiError(HTTPStatus.INTERNAL_SERVER_ERROR, "No read-only queries are registered.")

    query = match_query_from_prompt(prompt, queries)
    rows = execute_read_only_query(conn, query)
    return {
        "prompt": prompt,
        "matchedQuery": {
            "name": query.name,
            "title": query.title,
            "description": query.description,
            "category": query.category,
            "readOnly": True,
            "sql": query.sql,
        },
        "rowCount": len(rows),
        "rows": rows[:50],
        "safetyModel": "The prompt is routed to a reviewed predefined SELECT query from the shared registry. Arbitrary generated SQL is not executed.",
    }


def run_llm_generate_query(conn: sqlite3.Connection, payload: dict, client=None) -> dict:
    try:
        return llm_sql_assistant.run_prompt_to_sql(conn, payload, DB_PATH, client=client)
    except llm_sql_assistant.LlmSqlError as exc:
        raise ApiError(exc.status, exc.message, exc.payload) from exc


def create_application(conn: sqlite3.Connection, payload: dict) -> dict:
    applicant_id = coerce_crud_value("applicantId", payload.get("applicantId"), "positive_int", True)
    pet_id = coerce_crud_value("petId", payload.get("petId"), "positive_int", True)
    reason = (payload.get("reason") or "").strip()
    housing_type = (
        coerce_crud_value("housingType", payload.get("housingType"), "housing_type", False)
        if payload.get("housingType")
        else ""
    )

    if not applicant_id or not pet_id or not reason:
        raise ApiError(HTTPStatus.BAD_REQUEST, "Applicant, pet, and reason are required.")

    applicant = conn.execute(
        "SELECT applicant_id, housing_type FROM APPLICANT WHERE applicant_id = ?", (applicant_id,)
    ).fetchone()
    if not applicant:
        raise ApiError(HTTPStatus.NOT_FOUND, "Applicant not found.")

    pet = conn.execute(
        "SELECT pet_id, status, intake_date FROM PET WHERE pet_id = ?", (pet_id,)
    ).fetchone()
    if not pet:
        raise ApiError(HTTPStatus.NOT_FOUND, "Pet not found.")
    if (pet["status"] or "").lower() != "available":
        raise ApiError(HTTPStatus.CONFLICT, "Only available pets can receive new applications.")
    if db_date(pet["intake_date"]) > local_today():
        raise ApiError(HTTPStatus.CONFLICT, "Pets cannot receive applications before their intake date.")
    existing_approved = approved_application_for_pet(conn, pet_id)
    if existing_approved:
        raise ApiError(
            HTTPStatus.CONFLICT,
            f"This pet already has an approved application ({display_id('APP', existing_approved['application_id'])}).",
        )
    existing_pending = pending_application_for_pet(conn, pet_id)
    if existing_pending:
        raise ApiError(
            HTTPStatus.CONFLICT,
            f"This pet already has a pending application ({display_id('APP', existing_pending['application_id'])}).",
        )
    duplicate = conn.execute(
        """
        SELECT application_id
        FROM ADOPTION_APPLICATION
        WHERE applicant_id = ?
          AND pet_id = ?
          AND status = 'Under Review'
        LIMIT 1
        """,
        (applicant_id, pet_id),
    ).fetchone()
    if duplicate:
        raise ApiError(
            HTTPStatus.CONFLICT,
            f"This applicant already has an active application for the pet ({display_id('APP', duplicate['application_id'])}).",
        )

    new_id = conn.execute(
        "SELECT COALESCE(MAX(application_id), 0) + 1 AS next_id FROM ADOPTION_APPLICATION"
    ).fetchone()["next_id"]

    if housing_type and housing_type != (applicant["housing_type"] or ""):
        conn.execute(
            "UPDATE APPLICANT SET housing_type = ? WHERE applicant_id = ?",
            (housing_type, applicant_id),
        )
        log_resource_activity(conn, "applicants", applicant_id, "updated")

    conn.execute(
        """
        INSERT INTO ADOPTION_APPLICATION (
            application_id,
            applicant_id,
            pet_id,
            application_date,
            status,
            reason,
            reviewed_date,
            reviewer_name,
            decision_note
        )
        VALUES (?, ?, ?, ?, 'Under Review', ?, NULL, NULL, NULL)
        """,
        (new_id, applicant_id, pet_id, local_now_iso(), reason),
    )
    log_application_submitted(conn, new_id)
    conn.execute("UPDATE PET SET status = 'reserved' WHERE pet_id = ?", (pet_id,))
    log_pet_status_update(conn, pet_id, "reserved", f"{display_id('APP', new_id)} submitted")

    return fetch_application(conn, new_id)


def review_application(conn: sqlite3.Connection, application_id: int, payload: dict) -> dict:
    decision = (payload.get("decision") or "").strip()
    note = (payload.get("note") or "").strip()
    reviewer = (payload.get("reviewerName") or "Staff (you)").strip()
    final_fee_raw = payload.get("finalAdoptionFee")
    handover_note = (payload.get("handoverNote") or "").strip()

    if decision not in {"Approved", "Rejected"}:
        raise ApiError(HTTPStatus.BAD_REQUEST, "Decision must be Approved or Rejected.")
    if not note:
        raise ApiError(HTTPStatus.BAD_REQUEST, "Decision note is required.")

    app = conn.execute(
        "SELECT * FROM ADOPTION_APPLICATION WHERE application_id = ?", (application_id,)
    ).fetchone()
    if not app:
        raise ApiError(HTTPStatus.NOT_FOUND, "Application not found.")
    if app["status"] != "Under Review":
        raise ApiError(HTTPStatus.CONFLICT, "Only pending applications can be reviewed.")
    linked_adoption = conn.execute(
        "SELECT adoption_id FROM ADOPTION_RECORD WHERE application_id = ?",
        (application_id,),
    ).fetchone()
    if linked_adoption and decision != "Approved":
        raise ApiError(
            HTTPStatus.CONFLICT,
            "This application already has an adoption record and cannot be rejected.",
        )

    if decision == "Approved":
        other_approved = approved_application_for_pet(
            conn, app["pet_id"], exclude_application_id=application_id
        )
        if other_approved:
            raise ApiError(
                HTTPStatus.CONFLICT,
                f"This pet already has an approved application ({display_id('APP', other_approved['application_id'])}).",
            )

    pet_before_review = conn.execute(
        "SELECT status FROM PET WHERE pet_id = ?", (app["pet_id"],)
    ).fetchone()["status"]

    conn.execute(
        """
        UPDATE ADOPTION_APPLICATION
        SET status = ?,
            reviewed_date = ?,
            reviewer_name = ?,
            decision_note = ?
        WHERE application_id = ?
        """,
        (decision, local_now_iso(), reviewer, note, application_id),
    )
    log_application_status_update(conn, application_id, decision)

    if decision == "Approved":
        final_fee = None
        if final_fee_raw is not None and final_fee_raw != "":
            try:
                final_fee = float(final_fee_raw)
            except (TypeError, ValueError) as exc:
                raise ApiError(HTTPStatus.BAD_REQUEST, "Final adoption fee must be a number.") from exc
            if final_fee < 0:
                raise ApiError(HTTPStatus.BAD_REQUEST, "Final adoption fee cannot be negative.")

        auto_closed = conn.execute(
            """
            SELECT application_id
            FROM ADOPTION_APPLICATION
            WHERE pet_id = ?
              AND application_id != ?
              AND status = 'Under Review'
            ORDER BY application_id
            """,
            (app["pet_id"], application_id),
        ).fetchall()
        existing_record = linked_adoption
        if not existing_record:
            adoption_id = conn.execute(
                "SELECT COALESCE(MAX(adoption_id), 0) + 1 AS next_id FROM ADOPTION_RECORD"
            ).fetchone()["next_id"]
            conn.execute(
                """
                INSERT INTO ADOPTION_RECORD (
                    adoption_id,
                    application_id,
                    adoption_date,
                    final_adoption_fee,
                    handover_note
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    adoption_id,
                    application_id,
                    local_now_iso(),
                    final_fee,
                    handover_note or note,
                ),
            )
            ctx = application_activity_context(conn, application_id)
            log_activity(
                conn,
                "adoption",
                adoption_id,
                f"Adoption finalized: {ctx['pet']} with {ctx['applicant']}",
                "dot-green",
                20,
            )
        conn.execute(
            """
            UPDATE ADOPTION_APPLICATION
            SET status = 'Rejected',
                reviewed_date = ?,
                reviewer_name = ?,
                decision_note = ?
            WHERE pet_id = ?
              AND application_id != ?
              AND status = 'Under Review'
            """,
            (
                local_now_iso(),
                reviewer,
                f"Automatically closed because {display_id('APP', application_id)} was approved.",
                app["pet_id"],
                application_id,
            ),
        )
        for auto_closed_app in auto_closed:
            log_application_status_update(
                conn,
                auto_closed_app["application_id"],
                "Rejected",
                f"auto-closed after {display_id('APP', application_id)} was approved",
            )

    reconcile_pet_workflow_states(conn, app["pet_id"])
    pet_after_review = conn.execute(
        "SELECT status FROM PET WHERE pet_id = ?", (app["pet_id"],)
    ).fetchone()["status"]
    if pet_after_review != pet_before_review:
        log_pet_status_update(
            conn,
            app["pet_id"],
            pet_after_review,
            f"{display_id('APP', application_id)} reviewed",
        )

    return fetch_application(conn, application_id)


def create_follow_up(conn: sqlite3.Connection, payload: dict) -> dict:
    adoption_id = coerce_crud_value("adoptionId", payload.get("adoptionId"), "positive_int", True)
    followup_date = coerce_crud_value(
        "followupDate",
        payload.get("followupDate") or local_today_iso(),
        "date",
        True,
    )
    followup_type = coerce_crud_value("followupType", payload.get("followupType"), "followup_type", True)
    pet_condition = (payload.get("petCondition") or "").strip()
    adopter_feedback = (payload.get("adopterFeedback") or "").strip()
    result_status = coerce_crud_value("resultStatus", payload.get("resultStatus"), "followup_status", True)
    staff_note = (payload.get("staffNote") or "").strip()

    if not pet_condition:
        raise ApiError(
            HTTPStatus.BAD_REQUEST,
            "Pet condition is required.",
        )
    validate_resource_rules(
        conn,
        "follow-ups",
        {
            "adoption_id": adoption_id,
            "followup_date": followup_date,
            "followup_type": followup_type,
            "pet_condition": pet_condition,
            "adopter_feedback": adopter_feedback or None,
            "result_status": result_status,
            "staff_note": staff_note or None,
        },
    )

    followup_id = conn.execute(
        "SELECT COALESCE(MAX(followup_id), 0) + 1 AS next_id FROM FOLLOW_UP"
    ).fetchone()["next_id"]
    conn.execute(
        """
        INSERT INTO FOLLOW_UP (
            followup_id,
            adoption_id,
            followup_date,
            followup_type,
            pet_condition,
            adopter_feedback,
            result_status,
            staff_note
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            followup_id,
            adoption_id,
            followup_date,
            followup_type,
            pet_condition,
            adopter_feedback or None,
            result_status,
            staff_note or None,
        ),
    )

    row = conn.execute(
        """
        SELECT
            f.*,
            ar.application_id,
            aa.pet_id,
            ap.full_name AS applicant_name,
            p.name AS pet_name
        FROM FOLLOW_UP f
        JOIN ADOPTION_RECORD ar ON f.adoption_id = ar.adoption_id
        JOIN ADOPTION_APPLICATION aa ON ar.application_id = aa.application_id
        JOIN APPLICANT ap ON aa.applicant_id = ap.applicant_id
        JOIN PET p ON aa.pet_id = p.pet_id
        WHERE f.followup_id = ?
        """,
        (followup_id,),
    ).fetchone()
    log_resource_activity(conn, "follow-ups", followup_id, "created")
    return format_followup(row)


CRUD_CONFIGS = {
    "shelters": {
        "table": "SHELTER",
        "pk": "shelter_id",
        "fields": {
            "name": ("name", "text", True),
            "address": ("address", "text", False),
            "phone": ("phone", "phone", False),
            "capacity": ("capacity", "positive_int", True),
        },
        "fetch_key": "shelters",
        "fetcher": fetch_shelters,
    },
    "pets": {
        "table": "PET",
        "pk": "pet_id",
        "fields": {
            "shelterId": ("shelter_id", "positive_int", True),
            "name": ("name", "text", True),
            "species": ("species", "species", True),
            "breed": ("breed", "text", False),
            "sex": ("sex", "sex", False),
            "color": ("color", "text", False),
            "birth": ("estimated_birth_date", "date", False),
            "intake": ("intake_date", "date", True),
            "status": ("status", "pet_status", True),
            "sterilized": ("is_sterilized", "bool", False),
            "special": ("special_needs", "text", False),
        },
        "fetch_key": "pets",
        "fetcher": fetch_pets,
    },
    "applicants": {
        "table": "APPLICANT",
        "pk": "applicant_id",
        "fields": {
            "name": ("full_name", "text", True),
            "phone": ("phone", "phone", False),
            "email": ("email", "email", False),
            "address": ("address", "text", False),
            "housingType": ("housing_type", "housing_type", False),
            "hasPetExperience": ("has_pet_experience", "bool", False),
            "createdAt": ("created_at", "date", False),
        },
        "fetch_key": "applicants",
        "fetcher": fetch_applicants,
    },
    "medical-records": {
        "table": "MEDICAL_RECORD",
        "pk": "record_id",
        "fields": {
            "petId": ("pet_id", "positive_int", True),
            "date": ("visit_date", "date", True),
            "type": ("record_type", "medical_type", False),
            "diagnosis": ("diagnosis", "text", False),
            "treatment": ("treatment", "text", False),
            "vet": ("vet_name", "text", False),
            "notes": ("notes", "text", False),
        },
        "fetch_key": "medicalRecords",
        "fetcher": fetch_medical_records,
    },
    "vaccinations": {
        "table": "VACCINATION",
        "pk": "vaccination_id",
        "fields": {
            "petId": ("pet_id", "positive_int", True),
            "vaccine": ("vaccine_name", "text", True),
            "doseNo": ("dose_no", "positive_int", False),
            "vaccinationDate": ("vaccination_date", "date", True),
            "dueDate": ("next_due_date", "date", False),
            "vet": ("vet_name", "text", False),
            "notes": ("notes", "text", False),
        },
        "fetch_key": "vaccinations",
        "fetcher": lambda conn: fetch_vaccinations(conn, False),
    },
    "volunteers": {
        "table": "VOLUNTEER",
        "pk": "volunteer_id",
        "fields": {
            "shelterId": ("shelter_id", "positive_int", True),
            "name": ("full_name", "text", True),
            "phone": ("phone", "phone", False),
            "email": ("email", "email", False),
            "joined": ("join_date", "date", False),
            "availability": ("availability_note", "text", False),
        },
        "fetch_key": "volunteers",
        "fetcher": fetch_volunteers,
    },
    "care-assignments": {
        "table": "CARE_ASSIGNMENT",
        "pk": "assignment_id",
        "fields": {
            "volunteerId": ("volunteer_id", "positive_int", True),
            "petId": ("pet_id", "positive_int", True),
            "date": ("assignment_date", "date", True),
            "shift": ("shift", "care_shift", True),
            "task": ("task_type", "care_task", True),
            "status": ("status", "care_status", True),
            "notes": ("notes", "text", False),
        },
        "fetch_key": "careAssignments",
        "fetcher": fetch_care_assignments,
    },
    "follow-ups": {
        "table": "FOLLOW_UP",
        "pk": "followup_id",
        "fields": {
            "adoptionId": ("adoption_id", "positive_int", True),
            "followupDate": ("followup_date", "date", True),
            "followupType": ("followup_type", "followup_type", True),
            "petCondition": ("pet_condition", "text", True),
            "adopterFeedback": ("adopter_feedback", "text", False),
            "resultStatus": ("result_status", "followup_status", True),
            "staffNote": ("staff_note", "text", False),
        },
        "fetch_key": "followUps",
        "fetcher": fetch_followups,
    },
}


def coerce_crud_value(name: str, value, value_type: str, required: bool):
    if value is None or value == "":
        if required:
            raise ApiError(HTTPStatus.BAD_REQUEST, f"{name} is required.")
        return None

    if value_type in {"int", "positive_int"}:
        try:
            number = int(value)
        except (TypeError, ValueError) as exc:
            raise ApiError(HTTPStatus.BAD_REQUEST, f"{name} must be an integer.") from exc
        if value_type == "positive_int" and number <= 0:
            raise ApiError(HTTPStatus.BAD_REQUEST, f"{name} must be greater than 0.")
        return number
    if value_type == "bool":
        if isinstance(value, bool):
            return 1 if value else 0
        return 1 if str(value).lower() in {"1", "true", "yes", "on"} else 0
    if value_type == "date":
        text = str(value).strip()
        if len(text) == 10:
            try:
                datetime.strptime(text, "%Y-%m-%d")
                text = f"{text} {local_now_iso()[11:]}"
            except ValueError as exc:
                raise ApiError(HTTPStatus.BAD_REQUEST, f"{name} must use YYYY-MM-DD format.") from exc
        elif len(text) > 10:
            try:
                datetime.strptime(text[:10], "%Y-%m-%d")
                text = f"{text[:10]} {local_now_iso()[11:]}"
            except ValueError as exc:
                raise ApiError(HTTPStatus.BAD_REQUEST, f"{name} must use YYYY-MM-DD format.") from exc
        return text
    if value_type == "email":
        text = str(value).strip()
        if not EMAIL_RE.match(text):
            raise ApiError(HTTPStatus.BAD_REQUEST, f"{name} must be a valid email address.")
        return text
    if value_type == "phone":
        text = str(value).strip()
        if not PHONE_RE.match(text) or sum(ch.isdigit() for ch in text) < 3:
            raise ApiError(HTTPStatus.BAD_REQUEST, f"{name} must be a valid phone number.")
        return text
    if value_type == "pet_status":
        status = str(value).strip()
        normalized = PET_STATUS_DB_VALUES.get(status, status.lower().replace(" ", "_"))
        if normalized not in PET_STATUS_VALUES:
            raise ApiError(HTTPStatus.BAD_REQUEST, "status must be Available, Reserved, Adopted, or Medical hold.")
        return normalized
    domain_values = {
        "species": SPECIES_VALUES,
        "sex": SEX_VALUES,
        "housing_type": HOUSING_TYPE_VALUES,
        "medical_type": MEDICAL_RECORD_TYPES,
        "care_status": CARE_ASSIGNMENT_STATUSES,
        "care_shift": CARE_SHIFTS,
        "care_task": CARE_TASK_TYPES,
        "followup_type": FOLLOWUP_TYPES,
        "followup_status": FOLLOWUP_RESULT_STATUSES,
    }
    if value_type in domain_values:
        text = str(value).strip()
        canonical = {item.lower(): item for item in domain_values[value_type]}
        if text.lower() not in canonical:
            allowed = ", ".join(sorted(domain_values[value_type]))
            raise ApiError(HTTPStatus.BAD_REQUEST, f"{name} must be one of: {allowed}.")
        return canonical[text.lower()]
    return str(value).strip()


def crud_values(resource: str, payload: dict, *, partial: bool = False) -> dict[str, Any]:
    config = CRUD_CONFIGS[resource]
    values = {}
    for payload_name, (column, value_type, required) in config["fields"].items():
        if partial and payload_name not in payload:
            continue
        values[column] = coerce_crud_value(
            payload_name,
            payload.get(payload_name),
            value_type,
            required,
        )
    return values


def resource_payload(conn: sqlite3.Connection, resource: str) -> dict:
    config = CRUD_CONFIGS[resource]
    return {config["fetch_key"]: config["fetcher"](conn)}


def db_date(value: str | None) -> date | None:
    if not value:
        return None
    return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()


def ensure_exists(conn: sqlite3.Connection, table: str, pk: str, value: int, label: str) -> sqlite3.Row:
    row = conn.execute(f"SELECT * FROM {table} WHERE {pk} = ?", (value,)).fetchone()
    if not row:
        raise ApiError(HTTPStatus.BAD_REQUEST, f"{label} does not exist.")
    return row


def current_resource_values(
    conn: sqlite3.Connection, config: dict, values: dict[str, Any], item_id: int | None
) -> dict[str, Any]:
    if item_id is None:
        return dict(values)
    row = conn.execute(
        f"SELECT * FROM {config['table']} WHERE {config['pk']} = ?",
        (item_id,),
    ).fetchone()
    if not row:
        raise ApiError(HTTPStatus.NOT_FOUND, "Record not found.")
    merged = dict(row)
    merged.update(values)
    return merged


def active_pet_count(conn: sqlite3.Connection, shelter_id: int, exclude_pet_id: int | None = None) -> int:
    params: list[Any] = [shelter_id]
    exclude_sql = ""
    if exclude_pet_id is not None:
        exclude_sql = "AND pet_id != ?"
        params.append(exclude_pet_id)
    return conn.execute(
        f"""
        SELECT COUNT(*) AS count
        FROM PET
        WHERE shelter_id = ?
          AND lower(status) IN ('available', 'reserved', 'medical_hold')
          {exclude_sql}
        """,
        params,
    ).fetchone()["count"]


def assert_shelter_capacity(
    conn: sqlite3.Connection,
    shelter_id: int,
    new_status: str | None,
    pet_id: int | None = None,
) -> None:
    shelter = ensure_exists(conn, "SHELTER", "shelter_id", shelter_id, "Shelter")
    if (new_status or "").lower() not in {"available", "reserved", "medical_hold"}:
        return
    if active_pet_count(conn, shelter_id, pet_id) + 1 > shelter["capacity"]:
        raise ApiError(HTTPStatus.CONFLICT, f"{shelter['name']} is already at capacity.")


def approved_application_for_pet(
    conn: sqlite3.Connection,
    pet_id: int,
    exclude_application_id: int | None = None,
) -> sqlite3.Row | None:
    params: list[Any] = [pet_id]
    exclude_sql = ""
    if exclude_application_id is not None:
        exclude_sql = "AND aa.application_id != ?"
        params.append(exclude_application_id)
    return conn.execute(
        """
        SELECT aa.*, ar.adoption_date
        FROM ADOPTION_APPLICATION aa
        LEFT JOIN ADOPTION_RECORD ar ON aa.application_id = ar.application_id
        WHERE aa.pet_id = ?
          AND aa.status = 'Approved'
          {exclude_sql}
        ORDER BY date(COALESCE(ar.adoption_date, aa.reviewed_date, aa.application_date)) DESC
        LIMIT 1
        """.format(exclude_sql=exclude_sql),
        params,
    ).fetchone()


def pending_application_for_pet(conn: sqlite3.Connection, pet_id: int) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT *
        FROM ADOPTION_APPLICATION
        WHERE pet_id = ?
          AND status = 'Under Review'
        LIMIT 1
        """,
        (pet_id,),
    ).fetchone()


def assert_pet_intake_not_after_related_records(
    conn: sqlite3.Connection, pet_id: int, intake_date: str
) -> None:
    issue = conn.execute(
        """
        SELECT issue, event_date
        FROM (
            SELECT 'application' AS issue, application_date AS event_date
            FROM ADOPTION_APPLICATION
            WHERE pet_id = ?
              AND date(application_date) < date(?)
            UNION ALL
            SELECT 'adoption' AS issue, ar.adoption_date AS event_date
            FROM ADOPTION_RECORD ar
            JOIN ADOPTION_APPLICATION aa ON ar.application_id = aa.application_id
            WHERE aa.pet_id = ?
              AND date(ar.adoption_date) < date(?)
            UNION ALL
            SELECT 'medical visit' AS issue, visit_date AS event_date
            FROM MEDICAL_RECORD
            WHERE pet_id = ?
              AND date(visit_date) < date(?)
            UNION ALL
            SELECT 'vaccination' AS issue, vaccination_date AS event_date
            FROM VACCINATION
            WHERE pet_id = ?
              AND date(vaccination_date) < date(?)
            UNION ALL
            SELECT 'care assignment' AS issue, assignment_date AS event_date
            FROM CARE_ASSIGNMENT
            WHERE pet_id = ?
              AND date(assignment_date) < date(?)
        )
        ORDER BY date(event_date)
        LIMIT 1
        """,
        (
            pet_id,
            intake_date,
            pet_id,
            intake_date,
            pet_id,
            intake_date,
            pet_id,
            intake_date,
            pet_id,
            intake_date,
        ),
    ).fetchone()
    if issue:
        raise ApiError(
            HTTPStatus.CONFLICT,
            f"Pet intake date cannot be later than an existing {issue['issue']} on {issue['event_date']}.",
        )


def assert_pet_shelter_consistency_for_assignments(
    conn: sqlite3.Connection, pet_id: int, shelter_id: int
) -> None:
    conflict = conn.execute(
        """
        SELECT c.assignment_id, v.full_name, s.name AS volunteer_shelter
        FROM CARE_ASSIGNMENT c
        JOIN VOLUNTEER v ON c.volunteer_id = v.volunteer_id
        JOIN SHELTER s ON v.shelter_id = s.shelter_id
        WHERE c.pet_id = ?
          AND v.shelter_id != ?
        ORDER BY c.assignment_date DESC, c.assignment_id DESC
        LIMIT 1
        """,
        (pet_id, shelter_id),
    ).fetchone()
    if conflict:
        raise ApiError(
            HTTPStatus.CONFLICT,
            "Pet shelter cannot be changed because existing care assignments would become cross-shelter.",
        )


def assert_volunteer_join_date_not_after_assignments(
    conn: sqlite3.Connection, volunteer_id: int, join_date: str
) -> None:
    issue = conn.execute(
        """
        SELECT assignment_id, assignment_date
        FROM CARE_ASSIGNMENT
        WHERE volunteer_id = ?
          AND date(assignment_date) < date(?)
        ORDER BY date(assignment_date)
        LIMIT 1
        """,
        (volunteer_id, join_date),
    ).fetchone()
    if issue:
        raise ApiError(
            HTTPStatus.CONFLICT,
            f"Volunteer join date cannot be later than care assignment {display_id('CA', issue['assignment_id'])} on {issue['assignment_date']}.",
        )


def assert_volunteer_shelter_consistency_for_assignments(
    conn: sqlite3.Connection, volunteer_id: int, shelter_id: int
) -> None:
    conflict = conn.execute(
        """
        SELECT c.assignment_id, p.name AS pet_name, s.name AS pet_shelter
        FROM CARE_ASSIGNMENT c
        JOIN PET p ON c.pet_id = p.pet_id
        JOIN SHELTER s ON p.shelter_id = s.shelter_id
        WHERE c.volunteer_id = ?
          AND p.shelter_id != ?
        ORDER BY c.assignment_date DESC, c.assignment_id DESC
        LIMIT 1
        """,
        (volunteer_id, shelter_id),
    ).fetchone()
    if conflict:
        raise ApiError(
            HTTPStatus.CONFLICT,
            "Volunteer shelter cannot be changed because existing care assignments would become cross-shelter.",
        )


def assert_resource_deletable(conn: sqlite3.Connection, resource: str, item_id: int) -> None:
    if resource == "shelters":
        pet_count = conn.execute(
            "SELECT COUNT(*) AS count FROM PET WHERE shelter_id = ?",
            (item_id,),
        ).fetchone()["count"]
        volunteer_count = conn.execute(
            "SELECT COUNT(*) AS count FROM VOLUNTEER WHERE shelter_id = ?",
            (item_id,),
        ).fetchone()["count"]
        if pet_count or volunteer_count:
            raise ApiError(
                HTTPStatus.CONFLICT,
                "Shelters with linked pets or volunteers cannot be deleted.",
            )

    elif resource == "pets":
        blockers = {
            "applications": conn.execute(
                "SELECT COUNT(*) AS count FROM ADOPTION_APPLICATION WHERE pet_id = ?",
                (item_id,),
            ).fetchone()["count"],
            "medical records": conn.execute(
                "SELECT COUNT(*) AS count FROM MEDICAL_RECORD WHERE pet_id = ?",
                (item_id,),
            ).fetchone()["count"],
            "vaccinations": conn.execute(
                "SELECT COUNT(*) AS count FROM VACCINATION WHERE pet_id = ?",
                (item_id,),
            ).fetchone()["count"],
            "care assignments": conn.execute(
                "SELECT COUNT(*) AS count FROM CARE_ASSIGNMENT WHERE pet_id = ?",
                (item_id,),
            ).fetchone()["count"],
        }
        active = [label for label, count in blockers.items() if count]
        if active:
            raise ApiError(
                HTTPStatus.CONFLICT,
                f"Pets with linked {', '.join(active)} cannot be deleted.",
            )

    elif resource == "applicants":
        application_count = conn.execute(
            "SELECT COUNT(*) AS count FROM ADOPTION_APPLICATION WHERE applicant_id = ?",
            (item_id,),
        ).fetchone()["count"]
        if application_count:
            raise ApiError(
                HTTPStatus.CONFLICT,
                "Applicants with adoption applications cannot be deleted.",
            )

    elif resource == "volunteers":
        assignment_count = conn.execute(
            "SELECT COUNT(*) AS count FROM CARE_ASSIGNMENT WHERE volunteer_id = ?",
            (item_id,),
        ).fetchone()["count"]
        if assignment_count:
            raise ApiError(
                HTTPStatus.CONFLICT,
                "Volunteers with care assignments cannot be deleted.",
            )


def validate_pet_status_workflow(
    conn: sqlite3.Connection, pet_id: int | None, status: str, creating: bool
) -> None:
    if creating and status in {"reserved", "adopted"}:
        raise ApiError(
            HTTPStatus.CONFLICT,
            "New pets can start only as Available or Medical hold. Reserved and Adopted are controlled by the adoption workflow.",
        )
    if pet_id is None:
        return
    pending = pending_application_for_pet(conn, pet_id)
    approved = approved_application_for_pet(conn, pet_id)
    if pending and status != "reserved":
        raise ApiError(HTTPStatus.CONFLICT, "A pet with a pending application must stay Reserved.")
    if approved and not pending and status != "adopted":
        raise ApiError(HTTPStatus.CONFLICT, "An approved adoption keeps the pet status as Adopted.")
    if not pending and not approved and status in {"reserved", "adopted"}:
        raise ApiError(
            HTTPStatus.CONFLICT,
            "Reserved and Adopted statuses must be produced by adoption applications, not direct pet edits.",
        )


def validate_resource_rules(
    conn: sqlite3.Connection,
    resource: str,
    values: dict[str, Any],
    item_id: int | None = None,
) -> None:
    if resource == "shelters":
        if values.get("capacity") is not None and values["capacity"] < active_pet_count(conn, item_id or -1):
            raise ApiError(HTTPStatus.CONFLICT, "Shelter capacity cannot be lower than its active pet count.")

    elif resource == "pets":
        shelter_id = values["shelter_id"]
        status = values["status"]
        ensure_exists(conn, "SHELTER", "shelter_id", shelter_id, "Shelter")
        intake_date = db_date(values["intake_date"])
        if intake_date > local_today():
            raise ApiError(HTTPStatus.BAD_REQUEST, "Pet intake date cannot be in the future.")
        if values.get("estimated_birth_date") and db_date(values["estimated_birth_date"]) > intake_date:
            raise ApiError(HTTPStatus.BAD_REQUEST, "Estimated birth date cannot be after intake date.")
        if item_id is not None:
            current_pet = ensure_exists(conn, "PET", "pet_id", item_id, "Pet")
            if values["intake_date"] != current_pet["intake_date"]:
                assert_pet_intake_not_after_related_records(conn, item_id, values["intake_date"])
            if shelter_id != current_pet["shelter_id"]:
                assert_pet_shelter_consistency_for_assignments(conn, item_id, shelter_id)
        validate_pet_status_workflow(conn, item_id, status, item_id is None)
        assert_shelter_capacity(conn, shelter_id, status, item_id)

    elif resource == "medical-records":
        pet = ensure_exists(conn, "PET", "pet_id", values["pet_id"], "Pet")
        if db_date(values["visit_date"]) < db_date(pet["intake_date"]):
            raise ApiError(HTTPStatus.BAD_REQUEST, "Medical visit date cannot be before pet intake date.")

    elif resource == "vaccinations":
        pet = ensure_exists(conn, "PET", "pet_id", values["pet_id"], "Pet")
        vaccination_date = db_date(values["vaccination_date"])
        if vaccination_date < db_date(pet["intake_date"]):
            raise ApiError(HTTPStatus.BAD_REQUEST, "Vaccination date cannot be before pet intake date.")
        if values.get("next_due_date") and db_date(values["next_due_date"]) < vaccination_date:
            raise ApiError(HTTPStatus.BAD_REQUEST, "Next due date cannot be before vaccination date.")

    elif resource == "volunteers":
        ensure_exists(conn, "SHELTER", "shelter_id", values["shelter_id"], "Shelter")
        if item_id is not None:
            current_volunteer = ensure_exists(conn, "VOLUNTEER", "volunteer_id", item_id, "Volunteer")
            if values.get("join_date") and values["join_date"] != current_volunteer["join_date"]:
                assert_volunteer_join_date_not_after_assignments(conn, item_id, values["join_date"])
            if values["shelter_id"] != current_volunteer["shelter_id"]:
                assert_volunteer_shelter_consistency_for_assignments(conn, item_id, values["shelter_id"])

    elif resource == "care-assignments":
        volunteer = ensure_exists(conn, "VOLUNTEER", "volunteer_id", values["volunteer_id"], "Volunteer")
        pet = ensure_exists(conn, "PET", "pet_id", values["pet_id"], "Pet")
        assignment_date = db_date(values["assignment_date"])
        if assignment_date < db_date(pet["intake_date"]):
            raise ApiError(HTTPStatus.BAD_REQUEST, "Care assignment date cannot be before pet intake date.")
        if volunteer["shelter_id"] != pet["shelter_id"]:
            raise ApiError(
                HTTPStatus.CONFLICT,
                "Volunteer and pet must belong to the same shelter for care assignments.",
            )
        if volunteer["join_date"] and assignment_date < db_date(volunteer["join_date"]):
            raise ApiError(
                HTTPStatus.BAD_REQUEST,
                "Care assignment date cannot be before the volunteer join date.",
            )
        approved = approved_application_for_pet(conn, values["pet_id"])
        if approved and values.get("status") != "Cancelled":
            adoption_date = db_date(approved["adoption_date"] or approved["reviewed_date"] or approved["application_date"])
            if assignment_date >= adoption_date:
                raise ApiError(
                    HTTPStatus.CONFLICT,
                    "Adopted pets cannot receive scheduled care assignments on or after adoption date.",
                )

    elif resource == "follow-ups":
        adoption = ensure_exists(conn, "ADOPTION_RECORD", "adoption_id", values["adoption_id"], "Adoption record")
        if db_date(values["followup_date"]) < db_date(adoption["adoption_date"]):
            raise ApiError(HTTPStatus.BAD_REQUEST, "Follow-up date cannot be before adoption date.")


def next_resource_id(conn: sqlite3.Connection, table: str, pk: str) -> int:
    return conn.execute(
        f"SELECT COALESCE(MAX({pk}), 0) + 1 AS next_id FROM {table}"
    ).fetchone()["next_id"]


def apply_resource_defaults(resource: str, values: dict[str, Any]) -> dict[str, Any]:
    defaults = dict(values)
    if resource == "applicants" and not defaults.get("created_at"):
        defaults["created_at"] = local_now_iso()
    return defaults


def ensure_resource_exists(conn: sqlite3.Connection, table: str, pk: str, item_id: int) -> None:
    row = conn.execute(f"SELECT 1 FROM {table} WHERE {pk} = ?", (item_id,)).fetchone()
    if not row:
        raise ApiError(HTTPStatus.NOT_FOUND, "Record not found.")


def create_resource(conn: sqlite3.Connection, resource: str, payload: dict) -> dict:
    config = CRUD_CONFIGS[resource]
    values = apply_resource_defaults(resource, crud_values(resource, payload))
    validate_resource_rules(conn, resource, values)
    item_id = next_resource_id(conn, config["table"], config["pk"])
    columns = [config["pk"], *values.keys()]
    placeholders = ", ".join("?" for _ in columns)
    conn.execute(
        f"INSERT INTO {config['table']} ({', '.join(columns)}) VALUES ({placeholders})",
        (item_id, *values.values()),
    )
    if resource == "pets":
        reconcile_pet_workflow_states(conn, item_id)
    log_resource_activity(conn, resource, item_id, "created")

    return resource_payload(conn, resource)


def update_resource(conn: sqlite3.Connection, resource: str, item_id: int, payload: dict) -> dict:
    config = CRUD_CONFIGS[resource]
    ensure_resource_exists(conn, config["table"], config["pk"], item_id)
    values = crud_values(resource, payload, partial=True)
    if not values:
        raise ApiError(HTTPStatus.BAD_REQUEST, "No fields were provided.")
    merged_values = current_resource_values(conn, config, values, item_id)
    validate_resource_rules(conn, resource, merged_values, item_id)
    set_sql = ", ".join(f"{column} = ?" for column in values)
    conn.execute(
        f"UPDATE {config['table']} SET {set_sql} WHERE {config['pk']} = ?",
        (*values.values(), item_id),
    )
    if resource == "pets":
        reconcile_pet_workflow_states(conn, item_id)
    log_resource_activity(conn, resource, item_id, "updated")

    return resource_payload(conn, resource)


def delete_resource(conn: sqlite3.Connection, resource: str, item_id: int) -> dict:
    config = CRUD_CONFIGS[resource]
    ensure_resource_exists(conn, config["table"], config["pk"], item_id)
    assert_resource_deletable(conn, resource, item_id)

    log_resource_activity(conn, resource, item_id, "removed")
    conn.execute(f"DELETE FROM {config['table']} WHERE {config['pk']} = ?", (item_id,))

    return resource_payload(conn, resource)


def api_payload(path: str, query: dict[str, list[str]]) -> dict:
    with managed_connection() as conn:
        if path == "/api/health":
            return {"ok": True, "database": str(DB_PATH), "timezone": APP_TIMEZONE_NAME}
        if path == "/api/dashboard":
            return fetch_dashboard(conn)
        if path == "/api/analytics":
            return fetch_analytics(conn)
        if path == "/api/llm-bonus":
            return fetch_llm_bonus(conn)
        if path == "/api/shelters":
            return {"shelters": fetch_shelters(conn)}
        if path == "/api/pets":
            return {"pets": fetch_pets(conn)}
        if path == "/api/applicants":
            return {"applicants": fetch_applicants(conn)}
        if path == "/api/applications":
            return {"applications": fetch_applications(conn)}
        if path == "/api/adoption-records":
            return {"adoptionRecords": fetch_adoption_records(conn)}
        if path == "/api/follow-ups":
            return {"followUps": fetch_followups(conn)}
        if path == "/api/medical-records":
            return {"medicalRecords": fetch_medical_records(conn)}
        if path == "/api/vaccinations":
            upcoming_only = query.get("upcoming", ["false"])[0].lower() == "true"
            return {"vaccinations": fetch_vaccinations(conn, upcoming_only)}
        if path == "/api/volunteers":
            return {"volunteers": fetch_volunteers(conn)}
        if path == "/api/care-assignments":
            return {"careAssignments": fetch_care_assignments(conn)}
    raise ApiError(HTTPStatus.NOT_FOUND, "Endpoint not found.")


class PawTrackHandler(BaseHTTPRequestHandler):
    server_version = "PawTrackHTTP/1.0"

    def log_message(self, fmt: str, *args) -> None:
        print(f"{self.address_string()} - {fmt % args}")

    def end_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PATCH, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        super().end_headers()

    def do_OPTIONS(self) -> None:
        self.send_response(HTTPStatus.NO_CONTENT)
        self.end_headers()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)

        try:
            if path.startswith("/api/"):
                self.write_json(api_payload(path, query))
                return
            self.serve_static(path)
        except ApiError as exc:
            self.write_json({"error": exc.message, **exc.payload}, exc.status)
        except Exception as exc:
            self.write_json({"error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        try:
            payload = self.read_json_body()
            if parsed.path == "/api/applications":
                with managed_connection() as conn:
                    begin_write(conn)
                    result = create_application(conn, payload)
                self.write_json({"application": result}, HTTPStatus.CREATED)
                return
            if parsed.path == "/api/llm-query":
                with managed_connection() as conn:
                    result = run_llm_query(conn, payload)
                self.write_json(result)
                return
            if parsed.path == "/api/llm-generate-query":
                with managed_connection() as conn:
                    result = run_llm_generate_query(conn, payload)
                self.write_json(result)
                return
            if parsed.path == "/api/follow-ups":
                with managed_connection() as conn:
                    begin_write(conn)
                    result = create_follow_up(conn, payload)
                self.write_json({"followUp": result}, HTTPStatus.CREATED)
                return
            parts = [part for part in parsed.path.split("/") if part]
            if len(parts) == 2 and parts[0] == "api" and parts[1] in CRUD_CONFIGS:
                with managed_connection() as conn:
                    begin_write(conn)
                    result = create_resource(conn, parts[1], payload)
                self.write_json(result, HTTPStatus.CREATED)
                return
            raise ApiError(HTTPStatus.NOT_FOUND, "Endpoint not found.")
        except ApiError as exc:
            self.write_json({"error": exc.message, **exc.payload}, exc.status)
        except sqlite3.IntegrityError as exc:
            self.write_json({"error": f"Database constraint failed: {exc}"}, HTTPStatus.CONFLICT)
        except Exception as exc:
            self.write_json({"error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def do_PATCH(self) -> None:
        parsed = urlparse(self.path)
        try:
            payload = self.read_json_body()
            parts = [part for part in parsed.path.split("/") if part]
            if len(parts) == 4 and parts[:2] == ["api", "applications"] and parts[3] == "review":
                application_id = int(parts[2])
                with managed_connection() as conn:
                    begin_write(conn)
                    result = review_application(conn, application_id, payload)
                self.write_json({"application": result})
                return
            if len(parts) == 3 and parts[0] == "api" and parts[1] in CRUD_CONFIGS:
                item_id = int(parts[2])
                with managed_connection() as conn:
                    begin_write(conn)
                    result = update_resource(conn, parts[1], item_id, payload)
                self.write_json(result)
                return
            raise ApiError(HTTPStatus.NOT_FOUND, "Endpoint not found.")
        except ValueError:
            self.write_json({"error": "Invalid record id."}, HTTPStatus.BAD_REQUEST)
        except sqlite3.IntegrityError as exc:
            self.write_json({"error": f"Database constraint failed: {exc}"}, HTTPStatus.CONFLICT)
        except ApiError as exc:
            self.write_json({"error": exc.message, **exc.payload}, exc.status)
        except Exception as exc:
            self.write_json({"error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def do_DELETE(self) -> None:
        parsed = urlparse(self.path)
        try:
            parts = [part for part in parsed.path.split("/") if part]
            if len(parts) == 3 and parts[0] == "api" and parts[1] in CRUD_CONFIGS:
                item_id = int(parts[2])
                with managed_connection() as conn:
                    begin_write(conn)
                    result = delete_resource(conn, parts[1], item_id)
                self.write_json(result)
                return
            raise ApiError(HTTPStatus.NOT_FOUND, "Endpoint not found.")
        except ValueError:
            self.write_json({"error": "Invalid record id."}, HTTPStatus.BAD_REQUEST)
        except sqlite3.IntegrityError:
            self.write_json(
                {
                    "error": "This record is referenced by other records, so it cannot be deleted safely."
                },
                HTTPStatus.CONFLICT,
            )
        except ApiError as exc:
            self.write_json({"error": exc.message, **exc.payload}, exc.status)
        except Exception as exc:
            self.write_json({"error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def read_json_body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        return json.loads(raw.decode("utf-8"))

    def write_json(self, payload: dict, status: HTTPStatus = HTTPStatus.OK) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def serve_static(self, path: str) -> None:
        if path in {"/", "/pawtrack_demo.html"}:
            static_path = FRONTEND_PATH
        else:
            static_path = (ROOT_DIR / path.lstrip("/")).resolve()
            if ROOT_DIR not in static_path.parents and static_path != ROOT_DIR:
                raise ApiError(HTTPStatus.FORBIDDEN, "Forbidden.")
        if not static_path.exists() or not static_path.is_file():
            raise ApiError(HTTPStatus.NOT_FOUND, "File not found.")

        data = static_path.read_bytes()
        content_type = mimetypes.guess_type(static_path.name)[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the PawTrack HTTP API server.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8000, type=int)
    parser.add_argument("--reset-db", action="store_true", help="Rebuild pet_database.db from CSV files.")
    args = parser.parse_args()

    try:
        initialize_database(reset=args.reset_db)
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from exc
    server = ThreadingHTTPServer((args.host, args.port), PawTrackHandler)
    print(f"PawTrack API running at http://{args.host}:{args.port}")
    print(f"Open http://{args.host}:{args.port}/pawtrack_demo.html")
    server.serve_forever()


if __name__ == "__main__":
    main()
