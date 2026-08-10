# Fetan Eta Bot — MVP

Telegram lottery bot: group members reserve a number, pay, get verified by
an admin, then three winners are drawn live with a provably-fair
commit/reveal scheme.

## Stack

- aiogram 3.x (async, webhook-first — ready for a future Telegram Mini App)
- MongoDB (Motor async driver)
- aiohttp for the built-in web server (health/root/ping + webhook endpoint)
- Deployable as: Vercel functions, a long-running polling process, or a
  standard web service (Docker/Procfile/gunicorn) on basically any host

## 1. Setup

```bash
cd fetan-eta-bot
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env            # then fill in the real values
```

You need:

- A bot token from **@BotFather**.
- A free **MongoDB Atlas** cluster (or local `mongod`) connection string.
- Your own Telegram numeric user ID (and any co-admins) for `ADMIN_IDS`.
  Get it from **@userinfobot**.

`.env` is loaded automatically (via `python-dotenv`) whenever you run
`main.py`, `app.py`, `bot.py`, or `run_polling.py` locally — no need to
`export` anything by hand.

## 2. Test locally first (recommended, no deployment needed)

```bash
python run_polling.py
```

This forces polling mode regardless of your `.env`. Add the bot to a test
group, make it an admin, and try the flow:

1. `/newround 200 2000 500 300` — creates round #1, price 200 ETB, prizes
   2000/500/300, default 20 numbers.
2. Tap a number → bot DMs you payment instructions (press **Start** on the
   bot in a private chat first if you haven't).
3. Reply in the private chat with any text (fake transaction ID) or a photo.
4. As an admin, run `/pending` in the group — approve/reject buttons appear.
5. Tap **Approve** — the group board updates to 🟢.
6. `/closeregistration`, then `/startdraw` — watch the draw animation and
   results post in the group.
7. Winners get DM'd — reply as a winner with a fake account string.
8. `/payout <round_number> <telegram_id>` marks that winner as paid.

## 3. How deployment mode is chosen

Every entrypoint (`main.py`, `app.py`, `bot.py`) shares the same logic,
controlled by env vars — **not** by which file you run:

| RUN_MODE  | Behavior                                                                                                                     | Needs                                                                                                                    |
| --------- | ---------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------ |
| `polling` | Long-lived polling loop                                                                                                      | Just `BOT_TOKEN` + `MONGO_URI` — works anywhere, even with no public URL at all (VPS, systemd, a background worker dyno) |
| `webhook` | Starts an aiohttp server exposing `/` `/health` `/ping` (health checks / keep-alive pings) and `/webhook` (Telegram updates) | A public URL platforms can reach — set `PUBLIC_URL` so it self-registers the webhook on startup                          |

If `RUN_MODE` isn't set explicitly, it's auto-detected: **webhook** if
`PORT` is present (most PaaS web services inject this automatically),
**polling** otherwise. You can always override with `RUN_MODE=polling` or
`RUN_MODE=webhook` explicitly.

## 4. Deployment options

### A) Vercel (serverless, original setup — still supported)

```bash
vercel
vercel env add BOT_TOKEN
vercel env add MONGO_URI
vercel env add MONGO_DB_NAME
vercel env add ADMIN_IDS
vercel env add WEBHOOK_SECRET
vercel --prod
```

Then register the webhook once (serverless has no startup hook to do this
automatically):

```bash
export BOT_TOKEN=... WEBHOOK_URL=https://your-app.vercel.app/api/webhook WEBHOOK_SECRET=...
python set_webhook.py
```

Health check: `GET https://your-app.vercel.app/api/webhook` → `{"status": "alive"}`.

### B) Docker (any host that runs containers)

```bash
docker build -t fetan-eta-bot .
docker run -d --env-file .env -p 8080:8080 \
  -e PUBLIC_URL=https://your-domain.example \
  fetan-eta-bot
```

The image's `HEALTHCHECK` hits `/health` automatically. Run it as a
background worker instead (no public URL needed) with:

```bash
docker run -d --env-file .env -e RUN_MODE=polling fetan-eta-bot
```

### C) `docker-compose` (local dev with a real Mongo, no Atlas needed)

```bash
docker compose up
```

Runs the bot in polling mode against a local Mongo container — good for
testing the full flow without touching a cloud database.

### D) Railway / Render / Fly.io / Heroku-style platforms

These all understand a `Procfile`:

```
web: python main.py
worker: RUN_MODE=polling python main.py
```

Pick the `web` process type if you want a public webhook service (set
`PUBLIC_URL` to whatever domain the platform gives you, and it self-hosts
the webhook + health checks), or `worker` for a simple polling background
process. Most of these platforms also just run a Dockerfile directly if
present — either works.

For Render specifically: set the health check path to `/health` in the
dashboard; the `/ping` route is there if the platform (or an external
uptime pinger like UptimeRobot/cron-job.org) needs something to hit
periodically to prevent the service from sleeping on free tiers.

### E) gunicorn (production-grade aiohttp serving)

```bash
gunicorn -k aiohttp.GunicornWebWorker -b 0.0.0.0:8080 app:app
```

`app.py` exposes a ready-built aiohttp `Application` at import time
specifically for this.

### F) Plain VPS / systemd (long-running, no container)

```ini
# /etc/systemd/system/fetan-eta-bot.service
[Unit]
Description=Fetan Eta Telegram Bot
After=network.target

[Service]
WorkingDirectory=/opt/fetan-eta-bot
EnvironmentFile=/opt/fetan-eta-bot/.env
Environment=RUN_MODE=polling
ExecStart=/opt/fetan-eta-bot/.venv/bin/python main.py
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

Polling mode needs no public URL, no reverse proxy, nothing — just a
running process.

## 5. Admin commands (run inside the group)

| Command                                            | Purpose                                                   |
| -------------------------------------------------- | --------------------------------------------------------- |
| `/newround <price> <p1> <p2> <p3> [total_numbers]` | Start a round (default 20 numbers)                        |
| `/closeregistration`                               | Lock number selection, prepare for draw                   |
| `/startdraw`                                       | Run the provably-fair draw + animation                    |
| `/pending`                                         | List payments awaiting review with Approve/Reject buttons |
| `/cancelround`                                     | Void the current round                                    |
| `/payout <round_number> <telegram_id>`             | Mark a winner's prize as paid                             |

## 6. Project layout

```
main.py                  canonical entrypoint (polling or webhook, env-driven)
app.py                   alias entrypoint; also exposes `app` for gunicorn
bot.py                   alias entrypoint (some platforms/tutorials expect this name)
run_polling.py           forces polling mode, for quick local testing
set_webhook.py           one-off script to register the webhook (needed for Vercel)
Procfile                 Heroku/Railway-style process declarations
Dockerfile               container build for any Docker-capable host
docker-compose.yml        local dev stack (bot + Mongo)
api/webhook.py            Vercel serverless entrypoint (unchanged, separate from the above)

core/config.py            env var loading + RUN_MODE detection (was `bot/` — renamed
core/dispatcher.py         to free up bot.py as a top-level entrypoint name)
core/webserver.py         aiohttp app: webhook handler + health/root/ping routes
core/keyboards.py         inline keyboards (number grid, approve/reject)
core/texts.py             all user-facing strings + board text builder
core/routers/
  common.py                /start /help
  admin.py                  round management, verification, payouts
  selection.py               number tap handling (group)
  private.py                 payment proof + payout claim (private chat, no FSM)

db/client.py              Mongo connection singleton
db/repository.py          every Mongo query lives here, nowhere else
services/round_service.py   round/number/payment business logic
services/draw_service.py    provably-fair draw + animation
```

> Note: the internal package was renamed from `bot/` to `core/`. A
> top-level `bot.py` file and a `bot/` package can't coexist in the same
> directory in Python — this rename is what makes `bot.py` safely
> available as an entrypoint alongside `main.py` and `app.py`.

## 7. Known MVP limitations (intentional — for the next iteration)

- **No auto-expiry of pending numbers.** If someone taps a number and never
  pays, it stays 🟡 until an admin rejects it manually.
- **Draw animation runs synchronously** inside the request/loop (a few
  seconds of `asyncio.sleep`). Fine for a handful of frames; for longer or
  smoother animations, move it to a periodic job that advances one frame
  per tick (works the same in webhook or polling mode).
- **Single active round per group** — starting a new round is blocked until
  the current one reaches `completed` or `cancelled`.
- **No `users` collection yet** — user info is stored inline on
  payments/rounds. Fine for MVP; worth normalizing once you add
  stats/history features.
- **Payment methods are hardcoded text** in `core/texts.py` — swap in your
  real Telebirr/CBE numbers there.

## 8. Next steps (future, not in this MVP)

- Telegram Mini App for a nicer number-picking UI (services are already
  written transport-agnostic so a future REST layer can reuse them).
- Automatic payment verification (Telebirr/bank API or SMS parsing).
- `/history` and `/export` admin commands, multi-group support.

## 9. New features & admin commands (added)

This project includes additional admin and UX improvements since the MVP:

- Selection toggle: tapping a number in the group toggles selection for the tapping user. Tap once to reserve (pending, yellow), tap again to cancel (deselect).
- Multiple selections: a single user may reserve multiple different numbers. The bot aggregates awaiting payments and DMs the user a single summary (numbers + total).
- Reservation TTL: pending reservations auto-expire after `RESERVATION_TTL_MINUTES` (default 20). Set via env var in your `.env`.
- Display names: the system stores and displays Telegram `display_name` when available for clearer admin messages.

Admin management (DB-backed):

- `/addadmin <telegram_id>` — add an admin persisted in the DB
- `/deladmin <telegram_id>` — remove admin from DB
- `/listadmins` — list admins (includes env-configured IDs)

Round management commands:

- `/listrounds` — list all rounds in the chat (number, status, created_at)
- `/showround <round_number>` — print detailed list of numbers, their status and owner
- `/deleteround <round_number>` — delete a round and remove its board message
- `/resendboard <round_number>` — repost the board and update stored board message id (no extra confirmation message)
- `/assignnumber <round_number> <number> <telegram_id|@username> [display_name]` — admin force-assigns a number; updates the board to show it reserved

Other behaviour changes:

- After a draw, the bot posts a separate detailed results message (winners, prizes, seed/hash).
- All actions that change number state attempt to update the board message in the group immediately (selection, deselection, approval, rejection, manual assignment, resend, delete).

Refer to the `/help` and admin commands in the group for on-the-fly usage; check `core/routers/admin.py` for exact command formats.
