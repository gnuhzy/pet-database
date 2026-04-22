from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import llm_sql_assistant
import web_server


def connect_for_eval(reset_db: bool) -> sqlite3.Connection:
    web_server.initialize_database(reset=reset_db)
    conn = web_server.connect()
    return conn


def main() -> None:
    parser = argparse.ArgumentParser(description="Run GLM prompt-to-SQL evaluation cases.")
    parser.add_argument(
        "--methods",
        nargs="+",
        default=["schema_grounded"],
        choices=llm_sql_assistant.PROMPT_METHODS,
        help="Prompt methods to evaluate.",
    )
    parser.add_argument(
        "--output",
        default=str(llm_sql_assistant.RESULTS_PATH),
        help="JSON output path.",
    )
    parser.add_argument(
        "--reset-db",
        action="store_true",
        help="Rebuild the SQLite database before running evaluation.",
    )
    args = parser.parse_args()

    with closing(connect_for_eval(args.reset_db)) as conn:
        results = llm_sql_assistant.evaluate_cases(conn, web_server.DB_PATH, args.methods)

    output_path = Path(args.output)
    output_path.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    summary = results["summary"]
    print(
        "Evaluation complete: "
        f"{summary['executable']}/{summary['total']} executable, "
        f"{summary['safe']}/{summary['total']} safe. "
        f"Wrote {output_path}."
    )


if __name__ == "__main__":
    main()
