import asyncio
import hashlib
import random
import secrets

from core import config as core_config
from core.keyboards import build_number_grid
from core.texts import build_board_text, build_results_text, format_user_identity
from db import repository as repo
from aiogram.exceptions import TelegramBadRequest


async def commit_and_draw(round_doc, bot, chat_id):
    """Computes the draw result immediately using a committed random seed
    (so the outcome can never be influenced by the animation), then plays
    a short visual reveal in the group.

    NOTE (MVP limitation): the animation sleeps inside this single request
    for a few seconds. That's fine for a handful of frames on Vercel, but if
    you want longer/smoother animations later, move it to a Vercel Cron job
    that advances one frame per invocation (see the implementation plan).
    """
    eligible = [n for n in round_doc["numbers"] if n["status"] == "reserved"]
    prizes = round_doc["config"]["prizes"]

    if not eligible:
        return None, "ለማውጣት ምንም የተያዙ ቁጥሮች የሉም።"

    seed = secrets.token_hex(16)
    seed_hash = hashlib.sha256(seed.encode()).hexdigest()

    rng = random.Random(seed)
    winners = rng.sample(eligible, k=min(len(prizes), len(eligible)))

    results = []
    for i, w in enumerate(winners):
        results.append(
            {
                "place": i + 1,
                "number": w["number"],
                "telegram_id": w["telegram_id"],
                "username": w.get("username"),
                "display_name": w.get("display_name"),
                "prize": prizes[i] if i < len(prizes) else 0,
                "payout_account": None,
                "payout_status": "awaiting_details",
            }
        )

    await repo.set_round_status(round_doc["_id"], "drawing")
    await repo.set_draw_field(
        round_doc["_id"],
        seed=seed,
        seed_hash=seed_hash,
        status="revealed",
        results=results,
    )

    round_doc = await repo.get_round(round_doc["_id"])

    # Update the pinned board message itself so the drawn state is visible in-place.
    try:
        board_id = round_doc.get("message_refs", {}).get("board_message_id") if round_doc else None
        if round_doc and board_id:
            await bot.edit_message_text(build_board_text(round_doc), chat_id=chat_id, message_id=board_id)
            await bot.edit_message_reply_markup(chat_id=chat_id, message_id=board_id, reply_markup=build_number_grid(round_doc))
    except Exception:
        pass

    # 1) Publish the commitment BEFORE revealing anything, so anyone can
    #    later verify the result wasn't changed after the fact.
    await bot.send_message(
        chat_id,
        "🔒 የእጣ ማውጣት የseed hash (SHA-256):\n"
        f"<code>{seed_hash}</code>\n\n"
        "Seed ከዚህ በታች ከተገለጸ በኋላ ውጤቱን ማረጋገጥ ይቻላል።",
    )

    # 2) Cosmetic spinning animation. The real result is already decided
    #    and stored above — this is purely for visual transparency.
    all_numbers = [n["number"] for n in eligible]
    msg = await bot.send_message(chat_id, "🎲 እጣ በማውጣት ላይ...")
    for _ in range(6):
        await asyncio.sleep(0.6)
        fake = rng.choice(all_numbers)
        try:
            await bot.edit_message_text(
                f"🎲 እጣ በማውጣት ላይ... {fake:02d}", chat_id=chat_id, message_id=msg.message_id
            )
        except TelegramBadRequest:
            # Ignore "message is not modified" and similar transient edit errors
            pass

    # 3) Reveal results + the raw seed so the draw is auditable.
    def result_icon(place: int) -> str:
        return {1: "🥇", 2: "🥈", 3: "🥉"}.get(place, "🎖")

    lines = ["🏆 <b>ውጤቶች</b>", ""]
    for r in results:
        who = format_user_identity(r.get("display_name"), r.get("username"), r.get("telegram_id"))
        lines.append(f"{result_icon(r['place'])} ቁጥር {r['number']:02d} — {who} — {r['prize']} ETB")
    lines.append("")
    lines.append(f"Seed (እራስዎ ያረጋግጡ): <code>{seed}</code>")
    try:
        await bot.edit_message_text("\n".join(lines), chat_id=chat_id, message_id=msg.message_id)
    except TelegramBadRequest:
        pass

    await repo.set_round_status(round_doc["_id"], "awaiting_claims")
    # Send a separate detailed results message to the group
    try:
        send_kwargs = {}
        if core_config.RESULT_MESSAGE_EFFECT_ID:
            send_kwargs["message_effect_id"] = core_config.RESULT_MESSAGE_EFFECT_ID
        await bot.send_message(chat_id, build_results_text(round_doc, results), **send_kwargs)
    except Exception:
        try:
            await bot.send_message(chat_id, build_results_text(round_doc, results))
        except Exception:
            pass

    return results, None
