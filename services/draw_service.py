import asyncio
import hashlib
import random
import secrets

from db import repository as repo
from aiogram.exceptions import TelegramBadRequest
from core.texts import build_results_text, format_user_identity


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
        return None, "No reserved numbers to draw from."

    seed = secrets.token_hex(16)
    seed_hash = hashlib.sha256(seed.encode()).hexdigest()

    rng = random.Random(seed)
    winners = rng.sample(eligible, k=min(3, len(eligible)))

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

    # 1) Publish the commitment BEFORE revealing anything, so anyone can
    #    later verify the result wasn't changed after the fact.
    await bot.send_message(
        chat_id,
        "🔒 Draw seed commitment (SHA-256):\n"
        f"<code>{seed_hash}</code>\n\n"
        "This will be verifiable once the seed is revealed below.",
    )

    # 2) Cosmetic spinning animation. The real result is already decided
    #    and stored above — this is purely for visual transparency.
    all_numbers = [n["number"] for n in eligible]
    msg = await bot.send_message(chat_id, "🎲 Drawing...")
    for _ in range(6):
        await asyncio.sleep(0.6)
        fake = rng.choice(all_numbers)
        try:
            await bot.edit_message_text(
                f"🎲 Drawing... {fake:02d}", chat_id=chat_id, message_id=msg.message_id
            )
        except TelegramBadRequest:
            # Ignore "message is not modified" and similar transient edit errors
            pass

    # 3) Reveal results + the raw seed so the draw is auditable.
    medals = ["🥇", "🥈", "🥉"]
    lines = ["🏆 <b>Results</b>", ""]
    for r in results:
        who = format_user_identity(r.get("display_name"), r.get("username"), r.get("telegram_id"))
        lines.append(f"{medals[r['place'] - 1]} Number {r['number']:02d} — {who} — {r['prize']} ETB")
    lines.append("")
    lines.append(f"Seed (verify it yourself): <code>{seed}</code>")
    try:
        await bot.edit_message_text("\n".join(lines), chat_id=chat_id, message_id=msg.message_id)
    except TelegramBadRequest:
        pass

    await repo.set_round_status(round_doc["_id"], "awaiting_claims")
    # Send a separate detailed results message to the group
    try:
        await bot.send_message(chat_id, build_results_text(round_doc, results))
    except Exception:
        pass

    return results, None
