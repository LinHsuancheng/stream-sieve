from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BrowserResult:
    code: int
    output: str

    @property
    def ok(self) -> bool:
        return self.code == 0


class BrowserBackend:
    owns_browser: bool = False

    def attach(self) -> BrowserResult:
        raise NotImplementedError

    def goto(self, url: str) -> BrowserResult:
        raise NotImplementedError

    def snapshot(self) -> BrowserResult:
        raise NotImplementedError

    def text(self) -> BrowserResult:
        raise NotImplementedError

    def html(self) -> BrowserResult:
        raise NotImplementedError

    def links(self) -> BrowserResult:
        raise NotImplementedError

    def scroll(self, count: int = 1, delta_y: int = 1400, wait_seconds: float = 2.0) -> list[BrowserResult]:
        raise NotImplementedError

    def detach(self) -> BrowserResult:
        raise NotImplementedError

    def close_tab(self) -> BrowserResult:
        raise NotImplementedError
