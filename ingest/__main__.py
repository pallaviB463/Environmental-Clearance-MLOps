import argparse
import json
import sys

from ingest.pipeline import build_index, read_manifest


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m ingest", description="EIA corpus ingestion pipeline")
    sub = parser.add_subparsers(dest="command", required=True)

    build = sub.add_parser("build", help="parse, chunk, embed and index the corpus (idempotent)")
    build.add_argument("--force", action="store_true",
                       help="re-add every chunk to the index (embeddings still come from the cache)")

    sub.add_parser("status", help="print the index manifest")

    args = parser.parse_args()

    if args.command == "build":
        manifest = build_index(force=args.force)
        print(json.dumps({k: v for k, v in manifest.items() if k != "documents"}, indent=2))
        return 0

    manifest = read_manifest()
    if not manifest:
        print("No index found. Run: python -m ingest build")
        return 1
    print(json.dumps({k: v for k, v in manifest.items() if k != "documents"}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
