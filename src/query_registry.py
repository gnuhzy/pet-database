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
    return sql.lstrip().upper().startswith("SELECT")


def load_query_registry(base_dir: Path | None = None) -> list[StoredQuery]:
    query_dir = base_dir or QUERIES_DIR
    queries: list[StoredQuery] = []
    for sql_file in sorted(query_dir.glob("*_queries.sql")):
        category = sql_file.stem.replace("_queries", "").replace("_", " ")
        queries.extend(parse_query_file(sql_file.read_text(encoding="utf-8"), category))
    return [query for query in queries if is_read_only_query(query)]


def _depluralize(word: str) -> str:
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
    lowered = text.lower().replace("-", " ").replace("_", " ")
    tokens = re.split(r"\W+", lowered)
    return " ".join(_depluralize(tok) for tok in tokens if tok)


def match_query_from_prompt(prompt: str, queries: list[StoredQuery]) -> StoredQuery:
    prompt_lower = prompt.lower()
    prompt_normalized = _normalize_prompt(prompt)
    concept_map = [
        (
            [
                "vaccination due",
                "vaccine due",
                "upcoming vaccination",
                "vaccination soon",
                "vaccination reminder",
                "vaccine reminder",
                "due vaccination",
            ],
            "view_pets_whose_vaccination_due_date_is_approaching",
        ),
        (
            [
                "adoptable",
                "available for adoption",
                "pets available",
                "available pet",
                "pet available",
                "ready for adoption",
                "open for adoption",
            ],
            "view_all_pets_that_are_currently_available_for_adoption",
        ),
        (
            ["occupancy", "occupied", "most occupied", "fullest", "shelter occupancy", "shelter capacity", "how full"],
            "analyze_current_occupancy_of_each_shelter",
        ),
        (
            ["shelter", "shelter 1", "shelter 2", "pet in shelter", "housed in"],
            "view_all_pets_currently_housed_in_a_specific_shelter",
        ),
        (
            ["health info", "medical history", "full health", "vaccination and medical", "health record", "health profile"],
            "view_the_full_health_information_of_a_specific_pet",
        ),
        (
            ["volunteer assignment", "care assignment", "volunteer schedule", "volunteer shift", "upcoming shift"],
            "view_upcoming_care_assignments_for_a_volunteer",
        ),
        (
            ["adoption application", "pending application", "under review", "applications to review", "awaiting review"],
            "view_all_adoption_applications_that_are_currently_under_review",
        ),
        (
            ["follow up outcome", "followup outcome", "post adoption", "adopter feedback", "follow-up outcome"],
            "analyze_post-adoption_follow-up_outcomes",
        ),
        (
            ["long stay", "longest", "stay long", "long-stay", "stayed longest"],
            "analyze_pets_that_have_stayed_the_longest_in_the_shelter",
        ),
        (
            ["housing type", "approval rate by housing", "rejected by housing", "housing approval"],
            "analyze_adoption_application_results_by_housing_type",
        ),
        (
            ["adoption success rate", "adoption by species", "species demand", "most adopted species", "popular species"],
            "analyze_adoption_demand_and_success_rate_by_pet_species",
        ),
        (
            ["volunteer workload", "completed task", "volunteer performance", "tasks per volunteer", "workload"],
            "analyze_volunteer_workload_based_on_care_assignments",
        ),
    ]

    for keywords, exact_name in concept_map:
        for keyword in keywords:
            normalized_keyword = _normalize_prompt(keyword)
            if keyword in prompt_lower or normalized_keyword in prompt_normalized:
                for query in queries:
                    if query.name == exact_name:
                        return query
                break

    stop_words = {
        "the",
        "that",
        "this",
        "with",
        "from",
        "have",
        "which",
        "what",
        "find",
        "show",
        "list",
        "give",
        "some",
        "need",
        "want",
        "would",
        "could",
        "should",
        "about",
        "into",
        "onto",
        "pets",
        "pet",
    }
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
