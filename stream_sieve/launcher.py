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
    if command == "sieve-cycle":
        if not args or args[0].startswith("-"):
            print("sieve-cycle requires a non-negative cycle count", file=sys.stderr)
            return 2
        try:
            cycles = int(args.pop(0))
        except ValueError:
            print("sieve-cycle count must be an integer >= 0", file=sys.stderr)
            return 2
        if cycles < 0:
            print("sieve-cycle count must be >= 0", file=sys.stderr)
            return 2
        return run_sieve_cycles(cycles, args)

    if command not in {"all", "sieve", "sync", "send-email"}:
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
        "  sieve       collect, score, and analyze configured sources\n"
        "  sync        score all unscored saved extractions\n"
        "  sieve-cycle run sieve repeatedly; 0 means forever\n"
        "  send-email  select saved content and send email\n"
        "  all         run the complete pipeline\n\n"
        "Examples:\n"
        "  stream-sieve sieve\n"
        "  stream-sieve sieve --type ai_news politics\n"
        "  stream-sieve send-email --type ai_news cognition\n"
        "  stream-sieve send-email --dry-run\n"
        "  stream-sieve all configs/runs/full-email-test.example.yaml --dry-run",
        file=output,
    )


def run_sieve_cycles(cycles: int, args: list[str]) -> int:
    config = os.environ.get("STREAM_SIEVE_CONFIG", "config.yaml")
    if args and not args[0].startswith("-"):
        config = args.pop(0)

    runner = PROJECT_ROOT / "scripts" / "run_pipeline.py"
    if not runner.is_file():
        print(f"pipeline runner not found: {runner}", file=sys.stderr)
        return 1

    command = [sys.executable, str(runner), config, "--stage", "sieve", *args]
    cycle = 0
    failures = 0
    try:
        while cycles == 0 or cycle < cycles:
            cycle += 1
            print(f"== sieve-cycle {cycle}{' (infinite)' if cycles == 0 else f'/{cycles}'} ==", flush=True)
            result = subprocess.call(command, cwd=PROJECT_ROOT)
            if result != 0:
                failures += 1
                print(f"[ERROR] sieve cycle {cycle} failed with exit code {result}; continuing", file=sys.stderr, flush=True)
    except KeyboardInterrupt:
        print("\n[WARN] sieve-cycle stopped by user", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
