from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import time

import yaml


ROOT = Path(__file__).resolve().parents[1]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a Stream Sieve pipeline config.")
    parser.add_argument("config", nargs="?", default="config.yaml")
    parser.add_argument("--env-file", default=".env")
    parser.add_argument(
        "--stage",
        choices=("all", "sieve", "send-email"),
        default="all",
        help="Run the full pipeline or one independent project stage.",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    env = os.environ.copy()
    env.update(load_env(ROOT / args.env_file))
    config = load_yaml(ROOT / args.config)["run"]
    py = env.get("PY", ".venv/bin/python")
    db = expand(need(config, "db"))
    source_pool = config.get("source_pool", "sourcepool.yaml")
    source_pool_data = load_yaml(ROOT / source_pool).get("sources", {})
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
                "sieve",
                "--db",
                db,
                "--cdp-endpoint",
                cdp_endpoint,
                *[f"{need(source, 'path')}:{need(source, 'sync_limit')}" for source in sources],
            ]
        )

    scoring = config.get("scoring", {})
    fields = config.get("fields") or {}
    field_limits = {field: need(field_config, "target_items") for field, field_config in fields.items()}
    field_runs = build_field_runs(fields, source_pool_data)
    if not field_runs:
        field_runs = [(None, {}, None)]
    for field, field_config, source_ids in field_runs:
        command = [
            py,
            "-m",
            "stream_sieve.cli",
            "score",
            "--db",
            db,
            "--limit",
            str(field_config.get("score_limit") or need(scoring, "limit")),
            "--prefilter-scan-limit",
            str(field_config.get("prefilter_scan_limit") or need(scoring, "prefilter_scan_limit")),
            "--prefilter-min-score",
            str(field_config.get("prefilter_min_score", need(scoring, "prefilter_min_score"))),
            "--interests",
            need(scoring, "interests"),
            "--model",
            need(scoring, "model"),
            "--base-url",
            need(scoring, "base_url"),
            "--sample-chars",
            str(need(scoring, "sample_chars")),
            "--categories",
            ",".join([field] if field else need(scoring, "categories")),
            "--source-pool",
            source_pool,
            "--batch-size",
            str(need(scoring, "batch_size")),
            "--timeout",
            str(need(scoring, "timeout")),
            "--retries",
            str(need(scoring, "retries")),
        ]
        if field:
            command.extend(["--field", field])
            command.extend(["--field-mode", str(field_config.get("mode") or "")])
            command.extend(["--field-horizon", str(field_config.get("horizon") or "")])
            if field_config.get("profile"):
                command.extend(["--field-profile", str(field_config["profile"])])
        if source_ids:
            command.extend(["--source-ids", ",".join(source_ids)])
        if need(scoring, "nonthink"):
            command.append("--nonthink")
        commands.append(command)

    analysis = config.get("analysis", {})
    for field, field_config, source_ids in field_runs:
        command = [
            py,
            "-m",
            "stream_sieve.cli",
            "analyze",
            "--db",
            db,
            "--min-score",
            str(need(analysis, "min_score")),
            "--limit",
            str(field_config.get("analyze_limit") or need(analysis, "limit")),
            "--model",
            need(analysis, "model") if analysis.get("model") else need(scoring, "model"),
            "--base-url",
            need(analysis, "base_url") if analysis.get("base_url") else need(scoring, "base_url"),
            "--content-chars",
            str(need(analysis, "content_chars")),
            "--source-pool",
            source_pool,
            "--batch-size",
            str(need(analysis, "batch_size")),
            "--timeout",
            str(need(analysis, "timeout")),
            "--retries",
            str(need(analysis, "retries")),
        ]
        if source_ids:
            command.extend(["--source-ids", ",".join(source_ids)])
        if analysis.get("nonthink", need(scoring, "nonthink")):
            command.append("--nonthink")
        commands.append(command)

    brief = config.get("brief", {})
    brief_output = need(brief, "output")
    delivery = config.get("delivery", {})
    delivery_key = delivery.get("delivery_key") or need(delivery, "config")
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
            "--model",
            need(scoring, "model"),
            "--base-url",
            need(scoring, "base_url"),
            "--timeout",
            str(need(scoring, "timeout")),
            "--retries",
            str(need(scoring, "retries")),
            "--delivery-key",
            delivery_key,
            "--category-limits",
            json.dumps(need(brief, "category_limits"), ensure_ascii=False),
            "--field-limits",
            json.dumps(field_limits or need(brief, "category_limits"), ensure_ascii=False),
            "--source-pool",
            source_pool,
            "--output",
            brief_output,
        ]
    )
    if need(scoring, "nonthink"):
        commands[-1].append("--nonthink")

    send_command = [
        py,
        "-m",
        "stream_sieve.cli",
        "send-email",
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
        "--category-limits",
        json.dumps(need(brief, "category_limits"), ensure_ascii=False),
        "--field-limits",
        json.dumps(field_limits or need(brief, "category_limits"), ensure_ascii=False),
        "--source-pool",
        source_pool,
    ]
    send_command.extend(["--delivery-key", delivery_key])
    if delivery.get("resend"):
        send_command.append("--resend")
    if args.stage == "all":
        body_index = send_command.index("--category-limits")
        send_command[body_index:body_index] = ["--body-file", brief_output]
    commands.append(send_command)

    commands.append([py, "-m", "stream_sieve.cli", "status", "--db", db])

    if args.stage != "all":
        commands = [command for command in commands if command[3] == args.stage]

    if args.dry_run:
        if boot_command and args.stage in {"all", "sieve"}:
            print(shlex.join(boot_command))
        for command in commands:
            print(shlex.join(command))
        return 0

    chrome_proc: subprocess.Popen | None = None
    chrome_log = None
    if boot_command and args.stage in {"all", "sieve"}:
        print("== browser_boot ==", flush=True)
        port = int(need(config.get("browser_boot") or {}, "remote_debugging_port"))
        if is_chrome_cdp_ready(port):
            print(f"Chrome CDP already listening on 127.0.0.1:{port}", flush=True)
        elif is_port_open(port):
            replacement_port = find_free_port(port + 1)
            print(
                f"Port 127.0.0.1:{port} is open but not Chrome CDP; launching Chrome on 127.0.0.1:{replacement_port}",
                flush=True,
            )
            port = replacement_port
            cdp_endpoint = f"http://127.0.0.1:{port}"
            set_sieve_cdp_endpoint(commands, cdp_endpoint)
            chrome_log = open("/tmp/stream-sieve-chrome.log", "a", encoding="utf-8")
            chrome_proc = subprocess.Popen(
                build_browser_boot_command(browser_boot, port=port),
                cwd=ROOT,
                env=env,
                stdout=chrome_log,
                stderr=chrome_log,
                start_new_session=True,
            )
        else:
            chrome_log = open("/tmp/stream-sieve-chrome.log", "a", encoding="utf-8")
            chrome_proc = subprocess.Popen(
                build_browser_boot_command(browser_boot, port=port),
                cwd=ROOT,
                env=env,
                stdout=chrome_log,
                stderr=chrome_log,
                start_new_session=True,
            )
        wait = float((config.get("browser_boot") or {}).get("startup_wait_seconds", 5))
        if wait > 0:
            time.sleep(wait)
        if not is_chrome_cdp_ready(port):
            raise RuntimeError(f"Chrome CDP did not become ready on 127.0.0.1:{port}")
        print(flush=True)

    try:
        for command in commands:
            print(f"== {command[3]} ==", flush=True)
            if command[3] == "send-email" and chrome_proc:
                print("== cleanup: stopping Chrome before send-email ==", flush=True)
                stop_process(chrome_proc, "Chrome")
                chrome_proc = None
                if chrome_log:
                    chrome_log.close()
                    chrome_log = None
            subprocess.run(command, cwd=ROOT, env=env, check=True)
            print(flush=True)
        return 0
    finally:
        if chrome_proc:
            stop_process(chrome_proc, "Chrome")
        if chrome_log:
            chrome_log.close()


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
    result = curl_local_json_version(port)
    return result.returncode == 0 or result.stdout.startswith("HTTP/1.")


def is_chrome_cdp_ready(port: int) -> bool:
    result = curl_local_json_version(port)
    text = result.stdout
    if result.returncode != 0 or "HTTP/1.1 200" not in text and "HTTP/1.0 200" not in text:
        return False
    return '"Browser"' in text and '"webSocketDebuggerUrl"' in text


def curl_local_json_version(port: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["curl", "--noproxy", "*", "-sS", "-i", f"http://127.0.0.1:{port}/json/version"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=3,
    )


def find_free_port(start: int) -> int:
    for port in range(start, start + 50):
        if not is_port_open(port):
            return port
    raise RuntimeError(f"no free local port found from {start} to {start + 49}")


def set_sieve_cdp_endpoint(commands: list[list[str]], cdp_endpoint: str) -> None:
    for command in commands:
        if len(command) > 4 and command[3] == "sieve" and "--cdp-endpoint" in command:
            command[command.index("--cdp-endpoint") + 1] = cdp_endpoint


def build_field_runs(fields: dict, source_pool: dict) -> list[tuple[str, dict, list[str]]]:
    runs = []
    for field, config in fields.items():
        source_ids = list(config.get("sources") or [])
        if not source_ids:
            source_ids = [
                source_id
                for source_id, meta in source_pool.items()
                if isinstance(meta, dict)
                and field in (meta.get("briefing_categories") or [meta.get("briefing_category")])
            ]
        if source_ids:
            runs.append((str(field), config, source_ids))
    return runs


def stop_process(proc: subprocess.Popen, name: str) -> None:
    if proc.poll() is not None:
        return
    print(f"== cleanup: stopping {name} ==", flush=True)
    proc.terminate()
    try:
        proc.wait(timeout=8)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=8)


def need(config: dict, key: str):
    if key not in config:
        raise KeyError(f"missing config key: {key}")
    return config[key]


def build_browser_boot_command(config: dict, port: int | None = None) -> list[str] | None:
    if not config.get("enabled", False):
        return None
    executable = str(need(config, "executable"))
    user_data_dir = expand(str(need(config, "user_data_dir")))
    port_text = str(port if port is not None else need(config, "remote_debugging_port"))
    url = str(need(config, "url"))
    return [
        executable,
        f"--remote-debugging-port={port_text}",
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
