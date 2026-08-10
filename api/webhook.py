import asyncio
import json
from http.server import BaseHTTPRequestHandler

from aiogram.types import Update

from core.config import WEBHOOK_SECRET
from core.dispatcher import build_dispatcher


async def process_update(payload: dict):
    dp, bot = build_dispatcher()
    update = Update.model_validate(payload)
    await dp.feed_update(bot, update)


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        secret = self.headers.get("X-Telegram-Bot-Api-Secret-Token")
        if WEBHOOK_SECRET and secret != WEBHOOK_SECRET:
            self.send_response(401)
            self.end_headers()
            return

        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length else b"{}"

        try:
            payload = json.loads(body)
            asyncio.run(process_update(payload))
        except Exception as e:  # noqa: BLE001 - log and still ack Telegram
            print(f"Error processing update: {e}")

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"ok": true}')

    def do_GET(self):
        # simple health check, e.g. GET https://your-app.vercel.app/api/webhook
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"status": "alive"}')
