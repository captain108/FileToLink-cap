# Thunder/server/stream_routes.py

import re
import time
from urllib.parse import unquote

from aiohttp import web

from Thunder import __version__, StartTime
from Thunder.bot import StreamBot, multi_clients, work_loads
from Thunder.server.exceptions import InvalidHash, FileNotFound
from Thunder.utils.custom_dl import ByteStreamer
from Thunder.utils.logger import logger
from Thunder.utils.render_template import render_page
from Thunder.utils.time_format import get_readable_time

routes = web.RouteTableDef()

SECURE_HASH_LENGTH = 6
PATTERN_HASH_FIRST = re.compile(
    rf"^([a-zA-Z0-9_-]{{{SECURE_HASH_LENGTH}}})(\d+)(?:/.*)?$")
PATTERN_ID_FIRST = re.compile(r"^(\d+)(?:/.*)?$")
VALID_HASH_REGEX = re.compile(r'^[a-zA-Z0-9_-]+$')

streamers = {}


# ---------------- HELPERS ----------------

def get_streamer(client_id: int) -> ByteStreamer:
    if client_id not in streamers:
        streamers[client_id] = ByteStreamer(multi_clients[client_id])
    return streamers[client_id]


def select_optimal_client() -> tuple[int, ByteStreamer]:
    if not work_loads:
        raise web.HTTPInternalServerError(text="No clients available")
    client_id = min(work_loads, key=work_loads.get)
    return client_id, get_streamer(client_id)


def parse_media_request(path: str, query: dict) -> tuple[int, str]:
    clean = unquote(path).strip("/")

    m = PATTERN_HASH_FIRST.match(clean)
    if m:
        mid = int(m.group(2))
        h = m.group(1)
        if VALID_HASH_REGEX.match(h):
            return mid, h

    m = PATTERN_ID_FIRST.match(clean)
    if m:
        mid = int(m.group(1))
        h = query.get("hash", "").strip()
        if VALID_HASH_REGEX.match(h):
            return mid, h

    raise InvalidHash("Invalid link")


# ---------------- BASIC ROUTES ----------------

@routes.get("/")
async def root_redirect(request):
    raise web.HTTPFound("https://github.com/fyaz05/FileToLink")


@routes.get("/status")
async def status_endpoint(request):
    return web.json_response({
        "server": {
            "status": "ok",
            "version": __version__,
            "uptime": get_readable_time(time.time() - StartTime)
        },
        "bot": {
            "username": f"@{StreamBot.username}",
            "clients": len(multi_clients)
        }
    })


# ---------------- WATCH PAGE (HTML) ----------------

@routes.get(r"/watch/{path:.+}")
async def media_preview(request: web.Request):
    try:
        path = request.match_info["path"]
        message_id, secure_hash = parse_media_request(path, request.query)

        html = await render_page(
            message_id, secure_hash, requested_action="stream"
        )

        return web.Response(
            text=html,
            content_type="text/html",
            headers={"Access-Control-Allow-Origin": "*"}
        )
    except Exception:
        raise web.HTTPNotFound(text="Invalid or expired link")


# ---------------- CDN REDIRECT (DOWNLOAD + STREAM) ----------------

@routes.get(r"/{path:.+}")
async def media_delivery(request: web.Request):
    try:
        path = request.match_info["path"]
        message_id, secure_hash = parse_media_request(path, request.query)

        client_id, streamer = select_optimal_client()

        # Ensure client is connected (no restart needed)
        if not streamer.client.is_connected:
            await streamer.client.start()

        file_info = await streamer.get_file_info(message_id)
        if not file_info:
            raise FileNotFound("File not found")

        # 🔥 Telegram CDN URL (fresh every request)
        tg_url = (
            file_info.get("file_url")
            or file_info.get("telegram_file_url")
        )

        if not tg_url:
            raise FileNotFound("Telegram CDN URL not available")

        # 🔁 Redirect browser to Telegram CDN
        raise web.HTTPFound(tg_url)

    except (InvalidHash, FileNotFound):
        raise web.HTTPNotFound(text="Invalid or expired link")
    except Exception as e:
        logger.error(f"CDN redirect error: {e}", exc_info=True)
        raise web.HTTPInternalServerError(text="Server error")
