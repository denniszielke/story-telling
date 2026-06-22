"""CLI extraction agent for exporting Azure AI Search results.

This command-line tool searches the same vector index used by the researcher
agent and supports three intent types:
- method
- use case
- repo

It shows the top 3 matching results and exports selected items to individual
Markdown files with full document content.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from dotenv import load_dotenv

from searching import search_architecture_documents

load_dotenv(override=True)


def _normalize_search_type(raw_value: str) -> tuple[str | None, str | None, str | None, str]:
    """Map CLI search type to objective/classification filters.

    Returns:
        (objective, classification, filter_expr, display_name)
    """
    value = raw_value.strip().lower().replace("_", "-")

    if value == "method":
        return "method", None, None, "method"
    if value in {"use-case", "usecase"}:
        return "use case", None, None, "use case"
    if value in {"repo", "repository"}:
        # Repo content can be indexed with different labels; keep this inclusive.
        return (
            None,
            None,
            "classification eq 'repo' or classification eq 'repository' or "
            "objective eq 'repo' or objective eq 'repository'",
            "repo",
        )

    raise ValueError("search type must be one of: method, use-case, repo")


def _short_text(value: str | None, limit: int = 160) -> str:
    text = (value or "").strip().replace("\n", " ")
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
    return slug or "item"


def _parse_selection(raw: str, max_index: int) -> list[int]:
    value = raw.strip().lower()
    if value == "all":
        return list(range(1, max_index + 1))

    picked: set[int] = set()
    for token in value.split(","):
        token = token.strip()
        if not token:
            continue
        if not token.isdigit():
            raise ValueError("selection must be comma-separated numbers (for example: 1,3) or 'all'")
        idx = int(token)
        if idx < 1 or idx > max_index:
            raise ValueError(f"selection index out of range: {idx}")
        picked.add(idx)

    if not picked:
        raise ValueError("no items selected")

    return sorted(picked)


def _render_result_card(index: int, doc: dict) -> str:
    title = doc.get("description") or doc.get("id") or f"result-{index}"
    summary_source = doc.get("context") or doc.get("scenario") or doc.get("content")
    return (
        f"[{index}] {title}\n"
        f"    objective: {doc.get('objective', 'n/a')} | "
        f"classification: {doc.get('classification', 'n/a')} | "
        f"rating: {doc.get('rating', 'n/a')}\n"
        f"    source: {doc.get('source', 'n/a')}\n"
        f"    summary: {_short_text(summary_source)}"
    )


def _write_markdown(doc: dict, output_dir: Path, sequence: int) -> Path:
    title = doc.get("description") or doc.get("id") or f"item-{sequence}"
    filename = f"{sequence:02d}-{_slugify(title)}.md"
    path = output_dir / filename

    tags = doc.get("tags") or []
    if not isinstance(tags, list):
        tags = [str(tags)]

    content = (
        f"# {title}\n\n"
        f"- ID: {doc.get('id', 'n/a')}\n"
        f"- Objective: {doc.get('objective', 'n/a')}\n"
        f"- Classification: {doc.get('classification', 'n/a')}\n"
        f"- Source: {doc.get('source', 'n/a')}\n"
        f"- Reference: {doc.get('reference', 'n/a')}\n"
        f"- Rating: {doc.get('rating', 'n/a')}\n"
        f"- Tags: {', '.join(tags) if tags else 'n/a'}\n\n"
        "## Description\n\n"
        f"{doc.get('description', '')}\n\n"
        "## Scenario\n\n"
        f"{doc.get('scenario', '')}\n\n"
        "## Context\n\n"
        f"{doc.get('context', '')}\n\n"
        "## Full Content\n\n"
        f"{doc.get('content', '')}\n"
    )

    path.write_text(content, encoding="utf-8")
    return path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Search architecture vector content and export selected items to Markdown."
    )
    parser.add_argument(
        "--query",
        required=False,
        help="Natural language query for vector search.",
    )
    parser.add_argument(
        "--type",
        required=True,
        choices=["method", "use-case", "repo"],
        help="Search intent type.",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=3,
        help="Number of results to retrieve (default: 3).",
    )
    parser.add_argument(
        "--select",
        required=False,
        help="Selection list like '1,3' or 'all'. If omitted, interactive prompt is shown.",
    )
    parser.add_argument(
        "--output-dir",
        default="extractions",
        help="Directory where markdown files are written (default: ./extractions).",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    query = (args.query or "").strip()
    if not query:
        query = input("Enter your query: ").strip()
    if not query:
        print("Query is required.", file=sys.stderr)
        return 2

    try:
        objective, classification, filter_expr, display_type = _normalize_search_type(args.type)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    top = max(1, min(args.top, 3))

    docs = search_architecture_documents(
        query=query,
        classification=classification,
        objective=objective,
        filter_expr=filter_expr,
        top=top,
    )

    if not docs:
        print(f"No results found for '{query}' ({display_type}).")
        return 0

    print(f"Top {len(docs)} results for '{query}' ({display_type}):\n")
    for i, doc in enumerate(docs, start=1):
        print(_render_result_card(i, doc))
        print()

    raw_selection = args.select
    if raw_selection is None:
        raw_selection = input("Select items to export (e.g. 1,3 or all): ").strip()

    try:
        selected = _parse_selection(raw_selection, len(docs))
    except ValueError as exc:
        print(f"Invalid selection: {exc}", file=sys.stderr)
        return 2

    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    exported_paths: list[Path] = []
    for export_order, doc_index in enumerate(selected, start=1):
        path = _write_markdown(docs[doc_index - 1], output_dir, export_order)
        exported_paths.append(path)

    print("Exported files:")
    for path in exported_paths:
        print(f"- {path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
