"""Live probe / tuning helper.

Run this in an environment with direct internet access (e.g. the machine that
runs the bot) to:

  * confirm an adapter can reach a production URL and what it extracts, and
  * dump the fully-rendered booking DOM so per-date availability wording can be
    inspected and, if needed, the markers in ``bot/adapters/availability.py``
    tuned for a site.

Usage:
    python -m scripts.probe fetch  "<production url>"     # run the real adapter
    python -m scripts.probe render "<url>" [out.html]     # dump rendered DOM
"""
from __future__ import annotations

import asyncio
import sys

from bot.adapters import resolve
from bot.browser import BrowserManager
from bot.config import Config


def _config() -> Config:
    import os

    os.environ.setdefault("TELEGRAM_BOT_TOKEN", "probe")  # not used here
    return Config.from_env()


async def cmd_fetch(url: str) -> None:
    adapter = resolve(url)
    if adapter is None:
        print("No adapter matches that URL.")
        return
    browser = BrowserManager(_config())
    try:
        result = await adapter.fetch(url, browser)
    finally:
        await browser.close()
    avail = result.available
    print(f"Adapter : {adapter.name}")
    print(f"Title   : {result.title}")
    print(f"Perfs   : {len(result.performances)} total, {len(avail)} with tickets")
    for p in avail[:80]:
        print(f"  ✅ {p.display_date}")


async def cmd_render(url: str, out: str = "rendered.html") -> None:
    browser = BrowserManager(_config())
    try:
        html = await browser.render_html(url, settle_ms=5000)
    finally:
        await browser.close()
    with open(out, "w") as f:
        f.write(html)
    print(f"Wrote {out} ({len(html)} bytes)")


def main() -> None:
    if len(sys.argv) < 3:
        print(__doc__)
        raise SystemExit(1)
    cmd, url = sys.argv[1], sys.argv[2]
    if cmd == "fetch":
        asyncio.run(cmd_fetch(url))
    elif cmd == "render":
        out = sys.argv[3] if len(sys.argv) > 3 else "rendered.html"
        asyncio.run(cmd_render(url, out))
    else:
        print(__doc__)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
