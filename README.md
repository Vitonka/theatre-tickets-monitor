# 🎭 Theatre Ticket Monitor

A self-hosted Telegram bot that watches sold-out theatre productions and
messages you — with **date and price** — when tickets appear (returns,
released holds, extra performances).

Supported theatres out of the box:

| Theatre | Data source | Reliable signal |
| --- | --- | --- |
| **Almeida** (`almeida.co.uk`) | Rendered calendar page | Per-date sold-out / price |
| **Royal Court** (`royalcourttheatre.com`) | Spektrix public JSON API | Per-date list + on-sale state |
| **National Theatre** (`nationaltheatre.org.uk`) | schema.org data + rendered booking widget | Per-date list + availability text |

New theatres are added by dropping one small adapter into `bot/adapters/` — see
[Adding a theatre](#adding-a-theatre).

## How it works

Every `POLL_INTERVAL_MIN` minutes (default 15) the bot re-checks each monitored
production. For each performance it compares "available now" against the last
recorded state and messages you **only when a performance flips from
unavailable → available**, so you get one alert per opening, not a repeat every
cycle. If a performance sells out and later reopens, you're alerted again.

State lives in a small SQLite database (mounted as a Docker volume), so your
monitors and their history survive restarts.

## Setup

1. **Create a bot.** In Telegram, message [@BotFather](https://t.me/BotFather),
   send `/newbot`, follow the prompts, and copy the token it gives you.
2. **Configure.**
   ```bash
   cp .env.example .env
   # edit .env and paste your TELEGRAM_BOT_TOKEN
   ```
   Optionally set `ALLOWED_USER_IDS` (comma-separated Telegram user IDs, from
   [@userinfobot](https://t.me/userinfobot)) so only you can use the bot.
3. **Run.**
   ```bash
   docker compose up -d --build
   ```
4. **Use it.** Message your bot `/start`.

## Bot commands

| Command | Description |
| --- | --- |
| `/add <url>` | Start monitoring a production page (paste the show's URL). |
| `/list` | Show what you're monitoring, with ids. |
| `/remove` | Tap a show to stop monitoring it (or `/remove <id>`). |
| `/help` | Show help and supported theatres. |

When you `/add` a show, the bot fetches it once to validate the link and record
the title, then only alerts on **new** availability from then on.

## Availability detection — what's reliable, and tuning

Getting the *list of performance dates* is reliable for all three theatres
(structured data / official API). Detecting **per-date seat availability** is
done from each site's live booking interface, which is JavaScript-rendered and
occasionally changes its wording. The availability vocabulary ("Sold Out",
"Book now", price markers, …) is centralised in
[`bot/adapters/availability.py`](bot/adapters/availability.py) so it's easy to
adjust in one place.

Note on **Royal Court**: its Spektrix public API gives the authoritative date
list and an `isOnSale` flag, but does not expose per-seat counts, so "available"
there currently means "open for public sale". For a show that stays on sale but
sold out, catching returns needs the rendered booking widget — a documented
next step (see `scripts/probe.py`).

Use the probe helper (from a machine with direct internet) to see exactly what
an adapter extracts, or to dump a rendered page for inspection:

```bash
python -m scripts.probe fetch  "https://almeida.co.uk/whats-on/golden-boy/"
python -m scripts.probe render "https://almeida.co.uk/calendar/?e=golden-boy" out.html
```

## Development

```bash
pip install -r requirements.txt
pip install pytest pytest-asyncio
python -m pytest            # parser + storage + dedup tests (offline, uses fixtures)
```

Tests run against real HTML/JSON captured from the live sites in
`tests/fixtures/`, so parsing logic is verified without network access.

### Adding a theatre

1. Create `bot/adapters/<name>.py` with a `TheatreAdapter` subclass implementing
   `matches(url)` and `async fetch(url, browser)`. Reuse the helpers in
   `bot/adapters/util.py` and `availability.py`.
2. Register an instance in `bot/adapters/__init__.py`'s `ADAPTERS` list.
3. Add a fixture + test in `tests/`.

## Configuration reference

| Env var | Default | Meaning |
| --- | --- | --- |
| `TELEGRAM_BOT_TOKEN` | — (required) | Bot token from @BotFather. |
| `ALLOWED_USER_IDS` | empty | Comma-separated allowed user ids; empty = open. |
| `POLL_INTERVAL_MIN` | `15` | Minutes between checks. |
| `DB_PATH` | `data/monitors.db` | SQLite path (a volume in Docker). |
| `BROWSER_EXECUTABLE_PATH` | empty | Point at a specific Chromium if needed. |
| `PAGE_TIMEOUT_MS` | `45000` | Per-page render budget. |
