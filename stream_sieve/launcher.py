from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in {"-h", "--help"}:
        print_help()
        return 0 if args else 2

    command = args.pop(0)
    if command not in {
        "all", "sieve", "sieve-extraction", "sieve-score", "sieve-analysis",
        "send", "send-email",
    }:
        print(f"unknown project command: {command}", file=sys.stderr)
        print_help(file=sys.stderr)
        return 2

    config = os.environ.get("STREAM_SIEVE_CONFIG", "config.yaml")
    if args and not args[0].startswith("-"):
        config = args.pop(0)

    runner = PROJECT_ROOT / "scripts" / "run_pipeline.py"
    if not runner.is_file():
        print(f"pipeline runner not found: {runner}", file=sys.stderr)
        return 1

    command_args = [sys.executable, str(runner), config, "--stage", command, *args]
    return subprocess.call(command_args, cwd=PROJECT_ROOT)


def print_help(*, file=None) -> None:
    output = file or sys.stdout
    print(
        "Usage: stream-sieve <command> [config] [options]\n\n"
        "Commands:\n"
        "  sieve-extraction  collect configured sources\n"
        "  sieve-score       score saved extractions\n"
        "  sieve-analysis    analyze saved high-scored articles\n"
        "  send-email        select saved content and send email\n"
        "  sieve             extraction + score + analysis\n"
        "  send              complete send flow\n"
        "  all               sieve + send\n\n"
        "Examples:\n"
        "  stream-sieve sieve-extraction\n"
        "  stream-sieve sieve-score\n"
        "  stream-sieve sieve-analysis\n"
        "  stream-sieve send-email --dry-run\n"
        "  stream-sieve all configs/runs/full-email-test.example.yaml --dry-run",
        file=output,
    )


if __name__ == "__main__":
    raise SystemExit(main())
