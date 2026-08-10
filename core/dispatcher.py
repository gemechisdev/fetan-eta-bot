from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from core.config import BOT_TOKEN
from core.routers import admin, common, private, selection

_bot = None
_dp = None


def build_dispatcher():
    """Memoized so warm serverless invocations reuse the same Bot/Dispatcher
    instead of rebuilding routers and reconnecting on every request."""
    global _bot, _dp

    if _bot is None:
        _bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))

    if _dp is None:
        _dp = Dispatcher()
        # Order matters: specific routers first, the private-chat catch-all last.
        _dp.include_router(common.router)
        _dp.include_router(admin.router)
        _dp.include_router(selection.router)
        _dp.include_router(private.router)

    return _dp, _bot
