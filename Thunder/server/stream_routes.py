
# Thunder/server/stream_routes.py

import re
import secrets
import time
from urllib.parse import quote, unquote

from aiohttp import web

from Thunder import __version__, StartTime
from Thunder.bot import StreamBot, multi_clients, work_loads
from Thunder.server.exceptions import FileNotFound, InvalidHash
from Thunder.utils.custom_dl import ByteStreamer
from Thunder.utils.logger import logger
from Thunder.utils.render_template import render_page
from Thunder.utils.time_format import get_readable_time

routes = web.RouteTableDef()

SECURE_HASH_LENGTH = 6
CHUNK_SIZE = 1024 * 1024
MAX_CONCURRENT_PER_CLIENT = 8
RANGE_REGEX = re.compile(r"bytes=(?P<start>\d*)-(?P<end>\d*)")
PATTERN_HASH_FIRST = re.compile(
    rf"^([a-zA-Z0-9_-]{{{SECURE_HASH_LENGTH}}})(\d+)(?:/.*)?$")
PATTERN_ID_FIRST = re.compile(r"^(\d+)(?:/.*)?$")
VALID_HASH_REGEX = re.compile(r'^[a-zA-Z0-9_-]+$')

CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, OPTIONS",
    "Access-Control-Allow-Headers": "Range, Content-Type, *",
    "Access-Control-Expose-Headers": "Content-Length, Content-Range, Content-Disposition",
}

streamers = {}


# ---------------- HELPERS ----------------

def get_streamer(client_id: int) -> ByteStreamer:
    if client_id not in streamers:
        streamers[client_id] = ByteStreamer(multi_clients[client_id])
    return streamers[client_id]


def parse_media_request(path: str, query: dict) -> tuple[int, str]:
    clean_path = unquote(path).strip('/')

    match = PATTERN_HASH_FIRST.match(clean_path)
    if match:
        return int(match.group(2)), match.group(1)

    match = PATTERN_ID_FIRST.match(clean_path)
    if match:
        return int(match.group(1)), query.get("hash", "").strip()

    raise InvalidHash("Invalid URL")


def select_optimal_client() -> tuple[int, ByteStreamer]:
    if not work_loads:
        raise web.HTTPInternalServerError(text="No clients available")

    available = [
        (cid, load) for cid, load in work_loads.items()
        if load < MAX_CONCURRENT_PER_CLIENT
    ]

    client_id = min(available, key=lambda x: x[1])[0] if available else min(work_loads, key=work_loads.get)
    return client_id, get_streamer(client_id)


def parse_range_header(range_header: str, file_size: int) -> tuple[int, int]:
    if not range_header:
        return 0, file_size - 1

    match = RANGE_REGEX.match(range_header)
    if not match:
        raise web.HTTPBadRequest()

    start = int(match.group("start") or 0)
    end = int(match.group("end") or file_size - 1)
    return start, min(end, file_size - 1)


# ---------------- ROUTES ----------------

@routes.get("/")
async def root_redirect(request):
    raise web.HTTPFound("https://github.com/fyaz05/FileToLink")


@routes.get("/status")
async def status_endpoint(request):
    return web.json_response({
        "server": {
            "status": "operational",
            "version": __version__,
            "uptime": get_readable_time(time.time() - StartTime)
        },
        "telegram_bot": {
            "username": f"@{StreamBot.username}",
            "active_clients": len(multi_clients)
        }
    })


@routes.options(r"/{path:.+}")
async def options_handler(request):
    return web.Response(headers={**CORS_HEADERS, "Access-Control-Max-Age": "86400"})


# ---------------- STREAM PAGE ----------------

@routes.get(r"/watch/{path:.+}")
async def media_preview(request: web.Request):
    path = request.match_info["path"]
    message_id, secure_hash = parse_media_request(path, request.query)

    html = await render_page(message_id, secure_hash, requested_action="stream")
    return web.Response(
        text=html,
        content_type="text/html",
        headers={"Access-Control-Allow-Origin": "*"}
    )


# ---------------- FILE DELIVERY (FIXED) ----------------

@routes.get(r"/{path:.+}")
async def media_delivery(request: web.Request):

    # ❌ Block HEAD (fixes 0B / browser stuck)
    if request.method == "HEAD":
        raise web.HTTPMethodNotAllowed("HEAD", ["GET"])

    path = request.match_info["path"]
    message_id, secure_hash = parse_media_request(path, request.query)

    client_id, streamer = select_optimal_client()
    work_loads[client_id] += 1

    try:
        # 🔄 AUTO REFRESH CLIENT (replaces /restart)
        if not streamer.client.is_connected:
            await streamer.client.start()

        file_info = await streamer.get_file_info(message_id)

        if not file_info or not file_info.get("unique_id"):
            raise FileNotFound("File not found")

        if file_info["unique_id"][:SECURE_HASH_LENGTH] != secure_hash:
            raise InvalidHash("Hash mismatch")

        file_size = file_info.get("file_size", 0)
        if file_size <= 0:
            raise FileNotFound("Invalid file size")

        range_header = request.headers.get("Range")
        start, end = parse_range_header(range_header, file_size)
        content_length = end - start + 1

        mime = file_info.get("mime_type", "application/octet-stream")
        filename = file_info.get("file_name") or f"file_{secrets.token_hex(4)}"

        headers = {
            "Content-Type": mime,
            "Content-Disposition": f"inline; filename*=UTF-8''{quote(filename)}",
            "Accept-Ranges": "bytes",
            "Cache-Control": "no-store",
            "Access-Control-Allow-Origin": "*",
            "Content-Range": f"bytes {start}-{end}/{file_size}"
        }

        async def stream_generator():
            try:
                async for chunk in streamer.stream_file(
                    message_id,
                    offset=start,
                    limit=content_length
                ):
                    yield chunk
            finally:
                work_loads[client_id] -= 1

        return web.Response(
            status=206,
            body=stream_generator(),
            headers=headers
        )

    except Exception as e:
        work_loads[client_id] -= 1
        logger.error(f"Stream error: {e}", exc_info=True)
        raise web.HTTPNotFound(text="Link expired or invalid")
