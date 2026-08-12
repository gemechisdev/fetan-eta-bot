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
2. Tap a number in the group:
   - **Available (⚪)** → your own private chat with the bot opens
     automatically (works whether or not you'd started the bot before) and
     shows payment instructions right there.
   - **Pending (🟡) / Reserved (🟢)** → you just get a quick in-group alert
     saying who has it — no DM opens, since there's nothing to do there.
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

### G) Koyeb / other free web services (keep-alive tips)

When running on a free web service that may sleep inactive containers (like
Koyeb free web service), expose the `/.`, `/health`, `/ping`, and `/wake`
endpoints so an external uptime monitor can both check and "wake" the bot.

Important notes:

- Ensure `RUN_MODE=webhook`, `PORT`, and `PUBLIC_URL` are set in your Koyeb
  deployment env. `PUBLIC_URL` must be the public URL Koyeb assigns your
  service (e.g. `https://my-service.koyeb.app`).
- If your platform doesn't allow automatic webhook registration on startup,
  use the `POST /register_webhook` endpoint to register it once (protected
  by `WEBHOOK_SECRET`).

Quick examples (replace placeholders):

```bash
# Wake the service (ping + ensure bot client session is active)
curl -fsS https://your-app.koyeb.app/wake

# Register webhook (call once after deploy). Use WEBHOOK_SECRET if set.
curl -X POST "https://your-app.koyeb.app/register_webhook?secret=$WEBHOOK_SECRET"

# Health check (works for Koyeb's health probes)
curl -fsS https://your-app.koyeb.app/health
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

| Command / alias              | Purpose                                                   |
| ---------------------------- | --------------------------------------------------------- |
| `/newround` / `/nr`          | Start a round with dynamic prizes                         |
| `/closeregistration` / `/cr` | Lock number selection, prepare for draw                   |
| `/startdraw` / `/sd`         | Run the provably-fair draw + animation                    |
| `/pending` / `/pd`           | List payments awaiting review with Approve/Reject buttons |
| `/cancelround` / `/cancel`   | Void the current round (also cancels its open payments)   |
| `/listrounds` / `/rounds`    | List all rounds in the target chat                        |
| `/showround` / `/round`      | Show round details and owners                             |
| `/deleteround` / `/delround` | Delete a round and its stored board message                |
| `/resendboard` / `/board`    | Repost the board and refresh the stored board message id  |
| `/assignnumber` / `/assign`  | Force-assign a number to a user                           |
| `/revoke` / `/rv`            | Opposite of `/assignnumber` — force-release a number back to available |
| `/payout` / `/paid`          | Mark a winner's prize as paid                             |
| `/addadmin` / `/aadmin`      | Add a DB-backed admin                                     |
| `/deladmin` / `/dadmin`      | Remove a DB-backed admin                                  |
| `/listadmins` / `/admins`    | List admins                                               |
| `/chat` / `/msg`             | Send a text/media reply to a user                         |

When you run a round command from private chat, append the target `chat_id` at the end, for example:

```bash
/payout 1 7708711658 -1001234567890
/showround 1 -1001234567890
/assignnumber 1 34 7708711658 -1001234567890
/revoke 1 34 -1001234567890
```

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
core/texts.py             all user-facing strings + board/results text builders
core/deeplink.py          encode/decode payload for the per-tap, per-user reservation deep link
core/routers/
  common.py                 /start (incl. deep-link reservation handoff) /help
  admin.py                  round management, verification, payouts, revoke
  selection.py               number tap handling (group) — always opens the tapper's own DM
  private.py                 payment proof + payout claim (private chat, no FSM)

db/client.py              Mongo connection singleton (tz-aware, see note below)
db/repository.py          every Mongo query lives here, nowhere else
services/round_service.py     round/number/payment business logic + board refresh helper
services/reservation_flow.py  shared "reserve number + DM payer" flow, called from the
                                private /start handler once a user lands in their own DM
services/draw_service.py       provably-fair draw + animation
```

> Note: the internal package was renamed from `bot/` to `core/`. A
> top-level `bot.py` file and a `bot/` package can't coexist in the same
> directory in Python — this rename is what makes `bot.py` safely
> available as an entrypoint alongside `main.py` and `app.py`.

## 7. Known MVP limitations (intentional — for the next iteration)

- **Pending reservations auto-expire.** Pending numbers are released after
  `RESERVATION_TTL_MINUTES` (default 20) — configurable via your `.env`.
  Expiry also cancels the matching payment record so it can't resurface later.
- **A bot still can't force-open a DM out of thin air.** Telegram doesn't
  allow that for any bot. What we do instead: every tap on a group number
  button routes through `answerCallbackQuery`'s `url` field pointing at a
  `t.me/<bot>?start=...` deep link — Telegram treats this as "open this
  user's own chat with the bot", so it opens (or starts) *their* private
  chat with the number embedded, in the same tap. It's exclusive by
  construction (the link opens in the tapper's own client) and additionally
  carries their user id so `/start` refuses to act on it for anyone else.
- **Draw animation runs synchronously** inside the request/loop (a few
  seconds of `asyncio.sleep`). Fine for a handful of frames; for longer or
  smoother animations, move it to a periodic job that advances one frame
  per tick (works the same in webhook or polling mode).
- **Single active round per group** — starting a new round is blocked until
  the current one reaches `completed` or `cancelled`.
- **No `users` collection yet** — user info is stored inline on
  payments/rounds. Fine for MVP; worth normalizing once you add
  stats/history features.
- **Payment methods are hardcoded text** in `core/texts.py` and
  `services/round_service.py` (`PAY_INSTRUCTIONS_FOOTER`) — swap in your
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
- Reservation TTL: pending reservations auto-expire after `RESERVATION_TTL_MINUTES` (default 20). Set via env var in your `.env`. Expiry now also cancels the associated payment record (see fixes below).
- Display names: the system stores and displays Telegram `display_name` when available for clearer admin messages.
- **One-tap DM handoff for available numbers only**: tapping a free (⚪)
  number in the group opens the tapper's own private chat with the bot via a
  per-tap, per-user deep link (`core/deeplink.py`,
  `answerCallbackQuery(url=...)` in `core/routers/selection.py`) and shows
  payment instructions right there. Tapping a pending (🟡) or already
  reserved (🟢) number just shows a quick in-group alert with who has it —
  no DM opens, since there's nothing actionable to show there. The deep link
  embeds the tapping user's id, so `/start` in `core/routers/common.py`
  refuses to act on a link that isn't theirs. Deselecting your *own* pending
  number still happens instantly in-group.
- **Message effect on win DMs**: the "🎉 You won ..." private message sent to each winner after `/startdraw` now carries the same festive Telegram message effect (`RESULT_MESSAGE_EFFECT_ID`) used on the group results message — effects only render in private chats, so this is where it actually shows.
- **Redesigned results announcement**: the post-draw results message in the group is now a stylized box with round number, medal/number/prize lines (right-aligned), and the seed hash/seed for verification, prefixed with 🎊. See `core/texts.build_results_text`.
- **`/revoke` / `/rv`**: the opposite of `/assignnumber` — force-releases a number back to available, cancels any open payment tied to it, updates the board, and DMs the previous holder that their reservation was revoked.

Recent fixes & improvements

- **Fixed pending reservations never actually expiring.** `db/client.py`'s Mongo client wasn't `tz_aware`, so dates written as timezone-aware (`utcnow()`) came back from MongoDB as naive datetimes on read. Comparing the two in `expire_pending_reservations()` raised `can't compare offset-naive and offset-aware datetimes`, which every caller silently swallowed — so pending numbers never actually returned to available after `RESERVATION_TTL_MINUTES`, no matter how long they sat there. Fixed by making the client `tz_aware=True` (UTC). Expiry is also now checked from more places (`/pending`, `/showround`, every number tap, every `/start`) so views stay fresh, and failures are logged instead of silently swallowed.
- **`/revoke` now verifies and works uniformly on pending and reserved numbers.** It force-releases the number, cancels any lingering payment regardless of status (awaiting proof/review, or even already-approved), then re-reads the round to confirm the number actually ended up available before telling the admin it worked — if it didn't, you get a clear warning instead of a false "done".
- **Fixed a payment-mixing bug**: submitting a transaction ID/screenshot could sometimes get bundled with a stale payment for a *different* number the user never actually selected in the current round (e.g. an old expired/cancelled reservation), causing it to be silently approved alongside the real one. Root cause and fix:
  - `expire_pending_reservations()` now also expires the matching payment record instead of leaving it stuck at `awaiting_proof` forever.
  - `/cancelround` and `/deleteround` now cancel all open payments for that round (`repo.cancel_round_payments`).
  - `get_awaiting_proof_payments_for_user()` (used when matching a submitted proof to the payer's pending payments) is now scoped to rounds that are still active, so a payment from a cancelled/deleted/completed round can no longer resurface in a later, unrelated submission.
- Fixed incorrect board highlighting: updates to number state use MongoDB `arrayFilters` to target the exact `number` element (prevents earlier cases where reservations showed up on the first N buttons instead of the intended numbers).
- Stable keyboard ordering: the number grid is now built from a numerically-sorted `numbers` list, protecting against DB array reorders.
- Batch payment proofs: users with multiple pending numbers can submit one proof (photo/text) and the bot attaches it to all pending payments; admins receive a consolidated review message and can Approve All / Reject All.
- Admin `/chat` command: `/chat <telegram_id> <text>` sends text to a user; replying to a message and running `/chat <telegram_id>` will forward/copy that replied message (supports media).
- Admin notifications: the bot fetches admins from the DB plus env-configured IDs to ensure all admins are notified.
- Board update target: board edits prefer the stored board message id (so the canonical board is updated for everyone), rather than editing the callback-originating message.
- Debug helpers: lightweight debug prints (`[DB DEBUG]` / `[DEBUG]`) remain in `db/repository.py` and `core/routers/selection.py` to help troubleshoot number state during development — safe to strip once you're past testing.

Admin management (DB-backed):

- `/addadmin <telegram_id>` — add an admin persisted in the DB
- `/deladmin <telegram_id>` — remove admin from DB
- `/listadmins` — list admins (includes env-configured IDs)

Round management commands:

- `/listrounds` — list all rounds in the chat (number, status, created_at)
- `/showround <round_number>` — print detailed list of numbers, their status and owner
- `/deleteround <round_number>` — delete a round, cancel its open payments, and remove its board message
- `/resendboard <round_number>` — repost the board and update stored board message id (no extra confirmation message)
- `/assignnumber <round_number> <number> <telegram_id|@username> [display_name]` — admin force-assigns a number; updates the board to show it reserved
- `/revoke <round_number> <number>` — admin force-releases a number back to available; updates the board and notifies the previous holder

Other behaviour changes:

- After a draw, the bot posts a separate, stylized results message (winners, prizes, seed/hash) with the message effect applied, then DMs each winner individually (also with the effect).
- All actions that change number state attempt to update the board message in the group immediately (selection, deselection, approval, rejection, manual assignment, revoke, resend, delete).

Refer to the `/help` and admin commands in the group for on-the-fly usage; check `core/routers/admin.py` for exact command formats.
