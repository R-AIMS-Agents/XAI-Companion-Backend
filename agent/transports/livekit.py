"""LiveKit transport: room access tokens and transport construction."""

from datetime import timedelta

from livekit import api
from pipecat.transports.livekit.transport import LiveKitParams, LiveKitTransport

from agent.config import SAMPLE_RATE, Config

AGENT_IDENTITY = "agent"
CLIENT_IDENTITY = "unity"
TOKEN_TTL = timedelta(hours=12)


def _join_token(config: Config, identity: str) -> str:
    """Mint a room access token for one identity, signed with the server's key pair."""
    return (
        api.AccessToken(config.livekit_api_key, config.livekit_api_secret)
        .with_identity(identity)
        .with_name(identity)
        .with_ttl(TOKEN_TTL)
        .with_grants(api.VideoGrants(room_join=True, room=config.room))
        .to_jwt()
    )


def client_token(config: Config) -> str:
    """Mint the join token the Unity client uses to enter the same room."""
    return _join_token(config, CLIENT_IDENTITY)


def create(config: Config) -> LiveKitTransport:
    """Build the LiveKit transport the pipeline runs on."""
    params = LiveKitParams(
        audio_in_enabled=True,
        audio_in_sample_rate=SAMPLE_RATE,
        audio_out_enabled=True,
        audio_out_sample_rate=SAMPLE_RATE,
    )
    return LiveKitTransport(
        url=config.livekit_url,
        token=_join_token(config, AGENT_IDENTITY),
        room_name=config.room,
        params=params,
    )
