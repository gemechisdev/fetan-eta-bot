PAYMENT_INSTRUCTIONS = (
    "ቁጥር {number}ን መርጠዋል።\n\n"
    "ዋጋ፦ {amount} ብር\n\n"
    "ክፍያ የሚፈጽሙበት፦\n"
    "Telebirr፦ 09xxxxxxxx\n"
    "CBE፦ 100xxxxxxxx\n\n"
    "ክፍያውን ከፈጸሙ በኋላ የክፍያውን ስክሪንሾት ይላኩ ወይም የግብይት መለያ ቁጥሩን (Transaction ID) እዚህ ይጻፉ።"
)

PROOF_RECEIVED = (
    "ተቀብለናል! ለቁጥር {number} የላኩት የክፍያ ማረጋገጫ ለግምገማ ተልኳል። "
    "ቁጥርዎን በቅርቡ እናረጋግጣለን።"
)

CLAIM_RECEIVED = (
    "እናመሰግናለን! የሽልማት መቀበያ መረጃዎ ለአስተዳዳሪዎች ተልኳል። "
    "ክፍያው ከተፈጸመ በኋላ የማረጋገጫ መልዕክት ይደርስዎታል።"
)

NO_PENDING_ACTION = (
    "በአሁኑ ጊዜ ምንም የሚያደርጉት ነገር የለም። ወደ ግሩፑ በመሄድ በአሁኑ ዙር ለመሳተፍ ከነጻ ቁጥሮች አንዱን ይንኩ።\n\n"
    "አሰራሩ ግልጽ ካልሆነዎት /help ይጻፉ።"
)

WELCOME = (
    "👋 ወደ Fetan Eta(ፈጣን ዕጣ) እንኳን በደህና መጡ!\n\n"
    "ከግሩፑ ውስጥ ነጻ ቁጥርን በመንካት በሎተሪው ይሳተፉ። "
    "የክፍያ መመሪያዎችን እዚህ በግል መልዕክት እልክልዎታለሁ።"
)

HELP = (
    "እንዴት ይሰራል?\n"
    "1. በግሩፑ ውስጥ ካሉት ነጻ ቁጥሮች አንዱን ይንኩ።\n"
    "2. ክፍያ ይፈጽሙ፣ ከዚያም የክፍያውን ስክሪንሾት ወይም የግብይት መለያ ቁጥሩን እዚህ ይላኩ።\n"
    "3. የአስተዳዳሪውን ማጽደቅ ይጠብቁ።\n"
    "4. ምዝገባው ከተዘጋ በኋላ አሸናፊዎች በግሩፑ ውስጥ በቀጥታ ይለያሉ።\n"
    "5. ካሸነፉ የሽልማት መቀበያ ሂሳብዎን (Telebirr/CBE/ባንክ) ይላኩ።"
)


def build_board_text(round_doc) -> str:
    cfg = round_doc["config"]
    total = cfg["total_numbers"]
    left = sum(1 for n in round_doc["numbers"] if n["status"] == "available")
    prizes = cfg["prizes"]
    results = round_doc.get("draw", {}).get("results", [])

    def prize_icon(index: int) -> str:
        return {0: "🥇", 1: "🥈", 2: "🥉"}.get(index, "🎖")

    prize_lines = "\n".join(f"{prize_icon(i)} {p} ብር" for i, p in enumerate(prizes))

    lines = [
        f"🎲 <b>FETAN ETA #{round_doc['round_number']}</b>",
        "",
        f"የቲኬት ዋጋ፦ {cfg['ticket_price']} ብር",
        f"የቀሩ ቁጥሮች፦ {left}/{total}",
        "",
        f"የሽልማት ገንዘብ\n{prize_lines}",
    ]

    if results:
        lines.extend([
            "",
            "<b>የተለዩ አሸናፊዎች</b>",
        ])
        for r in results:
            lines.append(
                f"{prize_icon(r['place'] - 1)} ደረጃ #{r['place']}፦ ቁጥር {r['number']:02d} — {format_user_identity(r.get('display_name'), r.get('username'), r.get('telegram_id'))} — {r['prize']} ብር"
            )
        if round_doc.get("draw", {}).get("seed_hash"):
            lines.extend([
                "",
                f"የSeed Hash፦ {round_doc['draw']['seed_hash']}",
            ])

    lines.extend(["", "ከታች የሚገኘውን የእድል ቁጥርዎን ይምረጡ 👇"])

    return "\n".join(lines)


_BOLD_SANS_DIGIT_BASE = 0x1D7EC  # Mathematical Sans-Serif Bold Digit Zero


def _bold_digits(n: int) -> str:
    """Convert an integer to Mathematical Sans-Serif Bold digits (𝟬-𝟵), to
    match the stylized 'ROUND #𝟭' heading used in the results announcement."""
    return "".join(chr(_BOLD_SANS_DIGIT_BASE + int(d)) for d in str(n))


def build_results_text(round_doc, results) -> str:
    def result_icon(place: int) -> str:
        return {1: "🥇", 2: "🥈", 3: "🥉"}.get(place, "🎖")

    prize_strs = [f"{r['prize']:,}" for r in results]
    width = max((len(p) for p in prize_strs), default=0)

    result_lines = []
    for r, prize_str in zip(results, prize_strs):
        pad = " " * (width - len(prize_str))
        result_lines.append(
            f"┣ {result_icon(r['place'])} #{r['number']:02d} ➜ {pad}{prize_str} ብር"
        )

    draw = round_doc.get("draw", {})
    lines = [
        "╔═══━━━━━∙•∙◦❉◦∙•∙━━━━━═══╗",
        f"┣   🎉 𝗙𝗘𝗧𝗔𝗡 𝗘𝗧𝗔 — 𝗥𝗢𝗨𝗡𝗗 #{_bold_digits(round_doc['round_number'])}",
        "┣━━━━━━━━━━━━━━━━━━━━━",
        *result_lines,
        "┣━━━━━━━━━━━━━━━━━━━━━",
        f"┣ 🔐 Hash ➜ <code>{draw.get('seed_hash')}</code>",
        f"┣ 🔑 Seed ➜ <code>{draw.get('seed')}</code>",
        "╚═══━━━━━∙•∙◦❉◦∙•∙━━━━━═══╝",
    ]
    return "\n".join(lines)


def format_user_identity(display_name: str | None, username: str | None, telegram_id: int | None) -> str:
    """Return a standardized string: Display Name - @username - id
    Use 'None' for missing username and '-' for missing display name."""
    disp = display_name if display_name else "-"
    userpart = f"@{username}" if username else "None"
    idpart = str(telegram_id) if telegram_id else "None"
    return f"{disp} - {userpart} - {idpart}"
