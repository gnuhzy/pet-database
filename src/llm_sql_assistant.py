from __future__ import annotations

import json
import os
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from http import HTTPStatus
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import quote

from query_registry import StoredQuery, load_query_registry


DEFAULT_MODEL = "glm-5.1"
DEFAULT_BASE_URL = "https://open.bigmodel.cn/api/paas/v4/"
DEFAULT_TIMEOUT_SECONDS = 30
MAX_RESULT_ROWS = 50
PROMPT_METHODS = ("zero_shot", "schema_grounded", "few_shot", "self_check_repair")
CASES_PATH = Path(__file__).resolve().parent / "llm_prompt_cases.json"
RESULTS_PATH = Path(__file__).resolve().parent / "llm_prompt_results.json"
ENV_PATH = Path(__file__).resolve().parent.parent / ".env"

BLOCKED_SQL_KEYWORDS = (
    "INSERT",
    "UPDATE",
    "DELETE",
    "DROP",
    "ALTER",
    "CREATE",
    "REPLACE",
    "TRUNCATE",
    "ATTACH",
    "DETACH",
    "PRAGMA",
    "VACUUM",
    "REINDEX",
)


class LlmSqlError(Exception):
    def __init__(self, status: HTTPStatus, message: str, payload: dict[str, Any] | None = None):
        super().__init__(message)
        self.status = status
        self.message = message
        self.payload = payload or {}


class ChatClient(Protocol):
    def complete_json(self, messages: list[dict[str, str]], response_format: dict[str, str] | None = None) -> str:
        ...


@dataclass(frozen=True)
class LlmConfig:
    api_key: str | None
    model: str = DEFAULT_MODEL
    base_url: str = DEFAULT_BASE_URL
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS

    @classmethod
    def from_env(cls) -> "LlmConfig":
        local_env = read_local_env()

        def config_value(name: str, default: str | None = None) -> str | None:
            return os.getenv(name) or local_env.get(name) or default

        timeout_raw = config_value("LLM_SQL_TIMEOUT_SECONDS", str(DEFAULT_TIMEOUT_SECONDS))
        try:
            timeout_seconds = max(1, int(timeout_raw or DEFAULT_TIMEOUT_SECONDS))
        except ValueError:
            timeout_seconds = DEFAULT_TIMEOUT_SECONDS
        return cls(
            api_key=config_value("ZAI_API_KEY") or config_value("GLM_API_KEY"),
            model=config_value("GLM_MODEL", DEFAULT_MODEL) or DEFAULT_MODEL,
            base_url=config_value("GLM_BASE_URL", DEFAULT_BASE_URL) or DEFAULT_BASE_URL,
            timeout_seconds=timeout_seconds,
        )


def read_local_env(path: Path | None = None) -> dict[str, str]:
    path = path or ENV_PATH
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            values[key] = value
    return values


class GlmChatClient:
    def __init__(self, config: LlmConfig):
        if not config.api_key:
            raise LlmSqlError(
                HTTPStatus.SERVICE_UNAVAILABLE,
                "ZAI_API_KEY is not configured. Set ZAI_API_KEY or GLM_API_KEY before using GLM-generated SQL.",
            )
        self.config = config

    def complete_json(self, messages: list[dict[str, str]], response_format: dict[str, str] | None = None) -> str:
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise LlmSqlError(
                HTTPStatus.SERVICE_UNAVAILABLE,
                "The openai package is required for GLM-generated SQL. Run pip install -r requirements.txt.",
            ) from exc

        client = OpenAI(
            api_key=self.config.api_key,
            base_url=self.config.base_url,
            timeout=self.config.timeout_seconds,
            max_retries=1,
        )
        try:
            response = client.chat.completions.create(
                model=self.config.model,
                messages=messages,
                temperature=0.2,
                max_tokens=1200,
                response_format=response_format or {"type": "json_object"},
            )
        except TimeoutError as exc:
            raise LlmSqlError(HTTPStatus.GATEWAY_TIMEOUT, "GLM request timed out.") from exc
        except Exception as exc:
            message = str(exc)
            status = HTTPStatus.GATEWAY_TIMEOUT if "timeout" in message.lower() else HTTPStatus.BAD_GATEWAY
            raise LlmSqlError(status, f"GLM request failed: {message}") from exc

        content = response.choices[0].message.content
        if not content:
            raise LlmSqlError(HTTPStatus.BAD_GATEWAY, "GLM returned an empty response.")
        return content


def read_prompt_cases(path: Path = CASES_PATH) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def read_prompt_results(path: Path = RESULTS_PATH) -> dict[str, Any]:
    if not path.exists():
        return {
            "generatedAt": None,
            "summary": {"total": 0, "jsonValid": 0, "safe": 0, "executable": 0},
            "methods": [],
            "results": [],
        }
    return json.loads(path.read_text(encoding="utf-8"))


def build_schema_context(conn: sqlite3.Connection) -> str:
    tables = conn.execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE type = 'table'
          AND name NOT LIKE 'sqlite_%'
        ORDER BY name
        """
    ).fetchall()
    lines = ["SQLite database schema for the pet adoption center:"]
    for table in tables:
        table_name = table["name"]
        lines.append(f"\nTABLE {table_name}")
        for col in conn.execute(f"PRAGMA table_info({quote_identifier(table_name)})").fetchall():
            nullable = "NOT NULL" if col["notnull"] else "NULLABLE"
            pk = " PRIMARY KEY" if col["pk"] else ""
            default = f" DEFAULT {col['dflt_value']}" if col["dflt_value"] is not None else ""
            lines.append(f"- {col['name']} {col['type']} {nullable}{pk}{default}")
        foreign_keys = conn.execute(f"PRAGMA foreign_key_list({quote_identifier(table_name)})").fetchall()
        for fk in foreign_keys:
            lines.append(f"- FK {fk['from']} -> {fk['table']}.{fk['to']}")
        indexes = conn.execute(f"PRAGMA index_list({quote_identifier(table_name)})").fetchall()
        for idx in indexes:
            index_cols = conn.execute(f"PRAGMA index_info({quote_identifier(idx['name'])})").fetchall()
            cols = ", ".join(col["name"] for col in index_cols)
            unique = " UNIQUE" if idx["unique"] else ""
            lines.append(f"- INDEX{unique} {idx['name']}({cols})")

    domain_lines = build_domain_context(conn)
    if domain_lines:
        lines.append("\nKnown business domains:")
        lines.extend(domain_lines)
    lines.append(
        "\nImportant rule: generate SQLite SQL only. Use date('now', '+8 hours') for current local date logic."
    )
    return "\n".join(lines)


def quote_identifier(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def build_domain_context(conn: sqlite3.Connection) -> list[str]:
    domains = [
        ("PET", "status"),
        ("PET", "species"),
        ("PET", "sex"),
        ("ADOPTION_APPLICATION", "status"),
        ("APPLICANT", "housing_type"),
        ("CARE_ASSIGNMENT", "shift"),
        ("CARE_ASSIGNMENT", "task_type"),
        ("CARE_ASSIGNMENT", "status"),
        ("FOLLOW_UP", "followup_type"),
        ("FOLLOW_UP", "result_status"),
        ("MEDICAL_RECORD", "record_type"),
    ]
    lines: list[str] = []
    for table_name, column_name in domains:
        try:
            rows = conn.execute(
                f"""
                SELECT DISTINCT {quote_identifier(column_name)} AS value
                FROM {quote_identifier(table_name)}
                WHERE {quote_identifier(column_name)} IS NOT NULL
                ORDER BY value
                """
            ).fetchall()
        except sqlite3.Error:
            continue
        values = [str(row["value"]) for row in rows]
        if values:
            lines.append(f"- {table_name}.{column_name}: {', '.join(values)}")
    return lines


def build_prompt_messages(prompt: str, prompt_method: str, schema_context: str) -> list[dict[str, str]]:
    if prompt_method not in PROMPT_METHODS:
        raise LlmSqlError(
            HTTPStatus.BAD_REQUEST,
            f"Unsupported promptMethod '{prompt_method}'. Choose one of: {', '.join(PROMPT_METHODS)}.",
        )

    output_contract = (
        "Return only a JSON object with keys sql, explanation, tables_used, assumptions, confidence, prompt_method. "
        "The sql value must be a single SQLite SELECT query or a read-only WITH query. "
        "Never use INSERT, UPDATE, DELETE, DROP, ALTER, CREATE, REPLACE, TRUNCATE, ATTACH, DETACH, PRAGMA, VACUUM, or REINDEX."
    )
    system = (
        "You convert pet adoption center questions into safe SQLite information-retrieval SQL. "
        "You do not modify data. You prefer clear joins, explicit aliases, and readable aggregate names. "
        + output_contract
    )

    user_parts = [f"User question: {prompt}"]
    if prompt_method in {"schema_grounded", "few_shot", "self_check_repair"}:
        user_parts.append(schema_context)
    if prompt_method in {"few_shot", "self_check_repair"}:
        user_parts.append(build_few_shot_examples())
    if prompt_method == "zero_shot":
        user_parts.append("Use only the database concepts mentioned by the user. If ambiguous, choose a conservative read-only summary query.")
    if prompt_method == "schema_grounded":
        user_parts.append("Use the provided schema exactly. Do not invent tables or columns.")
    if prompt_method == "few_shot":
        user_parts.append("Follow the style of the examples, but generate a query that answers the user question.")
    if prompt_method == "self_check_repair":
        user_parts.append(
            "Before returning JSON, self-check that every table and column exists in the schema, the SQL is one statement, "
            "and the query is read-only SQLite. If uncertain, simplify the query."
        )
    user_parts.append(f"Set prompt_method to {prompt_method}.")
    return [{"role": "system", "content": system}, {"role": "user", "content": "\n\n".join(user_parts)}]


def build_repair_messages(prompt: str, prompt_method: str, schema_context: str, sql: str, error: str) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": (
                "Repair a failed SQLite SELECT query. Return only JSON with keys sql, explanation, "
                "tables_used, assumptions, confidence, prompt_method. The repaired SQL must be one read-only SELECT or WITH query."
            ),
        },
        {
            "role": "user",
            "content": "\n\n".join(
                [
                    f"Original question: {prompt}",
                    f"Prompt method: {prompt_method}",
                    schema_context,
                    f"Failed SQL:\n{sql}",
                    f"SQLite error:\n{error}",
                    "Return a corrected safe SQLite query. Do not use PRAGMA or any write/DDL command.",
                ]
            ),
        },
    ]


def build_few_shot_examples(limit: int = 4) -> str:
    examples: list[str] = ["Representative reviewed SQL examples:"]
    for query in load_query_registry()[:limit]:
        examples.append(f"\nQuestion intent: {query.description}\nSQL:\n{query.sql}")
    return "\n".join(examples)


def parse_llm_json(raw: str, prompt_method: str) -> dict[str, Any]:
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise LlmSqlError(
            HTTPStatus.BAD_GATEWAY,
            "GLM returned non-JSON output.",
            {"rawResponse": raw[:1000], "jsonValid": False},
        ) from exc
    if not isinstance(data, dict):
        raise LlmSqlError(HTTPStatus.BAD_GATEWAY, "GLM JSON output must be an object.", {"jsonValid": False})
    sql = data.get("sql")
    if not isinstance(sql, str) or not sql.strip():
        raise LlmSqlError(HTTPStatus.BAD_GATEWAY, "GLM JSON output is missing a non-empty sql field.", {"jsonValid": True})
    data.setdefault("explanation", "")
    data.setdefault("tables_used", [])
    data.setdefault("assumptions", [])
    data.setdefault("confidence", None)
    data["prompt_method"] = data.get("prompt_method") or prompt_method
    return data


def strip_sql_comments(sql: str) -> str:
    result: list[str] = []
    i = 0
    in_single = False
    in_double = False
    while i < len(sql):
        ch = sql[i]
        nxt = sql[i + 1] if i + 1 < len(sql) else ""
        if in_single:
            result.append(ch)
            if ch == "'" and nxt == "'":
                result.append(nxt)
                i += 2
                continue
            if ch == "'":
                in_single = False
            i += 1
            continue
        if in_double:
            result.append(ch)
            if ch == '"' and nxt == '"':
                result.append(nxt)
                i += 2
                continue
            if ch == '"':
                in_double = False
            i += 1
            continue
        if ch == "'":
            in_single = True
            result.append(ch)
            i += 1
            continue
        if ch == '"':
            in_double = True
            result.append(ch)
            i += 1
            continue
        if ch == "-" and nxt == "-":
            i += 2
            while i < len(sql) and sql[i] not in "\r\n":
                i += 1
            result.append(" ")
            continue
        if ch == "/" and nxt == "*":
            i += 2
            while i + 1 < len(sql) and not (sql[i] == "*" and sql[i + 1] == "/"):
                i += 1
            i += 2
            result.append(" ")
            continue
        result.append(ch)
        i += 1
    return "".join(result)


def mask_sql_strings(sql: str) -> str:
    result: list[str] = []
    i = 0
    in_single = False
    in_double = False
    while i < len(sql):
        ch = sql[i]
        nxt = sql[i + 1] if i + 1 < len(sql) else ""
        if in_single:
            result.append(" ")
            if ch == "'" and nxt == "'":
                result.append(" ")
                i += 2
                continue
            if ch == "'":
                in_single = False
            i += 1
            continue
        if in_double:
            result.append(" ")
            if ch == '"' and nxt == '"':
                result.append(" ")
                i += 2
                continue
            if ch == '"':
                in_double = False
            i += 1
            continue
        if ch == "'":
            in_single = True
            result.append(" ")
        elif ch == '"':
            in_double = True
            result.append(" ")
        else:
            result.append(ch)
        i += 1
    return "".join(result)


def split_sql_statements(sql: str) -> list[str]:
    statements: list[str] = []
    current: list[str] = []
    in_single = False
    in_double = False
    i = 0
    while i < len(sql):
        ch = sql[i]
        nxt = sql[i + 1] if i + 1 < len(sql) else ""
        if in_single:
            current.append(ch)
            if ch == "'" and nxt == "'":
                current.append(nxt)
                i += 2
                continue
            if ch == "'":
                in_single = False
            i += 1
            continue
        if in_double:
            current.append(ch)
            if ch == '"' and nxt == '"':
                current.append(nxt)
                i += 2
                continue
            if ch == '"':
                in_double = False
            i += 1
            continue
        if ch == "'":
            in_single = True
            current.append(ch)
        elif ch == '"':
            in_double = True
            current.append(ch)
        elif ch == ";":
            statements.append("".join(current).strip())
            current = []
        else:
            current.append(ch)
        i += 1
    tail = "".join(current).strip()
    if tail:
        statements.append(tail)
    return [statement for statement in statements if statement]


def validate_generated_sql(sql: str) -> dict[str, Any]:
    cleaned = strip_sql_comments(sql).strip()
    statements = split_sql_statements(cleaned)
    if len(statements) != 1:
        return validation_result(False, "Generated SQL must contain exactly one statement.")
    statement = statements[0].strip()
    if not statement:
        return validation_result(False, "Generated SQL is empty after removing comments.")

    masked = mask_sql_strings(statement)
    for keyword in BLOCKED_SQL_KEYWORDS:
        if re.search(rf"\b{keyword}\b", masked, flags=re.IGNORECASE):
            return validation_result(False, f"Blocked SQL keyword is not allowed: {keyword}.")

    if not re.match(r"^\s*(SELECT|WITH)\b", statement, flags=re.IGNORECASE):
        return validation_result(False, "Generated SQL must start with SELECT or WITH.")

    return validation_result(True, "SQL passed static read-only checks.", normalized_sql=statement)


def validation_result(safe: bool, reason: str, normalized_sql: str | None = None) -> dict[str, Any]:
    result = {
        "safe": safe,
        "readOnly": safe,
        "reason": reason,
        "checkedBy": ["comment_strip", "single_statement", "blocked_keyword_scan", "select_only"],
    }
    if normalized_sql is not None:
        result["normalizedSql"] = normalized_sql
    return result


def readonly_db_uri(db_path: Path) -> str:
    return f"file:{quote(str(db_path), safe='/:')}?mode=ro"


def install_readonly_authorizer(conn: sqlite3.Connection) -> None:
    allowed = {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_FUNCTION}

    def authorizer(action: int, arg1: str | None, arg2: str | None, db_name: str | None, source: str | None) -> int:
        return sqlite3.SQLITE_OK if action in allowed else sqlite3.SQLITE_DENY

    conn.set_authorizer(authorizer)


def install_progress_guard(conn: sqlite3.Connection, max_callbacks: int = 100000) -> None:
    counter = {"count": 0}

    def progress() -> int:
        counter["count"] += 1
        return 1 if counter["count"] > max_callbacks else 0

    conn.set_progress_handler(progress, 1000)


def execute_generated_select(db_path: Path, sql: str, max_rows: int = MAX_RESULT_ROWS) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    validation = validate_generated_sql(sql)
    if not validation["safe"]:
        raise LlmSqlError(
            HTTPStatus.BAD_REQUEST,
            validation["reason"],
            {"validation": validation, "generatedSql": sql},
        )

    normalized_sql = validation["normalizedSql"]
    try:
        conn = sqlite3.connect(readonly_db_uri(db_path), uri=True, timeout=10)
        conn.row_factory = sqlite3.Row
        install_readonly_authorizer(conn)
        install_progress_guard(conn)
        conn.execute(f"EXPLAIN QUERY PLAN {normalized_sql}").fetchall()
        cursor = conn.execute(normalized_sql)
        rows = [dict(row) for row in cursor.fetchmany(max_rows + 1)]
    except sqlite3.Error as exc:
        raise LlmSqlError(
            HTTPStatus.UNPROCESSABLE_ENTITY,
            f"Generated SQL failed SQLite validation: {exc}",
            {"validation": validation, "generatedSql": sql, "sqliteError": str(exc)},
        ) from exc
    finally:
        try:
            conn.close()
        except UnboundLocalError:
            pass

    if len(rows) > max_rows:
        rows = rows[:max_rows]
        validation["truncated"] = True
    else:
        validation["truncated"] = False
    validation["checkedBy"] = [*validation["checkedBy"], "sqlite_authorizer", "explain_query_plan", "progress_guard"]
    return rows, validation


def run_prompt_to_sql(
    conn: sqlite3.Connection,
    payload: dict[str, Any],
    db_path: Path,
    client: ChatClient | None = None,
) -> dict[str, Any]:
    prompt = (payload.get("prompt") or "").strip()
    if not prompt:
        raise LlmSqlError(HTTPStatus.BAD_REQUEST, "Prompt is required.")
    prompt_method = payload.get("promptMethod") or "schema_grounded"
    if prompt_method not in PROMPT_METHODS:
        raise LlmSqlError(
            HTTPStatus.BAD_REQUEST,
            f"Unsupported promptMethod '{prompt_method}'. Choose one of: {', '.join(PROMPT_METHODS)}.",
        )
    execute = bool(payload.get("execute", True))
    config = LlmConfig.from_env()
    chat_client = client or GlmChatClient(config)
    schema_context = build_schema_context(conn)
    messages = build_prompt_messages(prompt, prompt_method, schema_context)
    raw = chat_client.complete_json(messages, {"type": "json_object"})
    llm_output = parse_llm_json(raw, prompt_method)
    sql = llm_output["sql"]
    repair_attempts = 0

    validation = validate_generated_sql(sql)
    if not validation["safe"]:
        raise LlmSqlError(
            HTTPStatus.BAD_REQUEST,
            validation["reason"],
            {"validation": validation, "generatedSql": sql},
        )

    rows: list[dict[str, Any]] = []
    if execute:
        try:
            rows, validation = execute_generated_select(db_path, sql)
        except LlmSqlError as exc:
            if prompt_method != "self_check_repair" or exc.status == HTTPStatus.BAD_REQUEST:
                raise
            repair_attempts = 1
            repair_messages = build_repair_messages(prompt, prompt_method, schema_context, sql, exc.message)
            repaired_raw = chat_client.complete_json(repair_messages, {"type": "json_object"})
            llm_output = parse_llm_json(repaired_raw, prompt_method)
            sql = llm_output["sql"]
            rows, validation = execute_generated_select(db_path, sql)

    return {
        "provider": "zhipu-glm",
        "model": config.model,
        "prompt": prompt,
        "promptMethod": prompt_method,
        "generatedSql": sql,
        "explanation": llm_output.get("explanation", ""),
        "tablesUsed": llm_output.get("tables_used", []),
        "assumptions": llm_output.get("assumptions", []),
        "confidence": llm_output.get("confidence"),
        "validation": validation,
        "rowCount": len(rows),
        "rows": rows,
        "repairAttempts": repair_attempts,
    }


def evaluate_cases(
    conn: sqlite3.Connection,
    db_path: Path,
    methods: list[str],
    client: ChatClient | None = None,
) -> dict[str, Any]:
    cases = read_prompt_cases()
    results: list[dict[str, Any]] = []
    for case in cases:
        for method in methods:
            prompt = case["prompt"]
            record = {
                "caseId": case.get("id"),
                "category": case.get("category"),
                "prompt": prompt,
                "promptMethod": method,
                "jsonValid": False,
                "safe": False,
                "executable": False,
                "rowCount": 0,
                "generatedSql": "",
                "errorType": None,
            }
            try:
                response = run_prompt_to_sql(
                    conn,
                    {"prompt": prompt, "promptMethod": method, "execute": True},
                    db_path,
                    client=client,
                )
                record.update(
                    {
                        "jsonValid": True,
                        "safe": bool(response["validation"]["safe"]),
                        "executable": True,
                        "rowCount": response["rowCount"],
                        "generatedSql": response["generatedSql"],
                    }
                )
            except LlmSqlError as exc:
                record["errorType"] = exc.status.phrase
                record["error"] = exc.message
                record["safe"] = bool(exc.payload.get("validation", {}).get("safe", False))
                record["generatedSql"] = exc.payload.get("generatedSql", "")
                record["jsonValid"] = exc.payload.get("jsonValid", True)
            results.append(record)

    summary = summarize_eval_results(results)
    return {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "summary": summary,
        "methods": summarize_methods(results),
        "results": results,
    }


def summarize_eval_results(results: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "total": len(results),
        "jsonValid": sum(1 for row in results if row.get("jsonValid")),
        "safe": sum(1 for row in results if row.get("safe")),
        "executable": sum(1 for row in results if row.get("executable")),
    }


def summarize_methods(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    methods: list[dict[str, Any]] = []
    for method in PROMPT_METHODS:
        rows = [row for row in results if row.get("promptMethod") == method]
        if not rows:
            continue
        total = len(rows)
        methods.append(
            {
                "method": method,
                "total": total,
                "jsonValid": sum(1 for row in rows if row.get("jsonValid")),
                "safe": sum(1 for row in rows if row.get("safe")),
                "executable": sum(1 for row in rows if row.get("executable")),
            }
        )
    return methods
