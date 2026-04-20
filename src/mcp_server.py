"""
Pet Database MCP Server

Exposes pre-defined SQL queries from src/queries/ as callable MCP tools,
allowing an external LLM to query the pet adoption center database via natural language.
Only queries defined in src/queries/ can be executed — no arbitrary SQL allowed.
"""

import re
import sqlite3
from pathlib import Path
from dataclasses import dataclass, field
from typing import Any

from mcp.server import Server
from mcp.types import Tool, TextContent
from mcp import stdio_server

# ── Database ──────────────────────────────────────────────────────────────────

DB_PATH = Path(__file__).parent.parent / "pet_database.db"

# ── Query Registry ─────────────────────────────────────────────────────────────

@dataclass
class QueryParam:
    name: str
    type: str          # 'string' or 'integer'
    description: str

@dataclass
class StoredQuery:
    name: str
    description: str
    sql: str
    category: str
    params: list[QueryParam] = field(default_factory=list)
    is_write: bool = False

def load_queries() -> list[StoredQuery]:
    queries_dir = Path(__file__).parent.parent / "src" / "queries"
    queries: list[StoredQuery] = []

    for sql_file in sorted(queries_dir.glob("*.sql")):
        category = sql_file.stem.replace("_queries", "").replace("_", " ")
        raw = sql_file.read_text()
        parsed = parse_sql_file(raw, category)
        queries.extend(parsed)

    return queries

def parse_sql_file(content: str, category: str) -> list[StoredQuery]:
    queries: list[StoredQuery] = []
    headers = list(re.finditer(r'^-- Q\d+:\s*(.+?)$', content, re.MULTILINE))
    for i, m in enumerate(headers):
        title = m.group(1).strip()
        start = m.start()
        end = headers[i + 1].start() if i + 1 < len(headers) else len(content)
        chunk = content[start:end]

        lines = chunk.split('\n')
        description_parts = []
        param_parts: list[str] = []
        sql_lines = []
        is_write = False

        for line in lines[1:]:
            stripped = line.strip()
            if stripped.startswith('-- Purpose:'):
                description_parts.append(stripped[len('-- Purpose:'):].strip())
            elif stripped.startswith('-- Params:'):
                param_parts.append(stripped[len('-- Params:'):].strip())
            elif stripped.startswith('--'):
                pass
            elif stripped:
                sql_lines.append(line)
                if re.match(r'^\s*(INSERT|UPDATE|DELETE)', stripped, re.IGNORECASE):
                    is_write = True

        description = ' '.join(description_parts)
        sql = '\n'.join(sql_lines).strip()
        params = _parse_params(param_parts)

        queries.append(StoredQuery(
            name=slugify(title),
            description=description,
            sql=sql,
            category=category,
            params=params,
            is_write=is_write,
        ))

    return queries

def _parse_params(parts: list[str]) -> list[QueryParam]:
    """Parse -- Params: lines into QueryParam list. Format: name:type:description[, name:type:description...]

    Multiple params can be on one line separated by commas.
    """
    params: list[QueryParam] = []
    for part in parts:
        for segment in part.split(','):
            segments = [s.strip() for s in segment.split(':')]
            if len(segments) >= 3:
                params.append(QueryParam(name=segments[0], type=segments[1], description=segments[2]))
            elif len(segments) == 2:
                params.append(QueryParam(name=segments[0], type=segments[1], description=''))
    return params

def slugify(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[_\s]+", "_", text)
    return text.strip("-_")

# ── SQL Normalization & Parameter Binding ─────────────────────────────────────

def _preprocess_date_params(sql: str, param_values: dict[str, Any]) -> str:
    """Replace DATE_ADD(CURDATE(), INTERVAL :param DAY) with computed date literals.

    This must happen before normalize_sql so the ? placeholder never appears
    inside a DATE_ADD string literal (SQLite doesn't support that).
    Uses default 30 days when days_ahead is not provided.
    """
    from datetime import date, timedelta
    days = param_values.get('days_ahead') or 30
    target = date.today() + timedelta(days=int(days))
    sql = re.sub(
        r"DATE_ADD\s*\(\s*CURDATE\s*\(\s*\)\s*,\s*INTERVAL\s+:days_ahead\s+DAY\s*\)",
        f"'{target}'",
        sql,
        flags=re.IGNORECASE
    )
    return sql

def normalize_sql(sql: str) -> tuple[str, list[str]]:
    """Convert MySQL SQL to SQLite.

    Handles three cases:
    1. DATE_ADD(CURDATE(), INTERVAL :param DAY) — replaced in execute_query/execute_write
       after binding the param value (SQLite can't bind inside string literals)
    2. DATEDIFF(CURDATE(), col) — converted to julianday arithmetic
    3. CURDATE() — replaced with date('now')

    Returns (normalized_sql, ordered_param_names).
    """
    # DATEDIFF(CURDATE(), col) BEFORE CURDATE replacement
    sql = re.sub(
        r"DATEDIFF\s*\(\s*CURDATE\s*\(\s*\)\s*,\s*(\w+)\s*\)",
        r"(cast(julianday('now') - julianday(\1) as integer))",
        sql,
        flags=re.IGNORECASE
    )

    # CURDATE() -> date('now')
    sql = re.sub(r"\bCURDATE\s*\(\s*\)", "date('now')", sql, flags=re.IGNORECASE)

    # Replace :param_name with ? and collect param names in order
    param_names = []
    def record_param(m):
        param_names.append(m.group(1))
        return "?"
    sql = re.sub(r":(\w+)", record_param, sql)

    return sql, param_names


def execute_query(sql: str, param_names: list[str], param_values: dict[str, Any]) -> list[dict[str, Any]]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    ordered_values = [param_values.get(p) for p in param_names]
    cur.execute(sql, ordered_values)
    rows = cur.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def execute_write(sql: str, param_names: list[str], param_values: dict[str, Any]) -> int:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    ordered_values = [param_values.get(p) for p in param_names]
    cur.execute(sql, ordered_values)
    rows_affected = cur.rowcount
    conn.commit()
    conn.close()
    return rows_affected




# ── MCP Server ─────────────────────────────────────────────────────────────────

APP_NAME = "pet-database-mcp"
APP_VERSION = "1.0.0"

server = Server(APP_NAME, version=APP_VERSION)

_query_registry: list[StoredQuery] = []
_query_map: dict[str, StoredQuery] = {}

def _build_registry():
    global _query_registry, _query_map
    _query_registry = load_queries()
    _query_map = {q.name: q for q in _query_registry}

@server.list_tools()
async def list_tools() -> list[Tool]:
    _build_registry()
    tools = [
        Tool(
            name="list_available_queries",
            description="List all available pre-defined SQL queries with their parameter descriptions.",
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
        Tool(
            name="execute_named_query",
            description="Execute a specific pre-defined query by name. Pass optional params to override defaults.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query_name": {"type": "string", "description": "Name of the query to execute."},
                    "params": {
                        "type": "object",
                        "description": "Query parameters as key-value pairs. Omit to use defaults.",
                        "additionalProperties": True,
                    },
                },
                "required": ["query_name"],
            },
        ),
        Tool(
            name="natural_language_query",
            description="Given a natural language question, selects the best matching pre-defined query, extracts parameters from the prompt, and executes it.",
            inputSchema={
                "type": "object",
                "properties": {
                    "nl_prompt": {"type": "string", "description": "A natural language question about the pet shelter database."},
                },
                "required": ["nl_prompt"],
            },
        ),
    ]
    return tools

# ── Parameter extraction from natural language ───────────────────────────────

def _extract_params(nl_prompt: str, query: StoredQuery) -> dict[str, Any]:
    """Extract parameter values from natural language prompt."""
    prompt_lower = nl_prompt.lower()
    extracted: dict[str, Any] = {}

    id_patterns = [
        (r'shelter\s+(\d+)', 'shelter_id'),
        (r'volunteer\s+(\d+)', 'volunteer_id'),
        (r'pet\s+(\d+)', 'pet_id'),
        (r'application\s+(\d+)', 'application_id'),
        (r'adoption\s+(\d+)', 'adoption_id'),
        (r'days?\s+(\d+)', 'days_ahead'),
    ]
    for pattern, param_name in id_patterns:
        m = re.search(pattern, prompt_lower)
        if m:
            extracted[param_name] = int(m.group(1))

    return extracted

# ── Query Matching ─────────────────────────────────────────────────────────────

def _match_query(nl_prompt: str) -> StoredQuery | None:
    prompt_lower = nl_prompt.lower()

    concept_map = [
        (["vaccination due", "vaccine due", "upcoming vaccination", "vaccination soon"],
         "view_pets_whose_vaccination_due"),
        (["adoptable", "available for adoption", "pets available", "available pets"],
         "view_all_pets_that_are_currently_available"),
        (["occupancy", "shelter occupancy", "shelter capacity", "how full"],
         "analyze_current_occupancy"),
        (["shelter", "shelter 1", "shelter 2", "pets in shelter", "pet list in shelter", "current pets in shelter"],
         "view_all_pets_currently_housed_in_a_specific_shelter"),
        (["health info", "medical history", "full health", "vaccination and medical"],
         "view_the_full_health_information"),
        (["volunteer assignment", "care assignment", "volunteer schedule"],
         "view_upcoming_care_assignments_for_a_volunteer"),
        (["approve", "approving", "approved", "adoption approval"],
         "approve_a_selected_adoption_application"),
        (["adoption application", "pending application", "under review"],
         "view_all_adoption_applications_that_are_currently_under_review"),
        (["follow-up outcome", "post-adoption", "adopter feedback", "followup outcome"],
         "analyze_post-adoption_follow-up_outcomes"),
        (["follow-up", "follow up", "record follow-up", "phone check"],
         "insert_a_follow-up_record"),
        (["long stay", "longest", "stay long"],
         "analyze_pets_that_have_stayed_the_longest"),
        (["housing type", "approval rate by housing", "rejected by housing"],
         "analyze_adoption_application_results_by_housing_type"),
        (["adoption success rate", "adoption by species"],
         "analyze_adoption_demand_and_success_rate_by_pet_species"),
        (["volunteer workload", "completed tasks", "volunteer performance"],
         "analyze_volunteer_workload_based_on_care_assignments"),
    ]

    for keywords, name_fragment in concept_map:
        if any(kw in prompt_lower for kw in keywords):
            for q in _query_registry:
                if name_fragment in q.name:
                    return q

    prompt_words = [w for w in prompt_lower.split() if len(w) > 3]
    best: StoredQuery | None = None
    best_score = 0
    for q in _query_registry:
        combined = (q.name + " " + q.description).lower()
        score = sum(1 for w in prompt_words if w in combined)
        if score > best_score:
            best_score = score
            best = q
    return best or _query_registry[0]

# ── Result Formatting ─────────────────────────────────────────────────────────

def _format_result(query: StoredQuery, rows: list[dict[str, Any]]) -> str:
    if not rows:
        return f"**{query.name}**\n{query.description}\nNo rows returned."
    headers = list(rows[0].keys())
    col_widths = {h: max(len(h), max(len(str(r.get(h, ""))) for r in rows)) for h in headers}
    header_line = " | ".join(h.ljust(col_widths[h]) for h in headers)
    sep_line = "-+-".join("-" * col_widths[h] for h in headers)
    result_lines = [header_line, sep_line]
    for row in rows:
        result_lines.append(" | ".join(str(row.get(h, "")).ljust(col_widths[h]) for h in headers))
    return f"**{query.name}**\n{query.description}\n```\n" + "\n".join(result_lines) + "\n```"

# ── Tool Handlers ──────────────────────────────────────────────────────────────

@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    if name == "list_available_queries":
        _build_registry()
        lines = ["Available queries:\n"]
        current_category = ""
        for q in _query_registry:
            if q.category != current_category:
                current_category = q.category
                lines.append(f"\n## {current_category.title()} Queries\n")
            param_str = ""
            if q.params:
                param_str = " | params: " + ", ".join(f"{p.name} ({p.type})" for p in q.params)
            lines.append(f"- **{q.name}**: {q.description}{param_str}\n")
        return [TextContent(type="text", text="".join(lines))]

    elif name == "execute_named_query":
        _build_registry()
        query_name = arguments.get("query_name", "")
        raw_params: dict = arguments.get("params", {})
        if query_name not in _query_map:
            available = ", ".join(sorted(_query_map.keys()))
            return [TextContent(type="text", text=f"Query '{query_name}' not found. Available: {available}")]
        query = _query_map[query_name]

        # Validate: reject unknown param keys
        known_names = {p.name for p in query.params}
        unknown = set(raw_params.keys()) - known_names
        if unknown:
            return [TextContent(type="text", text=f"Unknown parameter(s): {', '.join(unknown)}. Known: {', '.join(known_names)}")]

        # Build param_values dict — params not provided get None (SQL DEFAULT will apply)
        param_values: dict[str, Any] = {p.name: raw_params.get(p.name) for p in query.params}

        try:
            # Pre-process date params before normalization
            sql_for_normalize = _preprocess_date_params(query.sql, param_values)
            normalized_sql, param_names = normalize_sql(sql_for_normalize)
            if query.is_write:
                rows_affected = execute_write(normalized_sql, param_names, param_values)
                return [TextContent(type="text", text=f"**{query.name}**\n{query.description}\nRows affected: {rows_affected}")]
            else:
                rows = execute_query(normalized_sql, param_names, param_values)
                return [TextContent(type="text", text=_format_result(query, rows))]
        except Exception as exc:
            return [TextContent(type="text", text=f"Error: {exc}")]

    elif name == "natural_language_query":
        _build_registry()
        nl_prompt = arguments.get("nl_prompt", "")
        if not nl_prompt:
            return [TextContent(type="text", text="Please provide a natural language prompt.")]
        matched = _match_query(nl_prompt)
        try:
            extracted = _extract_params(nl_prompt, matched)
            sql_for_normalize = _preprocess_date_params(matched.sql, extracted)
            normalized_sql, param_names = normalize_sql(sql_for_normalize)

            if matched.is_write:
                missing = [p.name for p in matched.params if p.name not in extracted]
                if missing:
                    return [TextContent(type="text", text=f"**{matched.name}**\n{matched.description}\nMissing required parameters: {', '.join(missing)}\nPlease use execute_named_query with explicit params.")]
                rows_affected = execute_write(normalized_sql, param_names, extracted)
                return [TextContent(type="text", text=f"**{matched.name}**\n{matched.description}\nRows affected: {rows_affected}")]
            else:
                param_values: dict[str, Any] = {p.name: extracted.get(p.name) for p in matched.params}
                rows = execute_query(normalized_sql, param_names, param_values)
                return [TextContent(type="text", text=_format_result(matched, rows))]
        except Exception as exc:
            return [TextContent(type="text", text=f"Error: {exc}")]

    else:
        return [TextContent(type="text", text=f"Unknown tool: {name}")]

# ── Entry Point ────────────────────────────────────────────────────────────────

async def main():
    async with stdio_server() as streams:
        await server.run(streams[0], streams[1], server.create_initialization_options())

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
