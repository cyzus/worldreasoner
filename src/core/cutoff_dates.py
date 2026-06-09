"""Fetch and parse LLM knowledge cutoff dates into local JSON.

Importable home for the logic that used to live in
``scripts/fetch_knowledge_cutoff_date.py``. The ``wr db fetch-cutoffs`` CLI
command wraps ``fetch_and_save``.
"""

from datetime import datetime, timezone
import json
import re
from typing import Callable, Dict, List, Optional, Tuple

import requests


SOURCE_README_URL = (
    "https://github.com/HaoooWang/llm-knowledge-cutoff-dates/blob/main/README.md"
)
DEFAULT_OUTPUT_FILE = "config/llm_cutoff_dates.json"


def fetch_readme_content(url: str) -> str:
    """Fetch the raw README content from GitHub."""
    raw_url = url.replace("github.com", "raw.githubusercontent.com").replace(
        "/blob/", "/"
    )
    response = requests.get(raw_url, timeout=30)
    response.raise_for_status()
    return response.text


def parse_cutoff_date(date_str: str) -> Optional[str]:
    """Parse various date formats to ISO format (YYYY-MM-DD)."""
    date_str = date_str.strip()
    date_str = re.sub(r"`", "", date_str)
    date_str = re.sub(r"\[[^\]]+\]\([^\)]+\)", "", date_str).strip()

    if date_str.lower() in ["unknown", "tbd", "n/a", "na", ""]:
        return None

    early_match = re.match(r"early\s+(\d{4})", date_str, re.IGNORECASE)
    if early_match:
        return f"{early_match.group(1)}-01-01"

    late_match = re.match(r"late\s+(\d{4})", date_str, re.IGNORECASE)
    if late_match:
        return f"{late_match.group(1)}-10-01"

    quarter_match = re.search(
        r"(?:Q([1-4])\s*(\d{4})|(\d{4})\s*Q([1-4]))", date_str, re.IGNORECASE
    )
    if quarter_match:
        quarter = int(quarter_match.group(1) or quarter_match.group(4))
        year = int(quarter_match.group(2) or quarter_match.group(3))
        month = (quarter - 1) * 3 + 1
        return f"{year:04d}-{month:02d}-01"

    pretraining_match = re.search(
        r"Pretraining[:\s]+(\d{4}\.\d{2}(?:\.\d{2})?)", date_str, re.IGNORECASE
    )
    if pretraining_match:
        date_str = pretraining_match.group(1)

    end_match = re.match(r"end\s+of\s+(\d{4})", date_str, re.IGNORECASE)
    if end_match:
        return f"{end_match.group(1)}-12-31"

    full_date_match = re.match(r"(\d{4})\.(\d{2})\.(\d{2})", date_str)
    if full_date_match:
        year, month, day = full_date_match.groups()
        return f"{year}-{month}-{day}"

    iso_or_slash_date_match = re.match(r"(\d{4})[-/](\d{2})[-/](\d{2})", date_str)
    if iso_or_slash_date_match:
        year, month, day = iso_or_slash_date_match.groups()
        return f"{year}-{month}-{day}"

    year_month_match = re.match(r"(\d{4})\.(\d{2})", date_str)
    if year_month_match:
        year, month = year_month_match.groups()
        return f"{year}-{month}-01"

    year_match = re.match(r"(\d{4})", date_str)
    if year_match:
        return f"{year_match.group(1)}-01-01"

    return None


def extract_markdown_tables(section_text: str) -> List[str]:
    """Extract contiguous markdown table blocks from a section."""
    tables: List[str] = []
    table_lines: List[str] = []

    for line in section_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("|") and stripped.endswith("|"):
            table_lines.append(stripped)
        else:
            if table_lines:
                tables.append("\n".join(table_lines))
                table_lines = []

    if table_lines:
        tables.append("\n".join(table_lines))

    return tables


def iter_markdown_sections(content: str) -> List[Tuple[str, str]]:
    """Return [(section_name, section_text)] for markdown heading sections."""
    header_regex = re.compile(r"(?m)^#{1,6}\s+(?P<section>.+?)\s*$")
    matches = list(header_regex.finditer(content))
    sections: List[Tuple[str, str]] = []

    for i, match in enumerate(matches):
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
        section_name = match.group("section").strip()
        section_text = content[start:end]
        sections.append((section_name, section_text))

    return sections


def normalize_model_name(name: str) -> str:
    """Normalize model name to lowercase, preserving dots for version numbers."""
    normalized = name.lower().replace(" ", "-").replace("_", "-")
    normalized = re.sub(r"[^a-z0-9.-]", "", normalized)
    normalized = re.sub(r"-+", "-", normalized)
    normalized = normalized.strip("-.")
    return normalized


def _split_markdown_row(line: str) -> List[str]:
    """Split a markdown table row into cells while preserving empty cells."""
    stripped = line.strip()
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]
    return [cell.strip() for cell in stripped.split("|")]


def _is_separator_row(cells: List[str]) -> bool:
    """Return True if cells represent markdown separator syntax like |---|:---:|."""
    if not cells:
        return False
    return all(re.match(r"^:?-{3,}:?$", cell) or cell == "" for cell in cells)


def _normalized_header(cell: str) -> str:
    """Normalize a header cell for loose matching."""
    value = cell.lower()
    value = value.replace("-", " ")
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def parse_markdown_table(table_text: str, company: str) -> Dict[str, Dict]:
    """Parse a markdown table and extract model information."""
    models: Dict[str, Dict] = {}

    lines = [line.strip() for line in table_text.split("\n") if line.strip()]
    if len(lines) < 2:
        return models

    header_cells = _split_markdown_row(lines[0])
    header_names = [_normalized_header(cell) for cell in header_cells]

    model_idx = next(
        (i for i, header in enumerate(header_names) if "model" in header), 0
    )
    provider_idx = next(
        (
            i
            for i, header in enumerate(header_names)
            if "company" in header or "provider" in header
        ),
        1,
    )
    source_idx = next(
        (i for i, header in enumerate(header_names) if "source" in header),
        -1,
    )

    reliable_cutoff_idx = next(
        (
            i
            for i, header in enumerate(header_names)
            if "reliable" in header and "cut" in header
        ),
        -1,
    )
    training_cutoff_idx = next(
        (
            i
            for i, header in enumerate(header_names)
            if "training" in header and "cut" in header
        ),
        -1,
    )
    generic_cutoff_idx = next(
        (i for i, header in enumerate(header_names) if "cut" in header),
        -1,
    )

    if reliable_cutoff_idx >= 0:
        cutoff_idx = reliable_cutoff_idx
    elif training_cutoff_idx >= 0:
        cutoff_idx = training_cutoff_idx
    elif generic_cutoff_idx >= 0:
        cutoff_idx = generic_cutoff_idx
    else:
        cutoff_idx = 2

    data_start_index = 1
    if len(lines) > 1 and _is_separator_row(_split_markdown_row(lines[1])):
        data_start_index = 2

    for line in lines[data_start_index:]:
        columns = _split_markdown_row(line)
        if not any(columns):
            continue

        model_name = columns[model_idx].strip() if model_idx < len(columns) else ""
        if not model_name or model_name.lower() in {"model", "model name"}:
            continue

        provider = columns[provider_idx].strip() if provider_idx < len(columns) else ""
        provider = provider or company

        cutoff_date_raw = (
            columns[cutoff_idx].strip() if cutoff_idx < len(columns) else ""
        )
        source_link = columns[source_idx].strip() if source_idx < len(columns) else ""

        cutoff_date = parse_cutoff_date(cutoff_date_raw)

        normalized_key = normalize_model_name(model_name)
        if not normalized_key:
            continue

        models[normalized_key] = {
            "model_name": model_name,
            "provider": provider,
            "cutoff_date": cutoff_date,
            "cutoff_date_raw": cutoff_date_raw,
            "source": source_link,
            "company": company,
        }

    return models


def parse_readme(content: str) -> Dict:
    """Parse the entire README and extract all model information."""
    models: Dict[str, Dict] = {}

    for section_name, section_text in iter_markdown_sections(content):
        for table_text in extract_markdown_tables(section_text):
            company_name = re.sub(
                r"\s+Models$", "", section_name, flags=re.IGNORECASE
            )
            section_models = parse_markdown_table(table_text, company_name)
            models.update(section_models)

    return {
        "models": models,
        "metadata": {
            "source_url": "https://github.com/HaoooWang/llm-knowledge-cutoff-dates",
            "parsed_at": datetime.now(timezone.utc)
            .isoformat()
            .replace("+00:00", "Z"),
            "total_models": len(models),
        },
    }


def fetch_and_save(
    output_file: str = DEFAULT_OUTPUT_FILE,
    source_url: str = SOURCE_README_URL,
    log: Optional[Callable[[str], None]] = None,
) -> Dict:
    """Fetch, parse, and save LLM knowledge cutoff dates to ``output_file``.

    Returns the parsed data dict.
    """
    emit = log or print

    emit(f"Fetching README from {source_url}...")
    content = fetch_readme_content(source_url)

    emit("Parsing content...")
    data = parse_readme(content)

    emit(f"\nParsed {data['metadata']['total_models']} models:")
    by_company: Dict[str, List[Dict]] = {}
    for model in data["models"].values():
        by_company.setdefault(model["company"], []).append(model)
    for company, models in sorted(by_company.items()):
        emit(f"  {company}: {len(models)} models")

    emit(f"\nSaving to {output_file}...")
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    emit(
        f"Success: saved {data['metadata']['total_models']} models to {output_file}"
    )
    return data
