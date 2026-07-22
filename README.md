# 🎭 Theatre Ticket Monitor

A self-hosted Telegram bot that watches sold-out theatre productions and
messages you — with **date and price** — when tickets appear (returns,
released holds, extra performances).

Supported theatres out of the box:

| Theatre | Data source | Reliable signal |
| --- | --- | --- |
| **Almeida** (`almeida.co.uk`) | Calendar admin-ajax endpoint | Per-date sold-out (CSS state) |
| **Royal Court** (`royalcourttheatre.com`) | Spektrix schedule + rendered page | Per-date buyable (excludes Access-only) |
| **National Theatre** (`nationaltheatre.org.uk`) | Events API + per-performance TNEW seat page | Real per-performance availability |

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

Each adapter reads the *real* per-performance availability the box office shows;
alerts list only dates with buyable tickets (no prices).

- **Almeida** — reads its calendar `admin-ajax` endpoint; each date's CSS state
  (`--sold-out` vs a book button) is the truth. No browser.
- **National Theatre** — takes the schedule + performance ids from the events API,
  then checks each performance's TNEW seat page, which is unambiguous:
  `"Best available"` = bookable, `"Not currently available"` = sold out. TNEW is
  behind a queue-it waiting room; a plain HTTP fetch passes it in most cases and
  the adapter falls back to the headless browser for any performance that comes
  back ambiguous. (This means one request per performance.)
- **Royal Court** — takes the schedule from Spektrix and reads buyability from the
  rendered production page: a `"Book now"` action with a plain `/book/instance/{id}`
  link is buyable; `"Sold out *"` (an `…&requireLogin=true` link) means only
  Access-Members / returns remain and is treated as not available. Rendered
  performances are joined to the Spektrix schedule by instance id.

All checks are conservative — only a positive "buyable" signal marks a date
available, so a blocked/failed fetch yields no availability rather than a false
alert. To inspect what a site serves, use `scripts/probe.py`.

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
