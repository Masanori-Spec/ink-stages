"""Linux CLI entry point; dry-run performs no native execution."""

import argparse
import sys

from . import __version__
from .core import dry_run, inspect, json_bytes, render
from .safety import InkStagesError


def main(argv=None):
    parser = argparse.ArgumentParser(description="Export ordered exact-name Xournal++ layer selections without rewriting XOPP")
    parser.add_argument("source", help="gzip/fileversion=4 XOPP source")
    parser.add_argument("recipe", nargs="?", help="inkstages.recipe.v1 JSON (optional for dry-run inventory)")
    parser.add_argument("--dry-run", action="store_true", help="validate and show JSON; do not run native tools")
    parser.add_argument("--output", help="fresh destination PDF; never overwritten")
    parser.add_argument("--report", help="fresh destination JSON report; never overwritten")
    parser.add_argument("--xournalpp", default="xournalpp", help="absolute native executable path (default: xournalpp on PATH)")
    parser.add_argument("--qpdf", default="qpdf", help="absolute qpdf executable path (default: qpdf on PATH)")
    parser.add_argument("--timeout", type=float, default=60.0, help="seconds per native command, 1..300 (default: 60)")
    parser.add_argument("--version", action="version", version=f"InkStages {__version__}")
    args = parser.parse_args(argv)
    if not sys.platform.startswith("linux"):
        parser.error("InkStages currently supports Linux only")
    if args.dry_run and args.output:
        parser.error("--output is not used by --dry-run")
    if not args.dry_run and not (args.recipe and args.output and args.report):
        parser.error("Rendering requires recipe, --output and --report")
    try:
        plan = inspect(args.source, args.recipe)
        result = dry_run(plan, args.report, xournalpp=args.xournalpp, qpdf=args.qpdf) if args.dry_run else render(
            plan, args.output, args.report, xournalpp=args.xournalpp, qpdf=args.qpdf, timeout=args.timeout)
        sys.stdout.write(json_bytes(result).decode("utf-8"))
        return 0
    except (InkStagesError, OSError) as exc:
        print(f"inkstages: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
