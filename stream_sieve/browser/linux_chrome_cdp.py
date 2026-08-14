from __future__ import annotations

import json
import os
import subprocess
import time

from .base import BrowserBackend, BrowserResult


class LinuxChromeCdpBackend(BrowserBackend):
    """Attach to Linux Chrome through Chrome DevTools Protocol."""

    owns_browser = False

    def __init__(
        self,
        session: str = "chrome-main",
        cdp_endpoint: str = "http://127.0.0.1:9222",
    ) -> None:
        self.session = session
        self.cdp_endpoint = cdp_endpoint

    def attach(self) -> BrowserResult:
        self._run_playwright(["detach"], timeout=10)
        return self._run_playwright(["attach", f"--cdp={self.cdp_endpoint}", f"--session={self.session}"], timeout=120)

    def goto(self, url: str) -> BrowserResult:
        code = f"async page => {{ await page.goto({json.dumps(url)}, {{ waitUntil: 'domcontentloaded', timeout: 30000 }}); }}"
        result = self._run_playwright(["run-code", code], timeout=45)
        if session_lost(result.output):
            attach = self.attach()
            if not attach.ok:
                return attach
            result = self._run_playwright(["run-code", code], timeout=45)
        return result

    def snapshot(self) -> BrowserResult:
        return self._run_playwright(["snapshot"], timeout=60)

    def text(self) -> BrowserResult:
        return self._run_playwright(["eval", "() => document.body && document.body.innerText || ''"], raw=True, timeout=60)

    def html(self) -> BrowserResult:
        return self._run_playwright(["eval", "() => document.documentElement.outerHTML"], raw=True, timeout=60)

    def links(self) -> BrowserResult:
        script = (
            "() => JSON.stringify(Array.from(document.querySelectorAll('a')).slice(0, 500)"
            ".map(a => ({ title: (a.innerText || a.textContent || a.getAttribute('aria-label') || '').trim(), url: a.href }))"
            ".filter(x => x.title && x.url))"
        )
        return self._run_playwright(["eval", script], raw=True, timeout=30)

    def wait_until_stable(
        self,
        *,
        max_seconds: float,
        min_seconds: float = 0.5,
        interval_seconds: float = 0.25,
        stable_checks: int = 2,
    ) -> BrowserResult:
        if max_seconds > 0:
            time.sleep(max_seconds)
        return BrowserResult(0, f"waited {max_seconds:g}s")

    def scroll(self, count: int = 1, delta_y: int = 1400, wait_seconds: float = 2.0) -> list[BrowserResult]:
        results: list[BrowserResult] = []
        for _ in range(max(0, count)):
            result = self._run_playwright(["eval", f"() => {{ window.scrollBy(0, {delta_y}); return true; }}"], timeout=30)
            results.append(result)
            if not result.ok:
                break
            if wait_seconds > 0:
                results.append(self.wait_until_stable(max_seconds=wait_seconds, min_seconds=0.2))
        return results

    def detach(self) -> BrowserResult:
        return self._run_playwright(["detach"], timeout=30)

    def close_tab(self) -> BrowserResult:
        return self.detach()

    def _run_playwright(self, args: list[str], *, raw: bool = False, timeout: int = 60) -> BrowserResult:
        command = ["playwright-cli", f"--s={self.session}"]
        if raw:
            command.append("--raw")
        command.extend(args)
        env = os.environ.copy()
        for key in (
            "HTTP_PROXY",
            "HTTPS_PROXY",
            "ALL_PROXY",
            "http_proxy",
            "https_proxy",
            "all_proxy",
        ):
            env.pop(key, None)
        env["NO_PROXY"] = "127.0.0.1,localhost"
        env["no_proxy"] = "127.0.0.1,localhost"
        proc = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            timeout=timeout,
        )
        output = proc.stdout.strip()
        if raw and proc.returncode == 0:
            output = _decode_raw_output(output)
        if proc.returncode != 0 and "EADDRINUSE" in output:
            return BrowserResult(0, "Session already running; reusing existing Playwright CLI session.")
        return BrowserResult(proc.returncode, output)


def _decode_raw_output(output: str) -> str:
    try:
        value = json.loads(output)
    except json.JSONDecodeError:
        return output
    return value if isinstance(value, str) else output


def session_lost(output: str) -> bool:
    text = output.lower()
    return (
        "target page, context or browser has been closed" in text
        or "the browser" in text and "is not open" in text
        or "econnrefused" in text
    )
