# Thunder/bot/plugins/stream.py

import os
import asyncio

from pyrogram import Client, filters
from pyrogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    Message,
)

from Thunder.bot import StreamBot
from Thunder.vars import Var
from Thunder.utils.logger import logger
from Thunder.utils.database import db


# ==============================
# START COMMAND
# ==============================

@StreamBot.on_message(filters.command("start") & filters.private)
async def start_handler(client: Client, message: Message):
    await db.add_user(message.from_user.id)
    await message.reply_text(
        "👋 Send me a file and I will generate stream & download links."
    )


# ==============================
# FILE HANDLER (DOCUMENT / VIDEO / AUDIO)
# ==============================

@StreamBot.on_message(
    filters.private & (filters.document | filters.video | filters.audio)
)
async def process_single(client: Client, message: Message):

    try:
        # --------- GET FILE & UNIQUE HASH ----------
        if message.document:
            file = message.document
        elif message.video:
            file = message.video
        elif message.audio:
            file = message.audio
        else:
            return

        # Thunder server validates using file_unique_id[:6]
        secure_hash = file.file_unique_id[:6]

        # --------- BASE URL ----------
        base_url = (
            f"https://{Var.FQDN}"
            if Var.HAS_SSL
            else f"http://{Var.FQDN}"
        )

        download_link = f"{base_url}/{secure_hash}{message.id}"
        stream_link = f"{base_url}/watch/{secure_hash}{message.id}"

        # --------- MESSAGE TEXT ----------
        text = (
            "✨ **Your Links are Ready!** ✨\n\n"
            f"📥 **Download Link:**\n{download_link}\n\n"
            f"▶️ **Stream Link:**\n{stream_link}\n\n"
            "⏳ Links work while the bot is running."
        )

        buttons = InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("⬇ Download", url=download_link)],
                [InlineKeyboardButton("▶ Stream", url=stream_link)],
            ]
        )

        # --------- SEND LINK ----------
        await message.reply_text(
            text=text,
            reply_markup=buttons,
            disable_web_page_preview=True
        )

        logger.info(
            f"Link sent | msg_id={message.id} | hash={secure_hash}"
        )

        # ==============================
        # 🔁 AUTO RESTART AFTER LINK
        # ==============================
        # Replaces manual /restart
        # Render / Railway will auto-restart process

        asyncio.get_event_loop().call_later(
            2, lambda: os._exit(0)
        )

    except Exception as e:
        logger.error(
            f"Error processing file {message.id}: {e}",
            exc_info=True
        )
        await message.reply_text(
            "❌ Failed to generate link. Please try again."
        )


# ==============================
# MANUAL RESTART (OPTIONAL)
# ==============================

@StreamBot.on_message(filters.command("restart") & filters.user(Var.OWNER_ID))
async def manual_restart(client: Client, message: Message):
    await message.reply_text("🔄 Restarting bot...")
    asyncio.get_event_loop().call_later(
        1, lambda: os._exit(0)
    )
