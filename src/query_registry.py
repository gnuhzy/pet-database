from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re


ROOT_DIR = Path(__file__).resolve().parent.parent
QUERIES_DIR = ROOT_DIR / "src" / "queries"


@dataclass(frozen=True)
class StoredQuery:
    name: str
    title: str
    description: str
    sql: str
    category: str


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
        description_parts: list[str] = []
        sql_lines: list[str] = []
        for line in chunk.splitlines()[1:]:
            stripped = line.strip()
            if stripped.startswith("-- Purpose:"):
                description_parts.append(stripped[len("-- Purpose:") :].strip())
            elif stripped.startswith("--"):
                continue
            elif stripped:
                sql_lines.append(line.rstrip())
        sql = "\n".join(sql_lines).strip()
        queries.append(
            StoredQuery(
                name=slugify(title),
                title=title,
                description=" ".join(description_parts),
                sql=sql,
                category=category,
            )
        )
    return queries


def is_read_only_query(query: StoredQuery | str) -> bool:
    sql = query.sql if isinstance(query, StoredQuery) else query
    return re.match(r"^\s*(SELECT|WITH)\b", sql, flags=re.IGNORECASE) is not None


def load_query_registry(base_dir: Path | None = None) -> list[StoredQuery]:
    query_dir = base_dir or QUERIES_DIR
    queries: list[StoredQuery] = []
    for sql_file in sorted(query_dir.glob("*_queries.sql")):
        category = sql_file.stem.replace("_queries", "").replace("_", " ")
        queries.extend(parse_query_file(sql_file.read_text(encoding="utf-8"), category))
    return [query for query in queries if is_read_only_query(query)]
