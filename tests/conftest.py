from __future__ import annotations

# ruff: noqa: E402, I001

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import pytest


@pytest.fixture(autouse=True)
def browser_e2e_diagnostics(monkeypatch: pytest.MonkeyPatch):
    """Print browser runtime failures and loaded scripts in the Playwright CI process."""
    if os.environ.get("RA_BROWSER_E2E") != "1":
        yield
        return

    playwright_api = pytest.importorskip("playwright.sync_api")
    original_new_page = playwright_api.Browser.new_page

    def new_page(browser, *args, **kwargs):
        page = original_new_page(browser, *args, **kwargs)
        page.on(
            "console",
            lambda message: print(
                f"[browser console:{message.type}] {message.text}",
                flush=True,
            ),
        )
        page.on(
            "pageerror",
            lambda error: print(f"[browser pageerror] {error}", flush=True),
        )
        page.on(
            "requestfailed",
            lambda request: print(
                f"[browser requestfailed] {request.method} {request.url}: "
                f"{request.failure}",
                flush=True,
            ),
        )

        def report_response(response) -> None:
            resource_type = response.request.resource_type
            if (
                resource_type not in {"document", "script"}
                and "/api/extensions/" not in response.url
            ):
                return
            print(
                f"[browser response:{resource_type}] {response.status} {response.url} "
                f"content-type={response.headers.get('content-type', '')}",
                flush=True,
            )

        page.on("response", report_response)
        return page

    monkeypatch.setattr(playwright_api.Browser, "new_page", new_page)
    yield
