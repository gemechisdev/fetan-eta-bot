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

    for n in round_doc["numbers"]:
        if n["number"] in winner_numbers:
            emoji = "🏆"
        else:
            emoji = STATUS_EMOJI.get(n["status"], "⚪")
        label = f"{n['number']:02d}{emoji}"
        builder.button(text=label, callback_data=f"num:{round_number}:{n['number']}")

    builder.adjust(4)
    return builder.as_markup()


def build_review_kb(payment_id: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Approve", callback_data=f"rev:approve:{payment_id}")
    builder.button(text="❌ Reject", callback_data=f"rev:reject:{payment_id}")
    builder.adjust(2)
    return builder.as_markup()
