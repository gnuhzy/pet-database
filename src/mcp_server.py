"""
Pet Database MCP Server

Exposes pre-defined SQL queries from src/queries/ as callable MCP tools,
allowing an external LLM to query the pet adoption center database via natural language.
Only queries defined in src/queries/ can be executed; no arbitrary SQL is allowed.
"""

import re
import sqlite3
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from mcp.server import Server
from mcp.types import Tool, TextContent
from mcp import stdio_server

# Database

DB_PATH = Path(__file__).parent.parent / "pet_database.db"

# Query Registry

@dataclass
class StoredQuery:
    name: str
    description: str
    sql: str
    category: str  # 'operational' or 'analytical'

def load_queries() -> list[StoredQuery]:
    queries_dir = Path(__file__).parent.parent / "src" / "queries"
    queries: list[StoredQuery] = []

    for sql_file in sorted(queries_dir.glob("*.sql")):
        category = sql_file.stem.replace("_queries", "").replace("_", " ")
        raw = sql_file.read_text()
        parsed = parse_sql_file(raw, category)
        queries.extend(q for q in parsed if is_read_only_sql(q.sql))

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
        sql_lines = []
        for line in lines[1:]:
            stripped = line.strip()
            if stripped.startswith('-- Purpose:'):
                description_parts.append(stripped[len('-- Purpose:'):].strip())
            elif stripped.startswith('-- Example:'):
                pass
            elif stripped.startswith('--'):
                pass
            elif stripped:
                sql_lines.append(line)

        description = ' '.join(description_parts)
        sql = '\n'.join(sql_lines).strip()
        queries.append(StoredQuery(name=slugify(title), description=description, sql=sql, category=category))

    return queries

def slugify(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[_\s]+", "_", text)
    return text.strip("-_")

# Query Execution

def normalize_sql(sql: str) -> str:
    """Convert MySQL-specific SQL to SQLite-compatible SQL.

    Must apply DATE_ADD/DATEDIFF before CURDATE, since CURDATE replacement
    would break the patterns that contain CURDATE().
    """
    today = date.today().isoformat()

    def date_add_matcher(m):
        val, unit = m.group(1), m.group(2).lower()
        return f"date('{today}', '+{val} {unit}')"
    sql = re.sub(r"DATE_ADD\(CURDATE\(\),\s*INTERVAL\s+(\d+)\s+(DAY|MONTH|YEAR)\)", date_add_matcher, sql, flags=re.IGNORECASE)
    sql = re.sub(
        r"\bDATEDIFF\(CURDATE\(\),\s*(\w+)\)",
        rf"(cast(julianday('{today}') - julianday(\1) as integer))",
        sql,
        flags=re.IGNORECASE,
    )
    sql = re.sub(r"\bCURDATE\(\)", f"date('{today}')", sql, flags=re.IGNORECASE)
    return sql

def is_read_only_sql(sql: str) -> bool:
    return sql.lstrip().upper().startswith("SELECT")

def execute_query(sql: str) -> list[dict[str, Any]]:
    if not is_read_only_sql(sql):
        raise ValueError("Only predefined read-only SELECT queries can be executed through MCP.")
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute(normalize_sql(sql))
    rows = cur.fetchall()
    conn.close()
    return [dict(row) for row in rows]

# MCP Server

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
            description="List all available pre-defined SQL queries. Returns each query's name, description, and category.",
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
        Tool(
            name="execute_named_query",
            description="Execute a specific pre-defined query by its name. Use list_available_queries to see all available queries.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query_name": {
                        "type": "string",
                        "description": "The name of the query to execute.",
                    }
                },
                "required": ["query_name"],
            },
        ),
        Tool(
            name="natural_language_query",
            description="Given a natural language question, selects the best matching pre-defined query and executes it.",
            inputSchema={
                "type": "object",
                "properties": {
                    "nl_prompt": {
                        "type": "string",
                        "description": "A natural language question about the pet shelter database.",
                    }
                },
                "required": ["nl_prompt"],
            },
        ),
    ]
    return tools

def _match_query(nl_prompt: str) -> StoredQuery | None:
    """Keyword-based matching from natural language to a pre-defined query."""
    prompt_lower = nl_prompt.lower()

    # (keyword_list, name_fragment) — first match wins.
    # Specific/longer keywords must precede shorter generic ones.
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

    # Fallback: word-level match
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
            lines.append(f"- **{q.name}**: {q.description}\n")
        return [TextContent(type="text", text="".join(lines))]

    elif name == "execute_named_query":
        _build_registry()
        query_name = arguments.get("query_name", "")
        if query_name not in _query_map:
            available = ", ".join(sorted(_query_map.keys()))
            return [TextContent(type="text", text=f"Query '{query_name}' not found. Available: {available}")]
        query = _query_map[query_name]
        try:
            rows = execute_query(query.sql)
            return [TextContent(type="text", text=_format_result(query, rows))]
        except Exception as exc:
            return [TextContent(type="text", text=f"Error executing query: {exc}")]

    elif name == "natural_language_query":
        _build_registry()
        nl_prompt = arguments.get("nl_prompt", "")
        if not nl_prompt:
            return [TextContent(type="text", text="Please provide a natural language prompt.")]
        matched = _match_query(nl_prompt)
        try:
            rows = execute_query(matched.sql)
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
