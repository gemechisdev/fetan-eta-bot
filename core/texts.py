PAYMENT_INSTRUCTIONS = (
    "You selected number {number}.\n\n"
    "Price: {amount} ETB\n\n"
    "Pay to:\n"
    "Telebirr: 09xxxxxxxx\n"
    "CBE: 100xxxxxxxx\n\n"
    "After paying, send a screenshot of the payment OR type the transaction ID here."
)

PROOF_RECEIVED = (
    "Got it! Your payment proof for number {number} was sent for review. "
    "We'll confirm your number shortly."
)

CLAIM_RECEIVED = (
    "Thanks! Your payout details were sent to the admins. "
    "You'll get a confirmation once it's paid out."
)

NO_PENDING_ACTION = (
    "Nothing to do right now. Go to the group and tap a number to join the current round.\n\n"
    "Type /help if you're not sure how it works."
)

WELCOME = (
    "👋 Welcome to Fetan Eta!\n\n"
    "Join the lottery from the group by tapping a free number. "
    "I'll DM you here with payment instructions."
)

HELP = (
    "How it works:\n"
    "1. Tap a free number in the group.\n"
    "2. Pay, then send me the screenshot or transaction ID here.\n"
    "3. Wait for admin approval.\n"
    "4. Winners are drawn live in the group once registration closes.\n"
    "5. If you win, reply here with your payout account (Telebirr/CBE/bank)."
)


def build_board_text(round_doc) -> str:
    cfg = round_doc["config"]
    total = cfg["total_numbers"]
    left = sum(1 for n in round_doc["numbers"] if n["status"] == "available")
    prizes = cfg["prizes"]
    medals = ["🥇", "🥈", "🥉"]
    prize_lines = "\n".join(f"{medals[i]} {p} ETB" for i, p in enumerate(prizes))

    return (
        f"🎲 <b>FETAN ETA #{round_doc['round_number']}</b>\n\n"
        f"Ticket Price: {cfg['ticket_price']} ETB\n"
        f"Numbers Left: {left}/{total}\n\n"
        f"Prize Pool\n{prize_lines}\n\n"
        f"Choose your lucky number below 👇"
    )


def build_results_text(round_doc, results) -> str:
    medals = ["🥇", "🥈", "🥉"]
    lines = [f"🎉 <b>Results for FETAN ETA #{round_doc['round_number']}</b>", ""]
    for r in results:
        who = r.get("display_name") or (f"@{r.get('username')}" if r.get("username") else f"id:{r.get('telegram_id')}")
        lines.append(f"{medals[r['place'] - 1]} Place #{r['place']}: Number {r['number']:02d} — {who} — Prize: {r['prize']} ETB")
    lines.append("")
    lines.append("Draw details:")
    lines.append(f"Seed hash: {round_doc.get('draw', {}).get('seed_hash')}")
    lines.append(f"Seed: {round_doc.get('draw', {}).get('seed')}")
    return "\n".join(lines)
