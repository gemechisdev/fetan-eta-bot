from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

STATUS_EMOJI = {
    "available": "⚪",
    "pending": "🟡",
    "reserved": "🟢",
}


def build_number_grid(round_doc) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    round_number = round_doc["round_number"]
    winner_numbers = {r["number"] for r in round_doc.get("draw", {}).get("results", [])}

    # Ensure stable numeric ordering for the grid (protect against DB array reorders)
    for n in sorted(round_doc["numbers"], key=lambda x: x["number"]):
        if n["number"] in winner_numbers:
            emoji = "🏆"
        else:
            emoji = STATUS_EMOJI.get(n.get("status"), "⚪")
        label = f"{n['number']:02d}{emoji}"
        builder.button(text=label, callback_data=f"num:{round_number}:{n['number']}")

    builder.adjust(4)
    return builder.as_markup()


def build_start_and_reserve_kb(bot_username: str, payload: str, number: int) -> InlineKeyboardMarkup:
    """One-tap 'open my DMs and grab this number' button for users who
    haven't started a private chat with the bot yet."""
    builder = InlineKeyboardBuilder()
    builder.button(
        text=f"🚀 Start bot & reserve {number:02d}",
        url=f"https://t.me/{bot_username}?start={payload}",
    )
    return builder.as_markup()


def build_review_kb(payment_id: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Approve", callback_data=f"rev:approve:{payment_id}")
    builder.button(text="❌ Reject", callback_data=f"rev:reject:{payment_id}")
    builder.adjust(2)
    return builder.as_markup()


def build_review_kb_multi(payment_ids: list[str]) -> InlineKeyboardMarkup:
    """Build a review keyboard for multiple payments at once.

    Provides Approve All / Reject All actions where the payment ids are joined by commas.
    """
    joined = ",".join(payment_ids)
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Approve All", callback_data=f"rev:approve:{joined}")
    builder.button(text="❌ Reject All", callback_data=f"rev:reject:{joined}")
    builder.adjust(2)
    return builder.as_markup()
