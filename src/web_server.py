"""
HTTP API for the PawTrack frontend.

The server uses the existing schema and CSV seed files to initialize a local
SQLite database, then exposes JSON endpoints for the single-page frontend.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import mimetypes
import re
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse


ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
SCHEMA_PATH = ROOT_DIR / "src" / "schema" / "table.sql"
INDEXING_PATH = ROOT_DIR / "src" / "schema" / "indexing.sql"
QUERIES_DIR = ROOT_DIR / "src" / "queries"
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

DOMAIN_OPTIONS = {
    "petStatuses": ["Available", "Reserved", "Medical hold", "Adopted"],
    "applicationStatuses": ["Pending", "Approved", "Rejected"],
    "species": ["Dog", "Cat", "Rabbit", "Bird"],
    "sex": ["Male", "Female", "Unknown"],
    "housingTypes": [
        "Apartment",
        "Condo",
        "House",
        "Townhouse",
        "House with garden",
        "House without garden",
        "Shared housing",
    ],
    "medicalRecordTypes": ["Check-up", "Surgery", "Treatment", "Injury", "Dental"],
    "careShifts": ["Morning", "Afternoon", "Evening"],
    "careTaskTypes": ["Cleaning", "Feeding", "Grooming", "Socializing", "Walking", "Medical support"],
    "careStatuses": ["Scheduled", "Completed", "Cancelled"],
    "followupTypes": ["Phone Check", "Home Visit", "Vet Check"],
    "followupResultStatuses": ["Excellent", "Good", "Satisfactory", "Needs Improvement"],
}


@dataclass
class StoredQuery:
    name: str
    title: str
    description: str
    sql: str
    category: str


class ApiError(Exception):
    def __init__(self, status: HTTPStatus, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def begin_write(conn: sqlite3.Connection) -> None:
    """Serialize write operations so validation and mutation stay atomic."""
    conn.execute("BEGIN IMMEDIATE")


def database_is_ready() -> bool:
    if not DB_PATH.exists():
        return False
    try:
        with connect() as conn:
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'PET'"
            ).fetchone()
            if not row:
                return False
            count = conn.execute("SELECT COUNT(*) AS count FROM PET").fetchone()["count"]
            return count > 0
    except sqlite3.Error:
        return False


def clean_csv_value(value: str | None):
    if value is None:
        return None
    value = value.strip()
    return value if value else None


def normalize_stored_dates(conn: sqlite3.Connection) -> None:
    """Normalize seeded datetime strings in DATE columns to YYYY-MM-DD."""
    conn.execute(
        """
        UPDATE APPLICANT
        SET created_at = substr(created_at, 1, 10)
        WHERE created_at GLOB '????-??-?? *'
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


def reconcile_adoption_records(conn: sqlite3.Connection) -> None:
    """Create missing final adoption records for already-approved applications."""
    rows = conn.execute(
        """
        SELECT a.application_id, a.reviewed_date, a.application_date, a.decision_note
        FROM ADOPTION_APPLICATION a
        LEFT JOIN ADOPTION_RECORD ar ON a.application_id = ar.application_id
        WHERE a.status = 'Approved'
          AND ar.adoption_id IS NULL
        ORDER BY a.application_id
        """
    ).fetchall()
    for row in rows:
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
            VALUES (?, ?, ?, NULL, ?)
            """,
            (
                adoption_id,
                row["application_id"],
                row["reviewed_date"] or row["application_date"] or date.today().isoformat(),
                row["decision_note"] or "Auto-created from approved application.",
            ),
        )


def ensure_database_constraints(conn: sqlite3.Connection) -> None:
    """Apply project indexes and uniqueness constraints to existing databases."""
    conn.executescript(INDEXING_PATH.read_text(encoding="utf-8"))


def initialize_database(reset: bool = False) -> None:
    if reset and DB_PATH.exists():
        DB_PATH.unlink()
    if database_is_ready():
        with connect() as conn:
            normalize_stored_dates(conn)
            reconcile_adoption_records(conn)
            reconcile_pet_workflow_states(conn)
            ensure_database_constraints(conn)
        return
    if DB_PATH.exists():
        DB_PATH.unlink()

    with connect() as conn:
        schema = SCHEMA_PATH.read_text(encoding="utf-8")
        conn.executescript(schema)

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
        reconcile_adoption_records(conn)
        reconcile_pet_workflow_states(conn)
        ensure_database_constraints(conn)


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


def slugify(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[_\s]+", "_", text)
    return text.strip("-_")


def parse_query_file(content: str, category: str) -> list[StoredQuery]:
    queries: list[StoredQuery] = []
    headers = list(re.finditer(r"^-- Q\d+:\s*(.+?)$", content, re.MULTILINE))
    for i, match in enumerate(headers):
        title = match.group(1).strip()
        start = match.start()
        end = headers[i + 1].start() if i + 1 < len(headers) else len(content)
        chunk = content[start:end]
        description_parts = []
        sql_lines = []
        for line in chunk.splitlines()[1:]:
            stripped = line.strip()
            if stripped.startswith("-- Purpose:"):
                description_parts.append(stripped[len("-- Purpose:") :].strip())
            elif stripped.startswith("--"):
                continue
            elif stripped:
                sql_lines.append(line)
        queries.append(
            StoredQuery(
                name=slugify(title),
                title=title,
                description=" ".join(description_parts),
                sql="\n".join(sql_lines).strip(),
                category=category,
            )
        )
    return queries


def load_query_registry() -> list[StoredQuery]:
    queries: list[StoredQuery] = []
    for sql_file in sorted(QUERIES_DIR.glob("*.sql")):
        category = sql_file.stem.replace("_queries", "").replace("_", " ")
        queries.extend(parse_query_file(sql_file.read_text(encoding="utf-8"), category))
    # Only expose read-only SELECT queries through the LLM catalog. Mutation
    # examples kept in the .sql files for documentation are silently skipped.
    return [q for q in queries if is_read_only_query(q)]


def normalize_sql(sql: str) -> str:
    today = date.today().isoformat()

    def date_add_matcher(match: re.Match) -> str:
        val, unit = match.group(1), match.group(2).lower()
        return f"date('{today}', '+{val} {unit}')"

    sql = re.sub(
        r"DATE_ADD\(CURDATE\(\),\s*INTERVAL\s+(\d+)\s+(DAY|MONTH|YEAR)\)",
        date_add_matcher,
        sql,
        flags=re.IGNORECASE,
    )
    sql = re.sub(
        r"\bDATEDIFF\(CURDATE\(\),\s*(\w+)\)",
        rf"(cast(julianday('{today}') - julianday(\1) as integer))",
        sql,
        flags=re.IGNORECASE,
    )
    return re.sub(r"\bCURDATE\(\)", f"date('{today}')", sql, flags=re.IGNORECASE)


def is_read_only_query(query: StoredQuery) -> bool:
    return query.sql.lstrip().upper().startswith("SELECT")


def _depluralize(word: str) -> str:
    """Cheap English stem so plural prompts still match singular keywords."""
    if len(word) <= 3:
        return word
    if word.endswith("ies") and len(word) > 4:
        return word[:-3] + "y"
    if word.endswith("ses") or word.endswith("xes") or word.endswith("zes"):
        return word[:-2]
    if word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def _normalize_prompt(text: str) -> str:
    """Lowercase, strip plurals, and collapse separators for matching."""
    lowered = text.lower().replace("-", " ").replace("_", " ")
    tokens = re.split(r"\W+", lowered)
    return " ".join(_depluralize(tok) for tok in tokens if tok)


def match_query_from_prompt(prompt: str, queries: list[StoredQuery]) -> StoredQuery:
    prompt_lower = prompt.lower()
    prompt_normalized = _normalize_prompt(prompt)
    concept_map = [
        (["vaccination due", "vaccine due", "upcoming vaccination", "vaccination soon", "vaccination reminder", "vaccine reminder", "due vaccination"], "view_pets_whose_vaccination_due"),
        (["adoptable", "available for adoption", "pets available", "available pet", "pet available", "ready for adoption", "open for adoption"], "view_all_pets_that_are_currently_available"),
        (["occupancy", "occupied", "most occupied", "fullest", "shelter occupancy", "shelter capacity", "how full"], "analyze_current_occupancy"),
        (["shelter", "shelter 1", "shelter 2", "pet in shelter", "housed in"], "view_all_pets_currently_housed_in_a_specific_shelter"),
        (["health info", "medical history", "full health", "vaccination and medical", "health record", "health profile"], "view_the_full_health_information"),
        (["volunteer assignment", "care assignment", "volunteer schedule", "volunteer shift", "upcoming shift"], "view_upcoming_care_assignments_for_a_volunteer"),
        (["adoption application", "pending application", "under review", "applications to review", "awaiting review"], "view_all_adoption_applications_that_are_currently_under_review"),
        (["follow up outcome", "followup outcome", "post adoption", "adopter feedback", "follow-up outcome"], "analyze_post-adoption_follow-up_outcomes"),
        (["long stay", "longest", "stay long", "long-stay", "stayed longest"], "analyze_pets_that_have_stayed_the_longest"),
        (["housing type", "approval rate by housing", "rejected by housing", "housing approval"], "analyze_adoption_application_results_by_housing_type"),
        (["adoption success rate", "adoption by species", "species demand", "most adopted species", "popular species"], "analyze_adoption_demand_and_success_rate_by_pet_species"),
        (["volunteer workload", "completed task", "volunteer performance", "tasks per volunteer", "workload"], "analyze_volunteer_workload_based_on_care_assignments"),
    ]

    for keywords, name_fragment in concept_map:
        for keyword in keywords:
            normalized_keyword = _normalize_prompt(keyword)
            if keyword in prompt_lower or normalized_keyword in prompt_normalized:
                for query in queries:
                    if name_fragment in query.name:
                        return query
                break

    stop_words = {"the", "that", "this", "with", "from", "have", "which", "what", "find", "show", "list", "give", "some", "need", "want", "would", "could", "should", "about", "into", "onto", "pets", "pet"}
    prompt_words = [
        _depluralize(word)
        for word in re.split(r"\W+", prompt_lower)
        if len(word) > 3 and word not in stop_words
    ]
    best = queries[0]
    best_score = -1
    for query in queries:
        combined = _normalize_prompt(f"{query.name} {query.description}")
        score = sum(1 for word in prompt_words if word in combined)
        if score > best_score:
            best_score = score
            best = query
    return best


def execute_read_only_query(conn: sqlite3.Connection, query: StoredQuery) -> list[dict[str, Any]]:
    if not is_read_only_query(query):
        raise ApiError(HTTPStatus.BAD_REQUEST, "Only read-only predefined SELECT queries can run from the LLM assistant.")
    rows = conn.execute(normalize_sql(query.sql)).fetchall()
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
    return {
        "petId": raw["pet_id"],
        "shelterId": raw["shelter_id"],
        "id": display_id("P", raw["pet_id"]),
        "name": raw["name"],
        "species": raw["species"],
        "breed": raw["breed"] or "",
        "sex": raw["sex"] or "",
        "color": raw["color"] or "",
        "birth": raw["estimated_birth_date"] or "",
        "intake": raw["intake_date"] or "",
        "status": pet_status_label(raw["status"]),
        "rawStatus": raw["status"],
        "sterilized": yes_no(raw["is_sterilized"]),
        "special": raw["special_needs"] or "",
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
            "createdAt": row["created_at"] or "",
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
        "applicantCreatedAt": raw["applicant_created_at"] or "",
        "pet": raw["pet_name"],
        "petSpecies": raw["pet_species"],
        "petBreed": raw["pet_breed"] or "",
        "date": raw["application_date"],
        "status": application_status_label(raw["status"]),
        "rawStatus": raw["status"],
        "reason": raw["reason"] or "",
        "reviewedDate": raw["reviewed_date"] or "",
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
        "adoptionDate": row["adoption_date"],
        "finalAdoptionFee": row["final_adoption_fee"],
        "handoverNote": row["handover_note"] or "",
        "applicantId": row["applicant_id"],
        "applicant": row["applicant_name"],
        "petId": row["pet_id"],
        "pet": row["pet_name"],
        "petSpecies": row["pet_species"],
        "followupCount": row["followup_count"] or 0,
        "lastFollowupDate": row["last_followup_date"] or "",
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
    return {
        "followupId": row["followup_id"],
        "id": display_id("FU", row["followup_id"]),
        "adoptionId": row["adoption_id"],
        "adoptionCode": display_id("AR", row["adoption_id"]),
        "followupDate": row["followup_date"],
        "followupType": row["followup_type"] or "",
        "petCondition": row["pet_condition"] or "",
        "adopterFeedback": row["adopter_feedback"] or "",
        "resultStatus": row["result_status"] or "",
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
            "date": row["visit_date"],
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
    where = (
        "WHERE v.next_due_date IS NOT NULL AND date(v.next_due_date) <= date(?)"
        if upcoming_only
        else ""
    )
    if upcoming_only:
        params = ((date.today() + timedelta(days=30)).isoformat(),)
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
            "vaccinationDate": row["vaccination_date"],
            "dueDate": row["next_due_date"] or "",
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
            COUNT(c.assignment_id) AS active_assignment_count
        FROM VOLUNTEER v
        JOIN SHELTER s ON v.shelter_id = s.shelter_id
        LEFT JOIN CARE_ASSIGNMENT c
            ON v.volunteer_id = c.volunteer_id
           AND c.status = 'Scheduled'
           AND date(c.assignment_date) >= date(?)
        LEFT JOIN PET p ON c.pet_id = p.pet_id
        GROUP BY v.volunteer_id
        ORDER BY v.full_name
        """,
        (date.today().isoformat(),),
    ).fetchall()
    return [
        {
            "volunteerId": row["volunteer_id"],
            "shelterId": row["shelter_id"],
            "id": display_id("VLT", row["volunteer_id"]),
            "name": row["full_name"],
            "email": row["email"] or "",
            "phone": row["phone"] or "",
            "joined": row["join_date"] or "",
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
            "date": row["assignment_date"],
            "shift": row["shift"] or "",
            "task": row["task_type"] or "",
            "status": row["status"] or "",
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
        WHERE lower(status) IN ('under review', 'pending')
        """
    ).fetchone()["count"]
    month_prefix = date.today().strftime("%Y-%m")
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
            "count": row["count"],
            "share": round(row["count"] * 100 / total_pets) if total_pets else 0,
        }
        for row in status_rows
    ]

    activities = fetch_recent_activity(conn)
    return {
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
        SELECT event_date, text, dot_class
        FROM (
            SELECT
                ar.adoption_date AS event_date,
                ar.adoption_id AS event_id,
                90 AS event_priority,
                p.name || ' adopted by ' || ap.full_name AS text,
                'dot-green' AS dot_class
            FROM ADOPTION_RECORD ar
            JOIN ADOPTION_APPLICATION aa ON ar.application_id = aa.application_id
            JOIN APPLICANT ap ON aa.applicant_id = ap.applicant_id
            JOIN PET p ON aa.pet_id = p.pet_id

            UNION ALL

            SELECT
                f.followup_date AS event_date,
                f.followup_id AS event_id,
                80 AS event_priority,
                'Follow-up completed for ' || p.name AS text,
                'dot-green' AS dot_class
            FROM FOLLOW_UP f
            JOIN ADOPTION_RECORD ar ON f.adoption_id = ar.adoption_id
            JOIN ADOPTION_APPLICATION aa ON ar.application_id = aa.application_id
            JOIN PET p ON aa.pet_id = p.pet_id

            UNION ALL

            SELECT
                aa.application_date AS event_date,
                aa.application_id AS event_id,
                70 AS event_priority,
                'New application for ' || p.name || ' from ' || ap.full_name AS text,
                'dot-amber' AS dot_class
            FROM ADOPTION_APPLICATION aa
            JOIN APPLICANT ap ON aa.applicant_id = ap.applicant_id
            JOIN PET p ON aa.pet_id = p.pet_id

            UNION ALL

            SELECT
                m.visit_date AS event_date,
                m.record_id AS event_id,
                60 AS event_priority,
                'Medical record added for ' || p.name AS text,
                'dot-blue' AS dot_class
            FROM MEDICAL_RECORD m
            JOIN PET p ON m.pet_id = p.pet_id

            UNION ALL

            SELECT
                v.vaccination_date AS event_date,
                v.vaccination_id AS event_id,
                50 AS event_priority,
                'Vaccination record added for ' || p.name AS text,
                'dot-blue' AS dot_class
            FROM VACCINATION v
            JOIN PET p ON v.pet_id = p.pet_id

            UNION ALL

            SELECT
                c.assignment_date AS event_date,
                c.assignment_id AS event_id,
                40 AS event_priority,
                v.full_name || ' assigned to care for ' || p.name AS text,
                'dot-amber' AS dot_class
            FROM CARE_ASSIGNMENT c
            JOIN VOLUNTEER v ON c.volunteer_id = v.volunteer_id
            JOIN PET p ON c.pet_id = p.pet_id

            UNION ALL

            SELECT
                p.intake_date AS event_date,
                p.pet_id AS event_id,
                30 AS event_priority,
                p.name || ' entered ' || s.name AS text,
                'dot-blue' AS dot_class
            FROM PET p
            JOIN SHELTER s ON p.shelter_id = s.shelter_id

            UNION ALL

            SELECT
                v.join_date AS event_date,
                v.volunteer_id AS event_id,
                20 AS event_priority,
                v.full_name || ' joined as a volunteer' AS text,
                'dot-blue' AS dot_class
            FROM VOLUNTEER v
            WHERE v.join_date IS NOT NULL

            UNION ALL

            SELECT
                ap.created_at AS event_date,
                ap.applicant_id AS event_id,
                10 AS event_priority,
                ap.full_name || ' registered as an applicant' AS text,
                'dot-amber' AS dot_class
            FROM APPLICANT ap
            WHERE ap.created_at IS NOT NULL
        )
        WHERE event_date IS NOT NULL
        ORDER BY date(event_date) DESC, event_id DESC, event_priority DESC
        LIMIT 8
        """
    ).fetchall()
    return [
        {
            "text": row["text"],
            "time": row["event_date"],
            "dotClass": row["dot_class"],
        }
        for row in rows
    ]


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
            CAST(julianday(?) - julianday(intake_date) AS INTEGER) AS days_in_shelter
        FROM PET
        WHERE lower(status) = 'available'
        ORDER BY days_in_shelter DESC
        LIMIT 10
        """,
        (date.today().isoformat(),),
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
                "intakeDate": row["intake_date"],
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


def fetch_check_rows(conn: sqlite3.Connection, sql: str, params: dict[str, Any] | None = None) -> dict:
    rows = [dict(row) for row in conn.execute(sql, params or {}).fetchall()]
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
            "llmRationale": "An LLM schema review flagged free-text status fields as a common source of inconsistent workflow states.",
            "sql": """
                SELECT pet_id, name, status
                FROM PET
                WHERE lower(status) NOT IN ('available', 'reserved', 'adopted', 'medical_hold')
            """,
            "refinement": "Use a CHECK constraint or lookup table for allowed pet statuses.",
        },
        {
            "id": "invalid_application_status",
            "title": "ADOPTION_APPLICATION.status domain validation",
            "severity": "high",
            "llmRationale": "The review identified application status as a controlled workflow attribute, not arbitrary text.",
            "sql": """
                SELECT application_id, status
                FROM ADOPTION_APPLICATION
                WHERE status NOT IN ('Under Review', 'Approved', 'Rejected')
            """,
            "refinement": "Constrain status to Under Review, Approved, or Rejected.",
        },
        {
            "id": "invalid_operational_domains",
            "title": "Operational domain validation",
            "severity": "medium",
            "llmRationale": "The LLM review recommended turning UI dropdown values into backend-enforced domains.",
            "sql": """
                SELECT 'PET.species' AS field_name, pet_id AS record_id, species AS value
                FROM PET
                WHERE species NOT IN ('Dog', 'Cat', 'Rabbit', 'Bird')
                UNION ALL
                SELECT 'PET.sex', pet_id, sex
                FROM PET
                WHERE sex IS NOT NULL AND sex NOT IN ('Male', 'Female', 'Unknown')
                UNION ALL
                SELECT 'APPLICANT.housing_type', applicant_id, housing_type
                FROM APPLICANT
                WHERE housing_type IS NOT NULL
                  AND housing_type NOT IN (
                    'Apartment', 'Condo', 'House', 'Townhouse',
                    'House with garden', 'House without garden', 'Shared housing'
                  )
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
            "refinement": "Backend CRUD validation now rejects values outside the controlled domains.",
        },
        {
            "id": "invalid_email_or_duplicate_email",
            "title": "Email format and uniqueness validation",
            "severity": "medium",
            "llmRationale": "Email fields are common identifiers for applicants and volunteers and should not contain malformed or duplicate values.",
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
                UNION ALL
                SELECT 'APPLICANT.email duplicate', MIN(applicant_id), email
                FROM APPLICANT
                WHERE email IS NOT NULL AND email != ''
                GROUP BY lower(email)
                HAVING COUNT(*) > 1
                UNION ALL
                SELECT 'VOLUNTEER.email duplicate', MIN(volunteer_id), email
                FROM VOLUNTEER
                WHERE email IS NOT NULL AND email != ''
                GROUP BY lower(email)
                HAVING COUNT(*) > 1
            """,
            "refinement": "CRUD validation rejects malformed email addresses and duplicate applicant/volunteer emails.",
        },
        {
            "id": "capacity_exceeded",
            "title": "Shelter capacity consistency",
            "severity": "high",
            "llmRationale": "Capacity is a business rule that cannot be fully expressed by foreign keys alone.",
            "sql": """
                SELECT s.shelter_id, s.name, s.capacity, COUNT(p.pet_id) AS active_pet_count
                FROM SHELTER s
                JOIN PET p ON s.shelter_id = p.shelter_id
                WHERE lower(p.status) IN ('available', 'reserved', 'medical_hold')
                GROUP BY s.shelter_id, s.name, s.capacity
                HAVING COUNT(p.pet_id) > s.capacity
            """,
            "refinement": "Check capacity before intake or enforce via trigger.",
        },
        {
            "id": "invalid_temporal_ordering",
            "title": "Date and temporal consistency",
            "severity": "high",
            "llmRationale": "The LLM review identified temporal ordering as a business constraint that foreign keys cannot enforce.",
            "params": {"today": date.today().isoformat()},
            "sql": """
                SELECT 'PET.birth_after_intake' AS issue, pet_id AS record_id, estimated_birth_date AS first_date, intake_date AS second_date
                FROM PET
                WHERE estimated_birth_date IS NOT NULL
                  AND date(estimated_birth_date) > date(intake_date)
                UNION ALL
                SELECT 'PET.future_intake', pet_id, intake_date, :today
                FROM PET
                WHERE date(intake_date) > date(:today)
                UNION ALL
                SELECT 'APPLICANT.future_created_at', applicant_id, created_at, :today
                FROM APPLICANT
                WHERE created_at IS NOT NULL
                  AND date(created_at) > date(:today)
                UNION ALL
                SELECT 'VOLUNTEER.future_join_date', volunteer_id, join_date, :today
                FROM VOLUNTEER
                WHERE join_date IS NOT NULL
                  AND date(join_date) > date(:today)
                UNION ALL
                SELECT 'MEDICAL.before_intake', m.record_id, m.visit_date, p.intake_date
                FROM MEDICAL_RECORD m
                JOIN PET p ON m.pet_id = p.pet_id
                WHERE date(m.visit_date) < date(p.intake_date)
                UNION ALL
                SELECT 'MEDICAL.future_visit', record_id, visit_date, :today
                FROM MEDICAL_RECORD
                WHERE date(visit_date) > date(:today)
                UNION ALL
                SELECT 'VACCINATION.before_intake', v.vaccination_id, v.vaccination_date, p.intake_date
                FROM VACCINATION v
                JOIN PET p ON v.pet_id = p.pet_id
                WHERE date(v.vaccination_date) < date(p.intake_date)
                UNION ALL
                SELECT 'VACCINATION.future_given', vaccination_id, vaccination_date, :today
                FROM VACCINATION
                WHERE date(vaccination_date) > date(:today)
                UNION ALL
                SELECT 'VACCINATION.due_before_given', vaccination_id, next_due_date, vaccination_date
                FROM VACCINATION
                WHERE next_due_date IS NOT NULL
                  AND date(next_due_date) < date(vaccination_date)
                UNION ALL
                SELECT 'FOLLOW_UP.before_adoption', f.followup_id, f.followup_date, ar.adoption_date
                FROM FOLLOW_UP f
                JOIN ADOPTION_RECORD ar ON f.adoption_id = ar.adoption_id
                WHERE date(f.followup_date) < date(ar.adoption_date)
                UNION ALL
                SELECT 'FOLLOW_UP.future_followup', followup_id, followup_date, :today
                FROM FOLLOW_UP
                WHERE date(followup_date) > date(:today)
                UNION ALL
                SELECT 'CARE.after_adoption', c.assignment_id, c.assignment_date, ar.adoption_date
                FROM CARE_ASSIGNMENT c
                JOIN ADOPTION_APPLICATION aa ON c.pet_id = aa.pet_id AND aa.status = 'Approved'
                JOIN ADOPTION_RECORD ar ON aa.application_id = ar.application_id
                WHERE c.status != 'Cancelled'
                  AND date(c.assignment_date) >= date(ar.adoption_date)
                UNION ALL
                SELECT 'CARE.completed_future', assignment_id, assignment_date, :today
                FROM CARE_ASSIGNMENT
                WHERE status = 'Completed'
                  AND date(assignment_date) > date(:today)
            """,
            "refinement": "CRUD validation enforces date order for pet intake, medical visits, vaccinations, follow-ups, and care assignments.",
        },
        {
            "id": "application_before_pet_intake",
            "title": "Application cannot predate pet intake",
            "severity": "high",
            "llmRationale": "Applications for a pet that has not yet entered the shelter create an invalid operational timeline.",
            "sql": """
                SELECT a.application_id, a.pet_id, a.application_date, p.intake_date
                FROM ADOPTION_APPLICATION a
                JOIN PET p ON a.pet_id = p.pet_id
                WHERE date(a.application_date) < date(p.intake_date)
            """,
            "refinement": "Application creation now rejects pets whose intake date is later than the application date, and pet intake edits cannot move past existing activity.",
        },
        {
            "id": "cross_shelter_care_assignment",
            "title": "Care assignments must stay within one shelter",
            "severity": "high",
            "llmRationale": "Volunteers and pets each belong to exactly one shelter, so cross-shelter care assignments indicate broken relationship semantics.",
            "sql": """
                SELECT c.assignment_id, c.volunteer_id, v.shelter_id AS volunteer_shelter_id, c.pet_id, p.shelter_id AS pet_shelter_id
                FROM CARE_ASSIGNMENT c
                JOIN VOLUNTEER v ON c.volunteer_id = v.volunteer_id
                JOIN PET p ON c.pet_id = p.pet_id
                WHERE v.shelter_id != p.shelter_id
            """,
            "refinement": "Care assignment creation now requires the volunteer and pet to belong to the same shelter, and shelter edits cannot retroactively break existing assignments.",
        },
        {
            "id": "care_assignment_before_volunteer_join",
            "title": "Care assignment cannot predate volunteer join date",
            "severity": "medium",
            "llmRationale": "Assignments before a volunteer officially joins the shelter are timeline anomalies.",
            "sql": """
                SELECT c.assignment_id, c.assignment_date, v.volunteer_id, v.join_date
                FROM CARE_ASSIGNMENT c
                JOIN VOLUNTEER v ON c.volunteer_id = v.volunteer_id
                WHERE v.join_date IS NOT NULL
                  AND date(c.assignment_date) < date(v.join_date)
            """,
            "refinement": "Care assignment validation now checks volunteer join date, and volunteer join-date edits cannot move later than existing assignments.",
        },
        {
            "id": "reserved_without_pending_application",
            "title": "Reserved pet must have a pending application",
            "severity": "medium",
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
            "refinement": "Application creation reserves the pet, and rejection releases it when no other pending application exists.",
        },
        {
            "id": "pending_application_pet_not_reserved",
            "title": "Pending application should reserve the pet",
            "severity": "medium",
            "llmRationale": "The LLM review connected application workflow state to pet availability state.",
            "sql": """
                SELECT a.application_id, p.pet_id, p.name, p.status
                FROM ADOPTION_APPLICATION a
                JOIN PET p ON a.pet_id = p.pet_id
                WHERE a.status = 'Under Review'
                  AND lower(p.status) != 'reserved'
            """,
            "refinement": "Create applications only for available pets and update PET.status to reserved in the same transaction.",
        },
        {
            "id": "adopted_pet_without_approved_application",
            "title": "Adopted pet must have an approved application",
            "severity": "high",
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
            "refinement": "Direct PET edits cannot mark a pet as Adopted unless an approved application exists.",
        },
        {
            "id": "adoption_record_without_approved_application",
            "title": "Adoption record must reference an approved application",
            "severity": "high",
            "llmRationale": "A final adoption should not exist unless the corresponding application reached Approved.",
            "sql": """
                SELECT ar.adoption_id, ar.application_id, aa.status
                FROM ADOPTION_RECORD ar
                JOIN ADOPTION_APPLICATION aa ON ar.application_id = aa.application_id
                WHERE aa.status != 'Approved'
            """,
            "refinement": "Add an application-status check before creating an adoption record.",
        },
        {
            "id": "approved_application_without_adoption_record",
            "title": "Approved application must generate an adoption record",
            "severity": "high",
            "llmRationale": "The ER relationship results_in means an approved adoption decision should produce the final ADOPTION_RECORD used for follow-ups.",
            "sql": """
                SELECT aa.application_id, aa.pet_id, aa.reviewed_date
                FROM ADOPTION_APPLICATION aa
                LEFT JOIN ADOPTION_RECORD ar ON aa.application_id = ar.application_id
                WHERE aa.status = 'Approved'
                  AND ar.adoption_id IS NULL
            """,
            "refinement": "Approval inserts the ADOPTION_RECORD, and server startup reconciles historical approved applications.",
        },
        {
            "id": "multiple_approved_applications_for_one_pet",
            "title": "Only one application may be finally approved for a pet",
            "severity": "high",
            "llmRationale": "The ER rules allow multiple applications over time, but only one can end as the accepted adoption for a pet.",
            "sql": """
                SELECT pet_id, COUNT(*) AS approved_application_count
                FROM ADOPTION_APPLICATION
                WHERE status = 'Approved'
                GROUP BY pet_id
                HAVING COUNT(*) > 1
            """,
            "refinement": "Approval now checks for an existing approved application for the same pet inside a serialized write transaction.",
        },
        {
            "id": "multiple_adoption_records_for_one_application",
            "title": "One application can create at most one adoption record",
            "severity": "high",
            "llmRationale": "The ER relationship between AdoptionApplication and AdoptionRecord is 1:0..1, so duplicate final records are invalid.",
            "sql": """
                SELECT application_id, COUNT(*) AS adoption_record_count
                FROM ADOPTION_RECORD
                GROUP BY application_id
                HAVING COUNT(*) > 1
            """,
            "refinement": "Approval reuses an existing adoption record for the same application and write operations are serialized to avoid duplicate inserts.",
        },
        {
            "id": "duplicate_active_applications",
            "title": "Avoid multiple pending applications by the same applicant for the same pet",
            "severity": "low",
            "llmRationale": "The LLM review suggested detecting duplicate active workflow records that could confuse staff decisions.",
            "sql": """
                SELECT applicant_id, pet_id, COUNT(*) AS active_application_count
                FROM ADOPTION_APPLICATION
                WHERE status = 'Under Review'
                GROUP BY applicant_id, pet_id
                HAVING COUNT(*) > 1
            """,
            "refinement": "Use a partial unique index in databases that support it, or enforce in application logic.",
        },
    ]

    audited = []
    for check in checks:
        result = fetch_check_rows(conn, check["sql"], check.get("params"))
        audited.append(
            {
                **{key: value for key, value in check.items() if key not in {"sql", "params"}},
                "sql": " ".join(check["sql"].split()),
                "findingCount": result["count"],
                "sampleRows": result["sampleRows"],
                "status": "Pass" if result["count"] == 0 else "Review",
            }
        )
    return audited


def fetch_llm_bonus(conn: sqlite3.Connection) -> dict:
    queries = load_query_registry()
    read_only_queries = [query for query in queries if is_read_only_query(query)]
    integrity_audit = fetch_integrity_audit(conn)
    issue_count = sum(check["findingCount"] for check in integrity_audit)

    architecture_refinements = [
        {
            "area": "Status domains",
            "originalDesign": "Status columns were modeled as VARCHAR fields.",
            "llmRefinement": "Treat PET.status, ADOPTION_APPLICATION.status, CARE_ASSIGNMENT.status, FOLLOW_UP.result_status, and other dropdown fields as controlled domains.",
            "implementation": "Backend CRUD validation rejects values outside the domain lists before they reach SQLite.",
            "benefit": "Prevents spelling variants and impossible workflow states.",
        },
        {
            "area": "Workflow integrity",
            "originalDesign": "Application and pet status could be updated independently.",
            "llmRefinement": "Create application and reserve pet in one transaction; release pet after rejection when no other pending application remains.",
            "implementation": "POST /api/applications and PATCH /api/applications/{id}/review update related rows transactionally.",
            "benefit": "Keeps adoption workflow consistent across PET and ADOPTION_APPLICATION.",
        },
        {
            "area": "Anomaly detection",
            "originalDesign": "Foreign keys catch missing parent rows but not business anomalies.",
            "llmRefinement": "Run periodic checks for invalid domains, malformed emails, over-capacity shelters, bad date ordering, workflow mismatches, and adoption records without approved applications.",
            "implementation": "GET /api/llm-bonus returns executable audit checks with finding counts and sample rows.",
            "benefit": "Makes data-quality validation visible and repeatable.",
        },
        {
            "area": "Efficient access",
            "originalDesign": "Tables were normalized but high-frequency access paths were not explicit in the UI layer.",
            "llmRefinement": "Index foreign keys, workflow statuses, and date fields used by dashboards and analytical queries.",
            "implementation": "src/schema/indexing.sql documents indexes for pet shelter/status, vaccination due dates, applications, assignments, and follow-ups.",
            "benefit": "Improves staff operations and analytical reports as data grows.",
        },
        {
            "area": "LLM query safety",
            "originalDesign": "Natural language querying could hallucinate table names or produce unsafe SQL.",
            "llmRefinement": "Use a predefined query registry and let the LLM select among reviewed SQL templates rather than executing arbitrary generated SQL.",
            "implementation": "MCP tools and /api/llm-query expose only named queries from src/queries, and the web assistant runs read-only SELECT queries.",
            "benefit": "Supports natural language access while limiting SQL injection and hallucinated schema risks.",
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

    refined_constraints = [
        {
            "name": "Pet status CHECK",
            "sql": "CHECK (status IN ('available', 'reserved', 'adopted', 'medical_hold'))",
            "reason": "Guarantees consistent pet workflow states.",
        },
        {
            "name": "Application status CHECK",
            "sql": "CHECK (status IN ('Under Review', 'Approved', 'Rejected'))",
            "reason": "Prevents unrecognized application review states.",
        },
        {
            "name": "Application status index",
            "sql": "CREATE INDEX idx_application_status ON ADOPTION_APPLICATION(status);",
            "reason": "Speeds up daily review queues and dashboard pending counts.",
        },
        {
            "name": "Vaccination due date index",
            "sql": "CREATE INDEX idx_vaccination_next_due ON VACCINATION(next_due_date);",
            "reason": "Speeds up upcoming vaccination reminders.",
        },
        {
            "name": "Care assignment status CHECK",
            "sql": "CHECK (status IN ('Scheduled', 'Completed', 'Cancelled'))",
            "reason": "Prevents care task workflow states outside the staff process.",
        },
        {
            "name": "Follow-up result CHECK",
            "sql": "CHECK (result_status IN ('Excellent', 'Good', 'Satisfactory', 'Needs Improvement'))",
            "reason": "Keeps post-adoption outcome analytics consistent.",
        },
        {
            "name": "Temporal business rule",
            "sql": "CHECK or trigger: followup_date >= adoption_date; next_due_date >= vaccination_date;",
            "reason": "Prevents impossible date sequences that foreign keys cannot catch.",
        },
        {
            "name": "Email uniqueness",
            "sql": "CREATE UNIQUE INDEX idx_applicant_email_unique ON APPLICANT(lower(email));",
            "reason": "Prevents duplicated applicant identity records when email is provided.",
        },
    ]

    return {
        "summary": {
            "bonusGoal": "LLM + Database",
            "architectureRefinementCount": len(architecture_refinements),
            "integrityCheckCount": len(integrity_audit),
            "openFindingCount": issue_count,
            "safeReadOnlyQueryCount": len(read_only_queries),
            "method": "LLM-assisted design review plus safe natural-language query routing over a predefined SQL registry.",
        },
        "architectureRefinements": architecture_refinements,
        "refinedConstraints": refined_constraints,
        "integrityAudit": integrity_audit,
        "promptPatterns": prompt_patterns,
        "queryCatalog": [
            {
                "name": query.name,
                "title": query.title,
                "description": query.description,
                "category": query.category,
                "readOnly": is_read_only_query(query),
            }
            for query in queries
        ],
    }


def run_llm_query(conn: sqlite3.Connection, payload: dict) -> dict:
    prompt = (payload.get("prompt") or "").strip()
    if not prompt:
        raise ApiError(HTTPStatus.BAD_REQUEST, "Prompt is required.")

    read_only_queries = [query for query in load_query_registry() if is_read_only_query(query)]
    if not read_only_queries:
        raise ApiError(HTTPStatus.INTERNAL_SERVER_ERROR, "No read-only queries are registered.")

    query = match_query_from_prompt(prompt, read_only_queries)
    rows = execute_read_only_query(conn, query)
    return {
        "prompt": prompt,
        "matchedQuery": {
            "name": query.name,
            "title": query.title,
            "description": query.description,
            "category": query.category,
            "sql": normalize_sql(query.sql),
        },
        "rowCount": len(rows),
        "rows": rows[:50],
        "safetyModel": "The prompt is routed to a reviewed predefined SELECT query. Arbitrary generated SQL is not executed.",
    }


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
        "SELECT applicant_id FROM APPLICANT WHERE applicant_id = ?", (applicant_id,)
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
    if db_date(pet["intake_date"]) > date.today():
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

    if housing_type:
        conn.execute(
            "UPDATE APPLICANT SET housing_type = ? WHERE applicant_id = ?",
            (housing_type, applicant_id),
        )

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
        (new_id, applicant_id, pet_id, date.today().isoformat(), reason),
    )
    conn.execute("UPDATE PET SET status = 'reserved' WHERE pet_id = ?", (pet_id,))
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
    if application_status_label(app["status"]) != "Pending":
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

    conn.execute(
        """
        UPDATE ADOPTION_APPLICATION
        SET status = ?,
            reviewed_date = ?,
            reviewer_name = ?,
            decision_note = ?
        WHERE application_id = ?
        """,
        (decision, date.today().isoformat(), reviewer, note, application_id),
    )

    if decision == "Approved":
        final_fee = None
        if final_fee_raw is not None and final_fee_raw != "":
            try:
                final_fee = float(final_fee_raw)
            except (TypeError, ValueError) as exc:
                raise ApiError(HTTPStatus.BAD_REQUEST, "Final adoption fee must be a number.") from exc
            if not math.isfinite(final_fee) or final_fee < 0:
                raise ApiError(HTTPStatus.BAD_REQUEST, "Final adoption fee must be a non-negative finite number.")

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
                    date.today().isoformat(),
                    final_fee,
                    handover_note or note,
                ),
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
                date.today().isoformat(),
                reviewer,
                f"Automatically closed because {display_id('APP', application_id)} was approved.",
                app["pet_id"],
                application_id,
            ),
        )

    reconcile_pet_workflow_states(conn, app["pet_id"])

    return fetch_application(conn, application_id)


def create_follow_up(conn: sqlite3.Connection, payload: dict) -> dict:
    adoption_id = coerce_crud_value("adoptionId", payload.get("adoptionId"), "positive_int", True)
    followup_date = coerce_crud_value(
        "followupDate",
        payload.get("followupDate") or date.today().isoformat(),
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
        try:
            datetime.strptime(text, "%Y-%m-%d")
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


def assert_unique_email(
    conn: sqlite3.Connection,
    table: str,
    pk: str,
    email: str | None,
    item_id: int | None,
    label: str,
) -> None:
    if not email:
        return
    params: list[Any] = [email.lower()]
    sql = f"SELECT {pk} FROM {table} WHERE lower(email) = ?"
    if item_id is not None:
        sql += f" AND {pk} != ?"
        params.append(item_id)
    if conn.execute(sql, params).fetchone():
        raise ApiError(HTTPStatus.CONFLICT, f"{label} email already exists.")


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
        f"""
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
        if intake_date > date.today():
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

    elif resource == "applicants":
        if values.get("created_at") and db_date(values["created_at"]) > date.today():
            raise ApiError(HTTPStatus.BAD_REQUEST, "Applicant created date cannot be in the future.")
        assert_unique_email(conn, "APPLICANT", "applicant_id", values.get("email"), item_id, "Applicant")

    elif resource == "medical-records":
        pet = ensure_exists(conn, "PET", "pet_id", values["pet_id"], "Pet")
        visit_date = db_date(values["visit_date"])
        if visit_date > date.today():
            raise ApiError(HTTPStatus.BAD_REQUEST, "Medical visit date cannot be in the future.")
        if visit_date < db_date(pet["intake_date"]):
            raise ApiError(HTTPStatus.BAD_REQUEST, "Medical visit date cannot be before pet intake date.")

    elif resource == "vaccinations":
        pet = ensure_exists(conn, "PET", "pet_id", values["pet_id"], "Pet")
        vaccination_date = db_date(values["vaccination_date"])
        if vaccination_date > date.today():
            raise ApiError(HTTPStatus.BAD_REQUEST, "Vaccination date cannot be in the future.")
        if vaccination_date < db_date(pet["intake_date"]):
            raise ApiError(HTTPStatus.BAD_REQUEST, "Vaccination date cannot be before pet intake date.")
        if values.get("next_due_date") and db_date(values["next_due_date"]) < vaccination_date:
            raise ApiError(HTTPStatus.BAD_REQUEST, "Next due date cannot be before vaccination date.")

    elif resource == "volunteers":
        ensure_exists(conn, "SHELTER", "shelter_id", values["shelter_id"], "Shelter")
        assert_unique_email(conn, "VOLUNTEER", "volunteer_id", values.get("email"), item_id, "Volunteer")
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
        followup_date = db_date(values["followup_date"])
        if followup_date > date.today():
            raise ApiError(HTTPStatus.BAD_REQUEST, "Follow-up date cannot be in the future.")
        if followup_date < db_date(adoption["adoption_date"]):
            raise ApiError(HTTPStatus.BAD_REQUEST, "Follow-up date cannot be before adoption date.")


def next_resource_id(conn: sqlite3.Connection, table: str, pk: str) -> int:
    return conn.execute(
        f"SELECT COALESCE(MAX({pk}), 0) + 1 AS next_id FROM {table}"
    ).fetchone()["next_id"]


def ensure_resource_exists(conn: sqlite3.Connection, table: str, pk: str, item_id: int) -> None:
    row = conn.execute(f"SELECT 1 FROM {table} WHERE {pk} = ?", (item_id,)).fetchone()
    if not row:
        raise ApiError(HTTPStatus.NOT_FOUND, "Record not found.")


def assert_resource_deletable(conn: sqlite3.Connection, resource: str, item_id: int) -> None:
    references = {
        "shelters": [
            ("PET", "shelter_id", "linked pets"),
            ("VOLUNTEER", "shelter_id", "linked volunteers"),
        ],
        "applicants": [("ADOPTION_APPLICATION", "applicant_id", "adoption applications")],
        "pets": [
            ("ADOPTION_APPLICATION", "pet_id", "adoption applications"),
            ("MEDICAL_RECORD", "pet_id", "medical records"),
            ("VACCINATION", "pet_id", "vaccinations"),
            ("CARE_ASSIGNMENT", "pet_id", "care assignments"),
        ],
        "volunteers": [("CARE_ASSIGNMENT", "volunteer_id", "care assignments")],
        "adoption-records": [("FOLLOW_UP", "adoption_id", "follow-ups")],
    }
    for table, column, label in references.get(resource, []):
        count = conn.execute(
            f"SELECT COUNT(*) AS count FROM {table} WHERE {column} = ?",
            (item_id,),
        ).fetchone()["count"]
        if count:
            raise ApiError(
                HTTPStatus.CONFLICT,
                f"This record cannot be deleted because it has {label}.",
            )


def create_resource(conn: sqlite3.Connection, resource: str, payload: dict) -> dict:
    config = CRUD_CONFIGS[resource]
    values = crud_values(resource, payload)
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
    return resource_payload(conn, resource)


def delete_resource(conn: sqlite3.Connection, resource: str, item_id: int) -> dict:
    config = CRUD_CONFIGS[resource]
    ensure_resource_exists(conn, config["table"], config["pk"], item_id)
    assert_resource_deletable(conn, resource, item_id)
    conn.execute(f"DELETE FROM {config['table']} WHERE {config['pk']} = ?", (item_id,))
    return resource_payload(conn, resource)


def api_payload(path: str, query: dict[str, list[str]]) -> dict:
    with connect() as conn:
        if path == "/api/health":
            return {"ok": True, "database": str(DB_PATH)}
        if path == "/api/options":
            return {"options": DOMAIN_OPTIONS}
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
            self.write_json({"error": exc.message}, exc.status)
        except Exception as exc:
            self.write_json({"error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        try:
            payload = self.read_json_body()
            if parsed.path == "/api/applications":
                with connect() as conn:
                    begin_write(conn)
                    result = create_application(conn, payload)
                    conn.commit()
                self.write_json({"application": result}, HTTPStatus.CREATED)
                return
            if parsed.path == "/api/llm-query":
                with connect() as conn:
                    result = run_llm_query(conn, payload)
                self.write_json(result)
                return
            if parsed.path == "/api/follow-ups":
                with connect() as conn:
                    begin_write(conn)
                    result = create_follow_up(conn, payload)
                    conn.commit()
                self.write_json({"followUp": result}, HTTPStatus.CREATED)
                return
            parts = [part for part in parsed.path.split("/") if part]
            if len(parts) == 2 and parts[0] == "api" and parts[1] in CRUD_CONFIGS:
                with connect() as conn:
                    begin_write(conn)
                    result = create_resource(conn, parts[1], payload)
                    conn.commit()
                self.write_json(result, HTTPStatus.CREATED)
                return
            raise ApiError(HTTPStatus.NOT_FOUND, "Endpoint not found.")
        except ApiError as exc:
            self.write_json({"error": exc.message}, exc.status)
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
                with connect() as conn:
                    begin_write(conn)
                    result = review_application(conn, application_id, payload)
                    conn.commit()
                self.write_json({"application": result})
                return
            if len(parts) == 3 and parts[0] == "api" and parts[1] in CRUD_CONFIGS:
                item_id = int(parts[2])
                with connect() as conn:
                    begin_write(conn)
                    result = update_resource(conn, parts[1], item_id, payload)
                    conn.commit()
                self.write_json(result)
                return
            raise ApiError(HTTPStatus.NOT_FOUND, "Endpoint not found.")
        except ValueError:
            self.write_json({"error": "Invalid record id."}, HTTPStatus.BAD_REQUEST)
        except sqlite3.IntegrityError as exc:
            self.write_json({"error": f"Database constraint failed: {exc}"}, HTTPStatus.CONFLICT)
        except ApiError as exc:
            self.write_json({"error": exc.message}, exc.status)
        except Exception as exc:
            self.write_json({"error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def do_DELETE(self) -> None:
        parsed = urlparse(self.path)
        try:
            parts = [part for part in parsed.path.split("/") if part]
            if len(parts) == 3 and parts[0] == "api" and parts[1] in CRUD_CONFIGS:
                item_id = int(parts[2])
                with connect() as conn:
                    begin_write(conn)
                    result = delete_resource(conn, parts[1], item_id)
                    conn.commit()
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
            self.write_json({"error": exc.message}, exc.status)
        except Exception as exc:
            self.write_json({"error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def read_json_body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        try:
            body = raw.decode("utf-8")
            return json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ApiError(HTTPStatus.BAD_REQUEST, "Request body must be valid JSON.") from exc

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

    initialize_database(reset=args.reset_db)
    server = ThreadingHTTPServer((args.host, args.port), PawTrackHandler)
    print(f"PawTrack API running at http://{args.host}:{args.port}")
    print(f"Open http://{args.host}:{args.port}/pawtrack_demo.html")
    server.serve_forever()


if __name__ == "__main__":
    main()
