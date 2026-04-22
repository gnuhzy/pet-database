"""
Pet Database MCP Server

Exposes reviewed read-only SQL queries from src/queries/*_queries.sql as MCP
tools. Arbitrary SQL and mutation statements are intentionally out of scope.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

from mcp import stdio_server
from mcp.server import Server
from mcp.types import TextContent, Tool

from query_registry import StoredQuery, load_query_registry, match_query_from_prompt


DB_PATH = Path(__file__).resolve().parent.parent / "pet_database.db"
APP_NAME = "pet-database-mcp"
APP_VERSION = "2.0.0"


server = Server(APP_NAME, version=APP_VERSION)
_query_registry: list[StoredQuery] = []
_query_map: dict[str, StoredQuery] = {}


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _build_registry() -> None:
    global _query_registry, _query_map
    _query_registry = load_query_registry()
    _query_map = {query.name: query for query in _query_registry}


def _require_database() -> None:
    if not DB_PATH.exists():
        raise RuntimeError(
            "pet_database.db was not found. Start src/web_server.py once to initialize the SQLite database."
        )


def execute_query(sql: str) -> list[dict[str, Any]]:
    _require_database()
    with closing(_connect()) as conn:
        return [dict(row) for row in conn.execute(sql).fetchall()]


def _format_catalog() -> str:
    lines = ["Available reviewed read-only queries:\n"]
    current_category = ""
    for query in _query_registry:
        if query.category != current_category:
            current_category = query.category
            lines.append(f"\n## {current_category.title()} Queries\n")
        lines.append(f"- **{query.name}** (`read-only`): {query.description}\n")
    return "".join(lines)


def _format_result(query: StoredQuery, rows: list[dict[str, Any]]) -> str:
    metadata = [
        f"query: {query.name}",
        f"title: {query.title}",
        f"category: {query.category}",
        "read_only: true",
    ]
    if not rows:
        return "\n".join(metadata + ["rows: 0", "", "No rows returned."])
    headers = list(rows[0].keys())
    col_widths = {
        header: max(len(header), max(len(str(row.get(header, ""))) for row in rows))
        for header in headers
    }
    header_line = " | ".join(header.ljust(col_widths[header]) for header in headers)
    separator_line = "-+-".join("-" * col_widths[header] for header in headers)
    body_lines = [
        " | ".join(str(row.get(header, "")).ljust(col_widths[header]) for header in headers)
        for row in rows
    ]
    table = "\n".join([header_line, separator_line, *body_lines])
    return "\n".join(metadata + [f"rows: {len(rows)}", "", f"```\n{table}\n```"])


@server.list_tools()
async def list_tools() -> list[Tool]:
    _build_registry()
    return [
        Tool(
            name="list_available_queries",
            description="List every reviewed read-only SQL query available through the pet database MCP server.",
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
        Tool(
            name="execute_named_query",
            description="Execute a reviewed read-only SQL query by name.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query_name": {
                        "type": "string",
                        "description": "The exact query name returned by list_available_queries.",
                    }
                },
                "required": ["query_name"],
            },
        ),
        Tool(
            name="natural_language_query",
            description="Map a natural-language request to the best reviewed read-only SQL query and execute it.",
            inputSchema={
                "type": "object",
                "properties": {
                    "nl_prompt": {
                        "type": "string",
                        "description": "A natural language question about the pet adoption center database.",
                    }
                },
                "required": ["nl_prompt"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    _build_registry()

    if name == "list_available_queries":
        return [TextContent(type="text", text=_format_catalog())]

    if name == "execute_named_query":
        query_name = arguments.get("query_name", "")
        if query_name not in _query_map:
            available = ", ".join(sorted(_query_map))
            return [TextContent(type="text", text=f"Query '{query_name}' not found. Available: {available}")]
        query = _query_map[query_name]
        try:
            rows = execute_query(query.sql)
            return [TextContent(type="text", text=_format_result(query, rows))]
        except Exception as exc:
            return [TextContent(type="text", text=f"Error executing read-only query '{query_name}': {exc}")]

    if name == "natural_language_query":
        prompt = arguments.get("nl_prompt", "").strip()
        if not prompt:
            return [TextContent(type="text", text="Please provide a natural language prompt.")]
        query = match_query_from_prompt(prompt, _query_registry)
        try:
            rows = execute_query(query.sql)
            text = "\n".join(
                [
                    f"prompt: {prompt}",
                    "routing_model: reviewed predefined SELECT query only",
                    "",
                    _format_result(query, rows),
                ]
            )
            return [TextContent(type="text", text=text)]
        except Exception as exc:
            return [TextContent(type="text", text=f"Error executing routed read-only query '{query.name}': {exc}")]

    return [TextContent(type="text", text=f"Unknown tool: {name}")]


async def main() -> None:
    async with stdio_server() as streams:
        await server.run(streams[0], streams[1], server.create_initialization_options())


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
