import argparse

from app.newsletters.store import annotate, ingest, list_docs
from app.storage.database import connect


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.newsletters.run")
    parser.add_argument("command", choices=("ingest", "annotate", "list"))
    parser.add_argument("--db", default="data/boustrategy.db")
    parser.add_argument("--root", default="data/newsletters")
    parser.add_argument("--doc")
    parser.add_argument("--in", dest="in_path")
    parser.add_argument("--source")
    args = parser.parse_args()
    conn = connect(args.db)
    if args.command == "ingest":
        inserted, duplicates = ingest(conn, args.root)
        print(f"ingested={inserted} duplicates={duplicates}")
    elif args.command == "annotate":
        if not args.doc or not args.in_path:
            raise ValueError("annotate requires --doc and --in")
        print(f"claims={annotate(conn, args.doc, args.in_path)}")
    else:
        for doc_id, source, title, status, claims in list_docs(conn, args.source):
            print(f"{doc_id} {source} {title} {status} claims={claims}")


if __name__ == "__main__":
    main()
