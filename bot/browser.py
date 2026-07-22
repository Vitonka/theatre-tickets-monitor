"""Shared headless-browser and HTTP fetch helpers.

Theatre booking pages fall into two camps:

* Some (National Theatre) block plain scripted requests with a 403 unless a
  realistic browser ``User-Agent`` is sent, but otherwise serve the data in
  static HTML — cheap ``httpx`` fetch is enough.
* Others (Almeida's calendar, Royal Court behind Cloudflare, National
  Theatre's TNEW booking widget) only reveal per-date availability after
  JavaScript runs, so they need a real rendered page.

``fetch_html`` covers the first case; ``render_html`` covers the second. Both
share one long-lived Chromium instance so we are not paying browser-startup
cost on every 15-minute poll.
"""
from __future__ import annotations

import asyncio
from typing import Optional

import httpx
from playwright.async_api import Browser, async_playwright

from .config import Config

# A current, real desktop Chrome UA. Sites fingerprint obviously-bot UAs.
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)
_HTTP_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9",
}


class BrowserManager:
    """Owns a single Chromium instance for the process lifetime."""

    def __init__(self, config: Config):
        self._config = config
        self._pw = None
        self._browser: Optional[Browser] = None
        self._lock = asyncio.Lock()

    async def _ensure_browser(self) -> Browser:
        async with self._lock:
            if self._browser and self._browser.is_connected():
                return self._browser
            if self._pw is None:
                self._pw = await async_playwright().start()
            launch_kwargs: dict = {
                "headless": self._config.headless,
                "args": ["--no-sandbox", "--disable-dev-shm-usage"],
            }
            if self._config.browser_executable_path:
                launch_kwargs["executable_path"] = self._config.browser_executable_path
            self._browser = await self._pw.chromium.launch(**launch_kwargs)
            return self._browser

    async def render_html(
        self,
        url: str,
        wait_selector: str | None = None,
        settle_ms: int = 3500,
        wait_until: str = "domcontentloaded",
        wait_timeout_ms: int | None = None,
    ) -> str:
        """Return the fully-rendered DOM after JS has run.

        ``wait_selector`` (when given) is waited for before snapshotting, up to
        ``wait_timeout_ms`` (defaults to the page timeout); missing it is not an
        error — we fall through and still snapshot. A short settle delay follows
        for late XHR-driven content. ``wait_until`` is the goto load state; we
        avoid "networkidle" for pages that keep a connection open (it can hang).
        """
        browser = await self._ensure_browser()
        context = await browser.new_context(
            user_agent=USER_AGENT,
            locale="en-GB",
            viewport={"width": 1280, "height": 2200},
        )
        page = await context.new_page()
        try:
            await page.goto(
                url,
                wait_until=wait_until,
                timeout=self._config.page_timeout_ms,
            )
            if wait_selector:
                try:
                    await page.wait_for_selector(
                        wait_selector,
                        timeout=wait_timeout_ms or self._config.page_timeout_ms,
                    )
                except Exception:
                    # Fall through: the caller's parser decides if content is
                    # usable. Missing selector often just means "sold out".
                    pass
            await page.wait_for_timeout(settle_ms)
            return await page.content()
        finally:
            await context.close()

    async def close(self) -> None:
        async with self._lock:
            if self._browser:
                await self._browser.close()
                self._browser = None
            if self._pw:
                await self._pw.stop()
                self._pw = None


async def fetch_html(url: str) -> str:
    """Plain HTTP GET with a browser-like UA. Raises on non-2xx."""
    async with httpx.AsyncClient(
        headers=_HTTP_HEADERS, follow_redirects=True, timeout=30.0
    ) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.text


async def fetch_json(url: str) -> object:
    """Plain HTTP GET returning parsed JSON (used for Spektrix API calls)."""
    async with httpx.AsyncClient(
        headers={**_HTTP_HEADERS, "Accept": "application/json"},
        follow_redirects=True,
        timeout=30.0,
    ) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.json()
