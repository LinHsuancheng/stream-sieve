from __future__ import annotations

import argparse
import os
from pathlib import Path
import shlex
import socket
import subprocess
import sys
import time

import yaml


ROOT = Path(__file__).resolve().parents[1]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a Stream Sieve pipeline config.")
    parser.add_argument("config", nargs="?", default="config.yaml")
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    env = os.environ.copy()
    env.update(load_env(ROOT / args.env_file))
    config = load_yaml(ROOT / args.config)["run"]
    py = env.get("PY", ".venv/bin/python")
    db = expand(need(config, "db"))
    browser_boot = config.get("browser_boot") or {}
    boot_command = build_browser_boot_command(browser_boot)
    cdp_endpoint = f"http://127.0.0.1:{need(browser_boot, 'remote_debugging_port')}"

    commands: list[list[str]] = []
    sources = config.get("sources", [])
    if sources:
        commands.append(
            [
                py,
                "-m",
                "stream_sieve.cli",
                "sync-many",
                "--db",
                db,
                "--cdp-endpoint",
                cdp_endpoint,
                *[f"{need(source, 'path')}:{need(source, 'sync_limit')}" for source in sources],
            ]
        )

    scoring = config.get("scoring", {})
    commands.append(
        [
            py,
            "-m",
            "stream_sieve.cli",
            "score",
            "--db",
            db,
            "--limit",
            str(need(scoring, "limit")),
            "--interests",
            need(scoring, "interests"),
            "--model",
            need(scoring, "model"),
            "--base-url",
            need(scoring, "base_url"),
            "--sample-chars",
            str(need(scoring, "sample_chars")),
            "--batch-size",
            str(need(scoring, "batch_size")),
            "--timeout",
            str(need(scoring, "timeout")),
            "--retries",
            str(need(scoring, "retries")),
        ]
    )
    if need(scoring, "nonthink"):
        commands[-1].append("--nonthink")

    brief = config.get("brief", {})
    commands.append(
        [
            py,
            "-m",
            "stream_sieve.cli",
            "brief",
            "--db",
            db,
            "--min-score",
            str(need(brief, "min_score")),
            "--limit",
            str(need(brief, "limit")),
            "--excerpt-chars",
            str(need(brief, "excerpt_chars")),
            "--output",
            need(brief, "output"),
        ]
    )

    delivery = config.get("delivery", {})
    send_command = [
        py,
        "-m",
        "stream_sieve.cli",
        "send",
        "--config",
        need(delivery, "config"),
        "--db",
        db,
        "--min-score",
        str(need(brief, "min_score")),
        "--limit",
        str(need(brief, "limit")),
        "--excerpt-chars",
        str(need(brief, "excerpt_chars")),
        "--subject",
        need(delivery, "subject"),
    ]
    if delivery.get("delivery_key"):
        send_command.extend(["--delivery-key", str(delivery["delivery_key"])])
    if delivery.get("resend"):
        send_command.append("--resend")
    commands.append(send_command)

    commands.append([py, "-m", "stream_sieve.cli", "status", "--db", db])

    if args.dry_run:
        if boot_command:
            print(shlex.join(boot_command))
        for command in commands:
            print(shlex.join(command))
        return 0

    if boot_command:
        print("== browser_boot ==", flush=True)
        port = int(need(config.get("browser_boot") or {}, "remote_debugging_port"))
        if is_port_open(port):
            print(f"Chrome CDP already listening on 127.0.0.1:{port}", flush=True)
        else:
            subprocess.Popen(
                boot_command,
                cwd=ROOT,
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        wait = float((config.get("browser_boot") or {}).get("startup_wait_seconds", 5))
        if wait > 0:
            time.sleep(wait)
        print(flush=True)

    for command in commands:
        print(f"== {command[3]} ==", flush=True)
        subprocess.run(command, cwd=ROOT, env=env, check=True)
        print(flush=True)
    return 0


def load_env(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    out: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        value = value.strip().strip("'\"")
        if value:
            out[key.strip()] = value
    return out


def load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def is_port_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.25)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def need(config: dict, key: str):
    if key not in config:
        raise KeyError(f"missing config key: {key}")
    return config[key]


def build_browser_boot_command(config: dict) -> list[str] | None:
    if not config.get("enabled", False):
        return None
    executable = str(need(config, "executable"))
    user_data_dir = expand(str(need(config, "user_data_dir")))
    port = str(need(config, "remote_debugging_port"))
    url = str(need(config, "url"))
    return [
        executable,
        f"--remote-debugging-port={port}",
        f"--user-data-dir={user_data_dir}",
        "--no-first-run",
        "--disable-default-apps",
        "--new-window",
        url,
    ]


def expand(value: str) -> str:
    return str(Path(value).expanduser())


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
