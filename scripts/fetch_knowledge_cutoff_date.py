#!/usr/bin/env python3
"""
Parse LLM knowledge cutoff dates from GitHub repository and convert to JSON.

Source: https://github.com/HaoooWang/llm-knowledge-cutoff-dates/blob/main/README.md
"""

import json
import re
from typing import Dict, Optional
from datetime import datetime
import requests


def fetch_readme_content(url: str) -> str:
    """Fetch the raw README content from GitHub."""
    # Convert GitHub blob URL to raw URL
    raw_url = url.replace("github.com", "raw.githubusercontent.com").replace(
        "/blob/", "/"
    )

    response = requests.get(raw_url)
    response.raise_for_status()
    return response.text


def parse_cutoff_date(date_str: str) -> Optional[str]:
    """
    Parse various date formats to ISO format (YYYY-MM-DD).

    Handles formats like:
    - 2023.10
    - 2023.10.01
    - early 2023
    - 2022.09 (from pretraining)
    - Unknown
    """
    date_str = date_str.strip()

    # Handle unknown dates
    if date_str.lower() in ["unknown", "tbd", ""]:
        return None

    # Handle "early YYYY" format
    early_match = re.match(r"early\s+(\d{4})", date_str, re.IGNORECASE)
    if early_match:
        return f"{early_match.group(1)}-01-01"

    # Handle "Pretraining YYYY.MM, Finetuning YYYY.MM" format - use pretraining date
    pretraining_match = re.search(
        r"Pretraining\s+(\d{4}\.\d{2})", date_str, re.IGNORECASE
    )
    if pretraining_match:
        date_str = pretraining_match.group(1)

    # Handle end of YYYY format
    end_match = re.match(r"end\s+of\s+(\d{4})", date_str, re.IGNORECASE)
    if end_match:
        return f"{end_match.group(1)}-12-31"

    # Handle YYYY.MM.DD format
    full_date_match = re.match(r"(\d{4})\.(\d{2})\.(\d{2})", date_str)
    if full_date_match:
        year, month, day = full_date_match.groups()
        return f"{year}-{month}-{day}"

    # Handle YYYY.MM format
    year_month_match = re.match(r"(\d{4})\.(\d{2})", date_str)
    if year_month_match:
        year, month = year_month_match.groups()
        # Use last day of month as approximation
        return f"{year}-{month}-01"

    # Handle YYYY format
    year_match = re.match(r"(\d{4})", date_str)
    if year_match:
        return f"{year_match.group(1)}-01-01"

    return None


def normalize_model_name(name: str) -> str:
    """Normalize model name to lowercase without spaces, preserving dots for version numbers."""
    # Convert to lowercase and replace spaces/underscores with dashes
    normalized = name.lower().replace(" ", "-").replace("_", "-")
    # Remove special characters except alphanumeric, dots, and dashes
    normalized = re.sub(r"[^a-z0-9.-]", "", normalized)
    # Remove consecutive dashes
    normalized = re.sub(r"-+", "-", normalized)
    # Remove leading/trailing dashes and dots
    normalized = normalized.strip("-.")
    return normalized


def parse_markdown_table(table_text: str, company: str) -> Dict[str, Dict]:
    """Parse a markdown table and extract model information."""
    models = {}

    # Split into lines and skip header/separator
    lines = [line.strip() for line in table_text.split("\n") if line.strip()]

    # Find actual data rows (skip header and separator)
    data_rows = []
    for line in lines:
        # Skip header row, separator row, and empty rows
        if not line or line.startswith("|  |") or "---" in line:
            continue
        data_rows.append(line)

    for line in data_rows:
        # Split by pipe and clean up
        columns = [col.strip() for col in line.split("|")]
        # Remove empty first and last elements from split
        columns = [col for col in columns if col]

        if len(columns) >= 3:
            model_name = columns[0].strip()
            provider = columns[1].strip() if len(columns) > 1 else company
            cutoff_date_raw = columns[2].strip() if len(columns) > 2 else ""
            source_link = columns[3].strip() if len(columns) > 3 else ""

            # Skip header rows
            if model_name.lower() == "model name":
                continue

            # Parse the cutoff date
            cutoff_date = parse_cutoff_date(cutoff_date_raw)

            # Normalize the model name for the key
            normalized_key = normalize_model_name(model_name)

            # Skip if we couldn't create a valid key
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
    models = {}

    # Define the companies/sections we're looking for
    companies = {
        "OpenAI Models": "OpenAI",
        "Google Models": "Google",
        "Anthropic Models": "Anthropic",
        "Meta Models": "Meta",
        "Qwen Models": "Qwen",
        "DeepSeek Models": "DeepSeek",
        "Microsoft Models": "Microsoft",
        "Unknown Models": "Unknown",
    }

    # Split content by headers
    for section_header, company_name in companies.items():
        # Find the section
        pattern = rf"#\s+{re.escape(section_header)}.*?(?=(?:#\s+\w+\s+Models|$))"
        matches = re.findall(pattern, content, re.DOTALL | re.IGNORECASE)

        if matches:
            section_content = matches[0]
            # Extract table content
            table_pattern = r"\|[^\n]+\|[\s\S]*?(?=\n\n|\n#|$)"
            table_matches = re.findall(table_pattern, section_content)

            for table_text in table_matches:
                section_models = parse_markdown_table(table_text, company_name)
                models.update(section_models)

    result = {
        "models": models,
        "metadata": {
            "source_url": "https://github.com/HaoooWang/llm-knowledge-cutoff-dates",
            "parsed_at": datetime.utcnow().isoformat() + "Z",
            "total_models": len(models),
        },
    }

    return result


def main():
    """Main function to fetch, parse, and save LLM knowledge cutoff dates."""
    github_url = (
        "https://github.com/HaoooWang/llm-knowledge-cutoff-dates/blob/main/README.md"
    )
    output_file = "config/llm_cutoff_dates.json"

    print(f"Fetching README from {github_url}...")
    content = fetch_readme_content(github_url)

    print("Parsing content...")
    data = parse_readme(content)

    print(f"\nParsed {data['metadata']['total_models']} models:")

    # Group by company for display
    by_company = {}
    for key, model in data["models"].items():
        company = model["company"]
        if company not in by_company:
            by_company[company] = []
        by_company[company].append(model)

    for company, models in sorted(by_company.items()):
        print(f"  {company}: {len(models)} models")

    print(f"\nSaving to {output_file}...")
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print(
        f"✓ Successfully saved {data['metadata']['total_models']} models to {output_file}"
    )

    # Show some examples
    print("\nExample entries:")
    for i, (key, model) in enumerate(list(data["models"].items())[:5], 1):
        print(f"\n{i}. {key}: {model['model_name']} ({model['provider']})")
        print(f"   Cutoff: {model['cutoff_date']} (raw: {model['cutoff_date_raw']})")


if __name__ == "__main__":
    main()
