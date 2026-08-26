"""CLI entry point for the isolated hosted annotation application."""

import argparse
from pathlib import Path

import uvicorn

from src.api.annotation_app import create_annotation_app


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packet-dir", type=Path, required=True)
    parser.add_argument(
        "--db",
        type=Path,
        default=Path("data/annotation/hosted_annotations.db"),
    )
    parser.add_argument("--completion-url")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8011)
    args = parser.parse_args()

    app = create_annotation_app(
        packet_dir=args.packet_dir,
        db_path=args.db,
        completion_url=args.completion_url,
    )
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
