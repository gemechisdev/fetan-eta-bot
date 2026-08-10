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


def build_web_app() -> web.Application:
    """Builds the aiohttp app used by every non-Vercel deployment mode:
    aiogram's webhook handler + health/root/ping routes for uptime
    monitors and platforms that ping a service to keep it awake.

    Works identically whether it's launched via:
      - `python main.py` (aiohttp's own web.run_app)
      - a gunicorn aiohttp worker (`gunicorn -k aiohttp.GunicornWebWorker app:app`)
      - any other aiohttp-compatible runner
    """
    dp, bot = build_dispatcher()

    app = web.Application()
    app["bot"] = bot
    app["dp"] = dp

    app.router.add_get("/", health)
    app.router.add_get("/health", health)
    app.router.add_get("/ping", ping)

    SimpleRequestHandler(
        dispatcher=dp,
        bot=bot,
        secret_token=WEBHOOK_SECRET or None,
    ).register(app, path=WEBHOOK_PATH)

    setup_application(app, dp, bot=bot)

    app.on_startup.append(_on_startup)
    app.on_cleanup.append(_on_cleanup)

    return app
