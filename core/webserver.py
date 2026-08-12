import logging

from aiohttp import web
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

from core.config import PUBLIC_URL, WEBHOOK_PATH, WEBHOOK_SECRET
from core.dispatcher import build_dispatcher

logger = logging.getLogger("fetan-eta.webserver")


async def health(request: web.Request) -> web.Response:
    return web.json_response({"status": "ok", "service": "fetan-eta-bot"})


async def ping(request: web.Request) -> web.Response:
    return web.json_response({"pong": True})


async def _on_startup(app: web.Application):
    bot = app["bot"]
    if PUBLIC_URL:
        webhook_url = PUBLIC_URL.rstrip("/") + WEBHOOK_PATH
        await bot.set_webhook(
            url=webhook_url,
            secret_token=WEBHOOK_SECRET or None,
            drop_pending_updates=True,
        )
        logger.info(f"Webhook registered at {webhook_url}")
    else:
        logger.warning(
            "PUBLIC_URL is not set - the webhook was NOT auto-registered. "
            "Set PUBLIC_URL to this deployment's public base URL, or run "
            "set_webhook.py manually once you know it."
        )


async def _on_cleanup(app: web.Application):
    bot = app["bot"]
    await bot.session.close()


def build_web_app(dp=None, bot=None) -> web.Application:
    """Builds the aiohttp app used by every non-Vercel deployment target:
    aiogram's webhook handler + health/root/ping routes for uptime
    monitors and platforms that ping a service to keep it awake.

    Works identically whether it's launched via:
      - `python main.py` (aiohttp's own web.run_app)
      - a gunicorn aiohttp worker (`gunicorn -k aiohttp.GunicornWebWorker app:app`)
      - any other aiohttp-compatible runner
    """
    # Allow callers to provide an existing dispatcher and bot (useful for
    # polling mode where the dispatcher is already running). If not
    # provided, build them here (webhook mode).
    if dp is None or bot is None:
        dp, bot = build_dispatcher()

    app = web.Application()
    app["bot"] = bot
    app["dp"] = dp

    app.router.add_get("/", health)
    app.router.add_get("/health", health)
    app.router.add_get("/ping", ping)
    # Lightweight wake endpoint: triggers an API call to Telegram to ensure
    # the bot's client session is active. Useful for uptime pings that also
    # need the bot process to become ready.
    async def wake(request: web.Request) -> web.Response:
        bot = request.app.get("bot")
        try:
            await bot.get_me()
            return web.json_response({"woke": True})
        except Exception as e:
            return web.json_response({"woke": False, "error": str(e)}, status=500)

    app.router.add_get("/wake", wake)

    # Register webhook on-demand (idempotent). Protect this endpoint with
    # the same WEBHOOK_SECRET used for incoming webhook validation. Call
    # it once (or from a CI step) after deployment if automatic startup
    # registration isn't possible.
    async def register_webhook(request: web.Request) -> web.Response:
        bot = request.app.get("bot")
        # Accept secret either as query param or X-Webhook-Secret header
        provided = request.query.get("secret") or request.headers.get("X-Webhook-Secret")
        if WEBHOOK_SECRET and provided != WEBHOOK_SECRET:
            return web.json_response({"error": "invalid secret"}, status=403)
        if not PUBLIC_URL:
            return web.json_response({"error": "PUBLIC_URL not configured"}, status=400)
        webhook_url = PUBLIC_URL.rstrip("/") + WEBHOOK_PATH
        try:
            await bot.set_webhook(url=webhook_url, secret_token=WEBHOOK_SECRET or None, drop_pending_updates=True)
            return web.json_response({"ok": True, "webhook": webhook_url})
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=500)

    app.router.add_post("/register_webhook", register_webhook)

    SimpleRequestHandler(
        dispatcher=dp,
        bot=bot,
        secret_token=WEBHOOK_SECRET or None,
    ).register(app, path=WEBHOOK_PATH)

    setup_application(app, dp, bot=bot)

    app.on_startup.append(_on_startup)
    app.on_cleanup.append(_on_cleanup)

    return app
