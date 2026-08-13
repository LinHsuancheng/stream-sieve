#!/usr/bin/env python3
"""Phase 0 environment checks for the personal feed browser bridge."""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys


REQUIRED_PYTHON_MODULES = ("feedparser", "httpx", "trafilatura", "yaml")


def run(cmd: list[str], timeout: int = 8) -> tuple[int | None, str]:
    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=timeout,
        )
        return proc.returncode, proc.stdout.strip()
    except FileNotFoundError as exc:
        return None, str(exc)
    except subprocess.TimeoutExpired:
        return None, "timed out"


def status(ok: bool) -> str:
    return "OK" if ok else "FAIL"


def check_command(label: str, cmd: list[str]) -> bool:
    code, output = run(cmd)
    ok = code == 0
    print(f"[{status(ok)}] {label}")
    if output:
        print(indent(output))
    return ok


def indent(text: str) -> str:
    return "\n".join(f"    {line}" for line in text.splitlines())


def module_available(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def main() -> int:
    print("Phase 0 environment check")
    print(f"Python: {sys.version.split()[0]}")
    print(f"Platform: {sys.platform}")
    print()

    failures = 0

    for mod in REQUIRED_PYTHON_MODULES:
        ok = module_available(mod)
        print(f"[{status(ok)}] Python module: {mod}")
        failures += 0 if ok else 1

    print()
    failures += 0 if check_command("node", ["node", "--version"]) else 1
    failures += 0 if check_command("npm", ["npm", "--version"]) else 1

    print()
    for command in ("google-chrome", "playwright-cli"):
        path = shutil.which(command)
        ok = path is not None
        print(f"[{status(ok)}] Linux command on PATH: {command}")
        if path:
            print(f"    {path}")
        failures += 0 if ok else 1

    print()
    failures += 0 if check_command("google-chrome", ["google-chrome", "--version"]) else 1
    failures += 0 if check_command("playwright-cli", ["playwright-cli", "--version"]) else 1

    print()
    if failures:
        print(f"Result: {failures} check(s) failed.")
        return 1
    print("Result: all checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
