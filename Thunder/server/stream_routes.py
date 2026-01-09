# Thunder/bot/plugins/stream.py

import os
import asyncio
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message

from Thunder.bot import StreamBot
from Thunder.vars import Var
from Thunder.utils.logger import logger
from Thunder.utils.database import db
from Thunder.utils.tokens import generate_token


# ==============================
# START COMMAND
# ==============================

@StreamBot.on_message(filters.command("start") & filters.private)
async def start_handler(client: Client, message: Message):
    await db.add_user(message.from_user.id)
    await message.reply_text(
        "👋 Send me a file and I will generate a stream & download link."
    )


# ==============================
# FILE HANDLER
# ==============================

@StreamBot.on_message(filters.private & (filters.document | filters.video | filters.audio))
async def process_single(client: Client, message: Message):

    try:
        # generate token / hash
        token = generate_token(message.id)

        base_url = f"https://{Var.FQDN}" if Var.HAS_SSL else f"http://{Var.FQDN}"

        download_link = f"{base_url}/{token}{message.id}"
        stream_link = f"{base_url}/watch/{token}{message.id}"

        text = (
            "✨ **Your Links are Ready!** ✨\n\n"
            f"📥 **Download:**\n{download_link}\n\n"
            f"▶️ **Stream:**\n{stream_link}\n\n"
            "⏳ Links work while bot is running."
        )

        buttons = InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("⬇ Download", url=download_link)],
                [InlineKeyboardButton("▶ Stream", url=stream_link)],
            ]
        )

        # ==============================
        # SEND LINK TO USER
        # ==============================

        await message.reply_text(
            text=text,
            reply_markup=buttons,
            disable_web_page_preview=True
        )

        logger.info(f"Link sent for message_id={message.id}")

        # ==============================
        # 🔁 AUTO RESTART AFTER LINK
        # ==============================
        # This replaces manual /restart
        # Render / Railway will auto-restart process

        asyncio.get_event_loop().call_later(
            2, lambda: os._exit(0)
        )

    except Exception as e:
        logger.error(f"Error processing file: {e}", exc_info=True)
        await message.reply_text("❌ Failed to generate link. Please try again.")


# ==============================
# OPTIONAL: MANUAL RESTART CMD
# ==============================

@StreamBot.on_message(filters.command("restart") & filters.user(Var.OWNER_ID))
async def manual_restart(client: Client, message: Message):
    await message.reply_text("🔄 Restarting bot...")
    asyncio.get_event_loop().call_later(
        1, lambda: os._exit(0)
    )
