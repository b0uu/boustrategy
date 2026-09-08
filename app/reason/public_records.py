"""Ingest approved public sources or thesis reviews from trusted local JSON."""

import argparse
import json
from pathlib import Path

from app.schemas.public_authoring import PublicSourceRecord, ThesisReview
from app.storage.database import connect
from app.storage.public_records import save_public_source, save_thesis_review


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--kind", choices=("source", "thesis-review"), required=True)
    args = parser.parse_args()
    raw = json.loads(args.input.read_text(encoding="utf-8"))
    conn = connect(args.db)
    try:
        with conn:
            if args.kind == "source":
                print(save_public_source(conn, PublicSourceRecord.model_validate(raw)))
            else:
                save_thesis_review(conn, ThesisReview.model_validate(raw))
                print("Thesis review recorded.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
