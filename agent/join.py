"""The endpoint the client fetches its LiveKit connection details from, in the format every LiveKit SDK speaks."""

import json

from aiohttp import web
from loguru import logger

from agent.config import Config
from agent.transports.livekit import CLIENT_IDENTITY, join_token

PORT = 8080
PATH = "/getToken"


async def _body(request: web.Request) -> dict:
    """Read the request body, treating an absent one as a client that asked for nothing in particular."""
    if not request.can_read_body:
        return {}
    try:
        body = await request.json()
    except json.JSONDecodeError as error:
        raise web.HTTPBadRequest(text="The request body is not JSON.") from error
    if not isinstance(body, dict):
        raise web.HTTPBadRequest(text="The request body is not an object.")
    return body


def _handler(config: Config):
    """Build the request handler, closing over the configuration it answers from."""

    async def get_token(request: web.Request) -> web.Response:
        """Answer one request with where the room is and the token to enter it with."""
        body = await _body(request)
        # The client names its room and identity where it has an opinion, and inherits the configured ones where it has none.
        room = body.get("room_name") or config.room
        identity = body.get("participant_identity") or CLIENT_IDENTITY
        name = body.get("participant_name") or identity
        logger.info(f"Handing '{identity}' a token for room '{room}'")
        return web.json_response(
            {
                "server_url": config.livekit_url,
                "participant_token": join_token(config, identity, room, name),
            },
            status=201,
        )

    return get_token


async def serve(config: Config) -> web.AppRunner:
    """Start the endpoint on every interface, so a client on another machine reaches it too, and return it for shutdown."""
    app = web.Application()
    app.router.add_post(PATH, _handler(config))
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    await web.TCPSite(runner, port=PORT).start()
    return runner
