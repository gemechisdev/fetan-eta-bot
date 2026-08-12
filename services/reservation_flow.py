"""Shared "reserve a number + DM the payer" flow.

Used from two entry points:
  * core/routers/selection.py  - user taps a free number in the group
  * core/routers/common.py     - user opens the bot via a start-and-reserve
                                  deep link (core/deeplink.py)

Keeping this logic in one place means both entry points build the exact same
DM (numbers list + total) and both roll back the same way if the DM can't be
delivered, instead of two copies quietly drifting apart.
"""

from aiogram import Bot

from db import repository as repo
from services import round_service


async def reserve_number_and_notify(bot: Bot, round_doc: dict, number: int, user) -> dict:
    """Attempt to reserve `number` in `round_doc` for `user`, then DM them
    payment instructions.

    Returns one of:
      {"status": "reserved"}
      {"status": "taken", "message": str}       # couldn't reserve (race/closed/invalid)
      {"status": "dm_failed"}                   # reserved, but DM bounced; rolled back
    """
    display_name = f"{user.first_name or ''} {user.last_name or ''}".strip()

    payment, error = await round_service.select_number(
        round_doc, number, user.id, user.username, display_name=display_name
    )
    if error:
        return {"status": "taken", "message": error}

    try:
        dm_text = await round_service.build_reservation_summary_text(round_doc["_id"], user.id)
        await bot.send_message(user.id, dm_text)
    except Exception:
        # User can't be DMed yet (hasn't started the bot). Roll back the
        # reservation instead of holding the number hostage until it expires.
        await round_service.cancel_selection(round_doc, number)
        try:
            await repo.release_number(round_doc["_id"], number)
        except Exception:
            pass
        return {"status": "dm_failed"}

    return {"status": "reserved"}
