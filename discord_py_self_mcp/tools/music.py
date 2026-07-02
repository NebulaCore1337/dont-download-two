import asyncio
import discord
import json
import os
from collections import deque
from dataclasses import dataclass, field
from typing import Optional

from soundcloud import SoundCloud as SC

_sc = SC()


def _sc_search(query, limit=5):
    results = []
    for track in _sc.search(query, limit=limit):
        stream_url = None
        for t in track.media.transcodings:
            if t.format.protocol == 'progressive':
                stream_url = t.url
                break
        results.append({
            "title": track.title,
            "artist": track.user.username if track.user else "Unknown",
            "duration": (track.duration or 0) // 1000,
            "url": track.permalink_url,
            "stream_url": stream_url or "",
        })
    return results


def _sc_resolve(url):
    track = _sc.resolve(url)
    if not track:
        raise Exception("Track not found")
    stream_url = None
    for t in track.media.transcodings:
        if t.format.protocol == 'progressive':
            stream_url = t.url
            break
    return {
        "title": track.title,
        "artist": track.user.username if track.user else "Unknown",
        "duration": (track.duration or 0) // 1000,
        "url": track.permalink_url,
        "stream_url": stream_url or "",
    }

from mcp.types import TextContent
from .registry import registry
from ..bot import client
from ..tool_utils import apply_rate_limit


@dataclass
class Track:
    url: str
    title: str
    duration: int  # seconds
    artist: str = ""
    stream_url: str = ""


@dataclass
class MusicState:
    queue: deque = field(default_factory=deque)
    current: Optional[Track] = None
    volume: float = 1.0
    is_paused: bool = False
    is_playing: bool = False
    guild_id: Optional[int] = None
    channel_id: Optional[int] = None


# Global state per guild
_states: dict[int, MusicState] = {}


def _get_state(guild_id: int) -> MusicState:
    if guild_id not in _states:
        _states[guild_id] = MusicState(guild_id=guild_id)
    return _states[guild_id]


async def _search_soundcloud(query: str, limit: int = 5) -> list[dict]:
    """Search SoundCloud via soundcloud-v2."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _sc_search, query, limit)


async def _get_stream_url(url: str) -> dict:
    """Get stream info from a SoundCloud URL."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _sc_resolve, url)


def _format_duration(seconds: int) -> str:
    if seconds <= 0:
        return "?:??"
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def _get_vc(channel):
    """Get voice client from either a guild or group channel."""
    if isinstance(channel, discord.Guild):
        return channel.voice_client
    elif isinstance(channel, discord.GroupChannel):
        # GroupChannel has no .voice_client — find via client.voice_clients
        if client.voice_clients:
            for v in client.voice_clients:
                if hasattr(v, 'channel') and str(v.channel) == channel.name:
                    return v
            return client.voice_clients[0]
    return None


async def _play_track(channel, state: MusicState):
    """Play the next track in the queue. channel is Guild or GroupChannel."""
    vc = _get_vc(channel)
    if not vc or not isinstance(vc, discord.VoiceClient):
        state.is_playing = False
        state.current = None
        return

    if state.is_paused:
        return

    if not state.queue:
        state.is_playing = False
        state.current = None
        return

    track = state.queue.popleft()
    state.current = track
    state.is_playing = True

    try:
        source = discord.FFmpegPCMAudio(
            track.stream_url if isinstance(track, dict) else track["stream_url"],
            before_options="-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
            options=f"-vn -af volume={state.volume}",
        )
        source = discord.PCMVolumeTransformer(source, volume=state.volume)

        def after_playing(error):
            if error:
                pass
            coro = _play_track(channel, state)
            asyncio.run_coroutine_threadsafe(coro, client.loop)

        vc.play(source, after=after_playing)
    except Exception:
        state.is_playing = False
        state.current = None
        if state.queue:
            await _play_track(channel, state)


@registry.register(
    name="soundcloud_search",
    description="Search SoundCloud for tracks. Returns a list of matching tracks with titles, artists, durations, and URLs.",
    input_schema={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search query (e.g. 'deadmau5 strobe' or a SoundCloud URL)",
            },
            "limit": {
                "type": "integer",
                "description": "Number of results to return (default 5, max 10)",
            },
        },
        "required": ["query"],
    },
)
async def soundcloud_search(arguments: dict):
    query = arguments.get("query", "")
    limit = min(int(arguments.get("limit", 5)), 10)

    if not query:
        return [TextContent(type="text", text="Error: query is required")]

    # If it's already a URL, resolve it directly
    if "soundcloud.com/" in query:
        try:
            stream_url, title, duration, artist = await _get_stream_url(query)
            return [TextContent(type="text", text=json.dumps({
                "results": [{
                    "title": title,
                    "artist": artist,
                    "duration": _format_duration(duration),
                    "duration_seconds": duration,
                    "url": query,
                    "stream_url": stream_url,
                }]
            }))]
        except Exception as e:
            return [TextContent(type="text", text=f"Error resolving URL: {str(e)}")]

    results = await _search_soundcloud(query, limit)
    if not results:
        return [TextContent(type="text", text="No results found for: " + query)]

    formatted = []
    for r in results:
        formatted.append({
            "title": r["title"],
            "artist": r["artist"],
            "duration": _format_duration(r["duration"]),
            "duration_seconds": r["duration"],
            "url": r["webpage_url"],
        })

    return [TextContent(type="text", text=json.dumps({"results": formatted}))]


@registry.register(
    name="play_soundcloud",
    description="Play a SoundCloud track or URL in a voice channel or group DM call. Use soundcloud_search first to find tracks, or pass a direct SoundCloud URL. Tracks are queued automatically.",
    input_schema={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "SoundCloud URL or search query to play",
            },
            "guild_id": {
                "type": "string",
                "description": "Guild (server) ID (use this OR group_id, not both)",
            },
            "group_id": {
                "type": "string",
                "description": "Group DM ID (use this OR guild_id, not both)",
            },
        },
        "required": ["query"],
    },
)
async def play_soundcloud(arguments: dict):
    query = arguments.get("query", "")
    guild_id = arguments.get("guild_id")
    group_id = arguments.get("group_id")

    if not query:
        return [TextContent(type="text", text="Error: query is required")]

    # Resolve target channel
    channel = None
    state_key = 0
    if group_id:
        group_id = int(group_id)
        channel = client.get_channel(group_id)
        if not channel or not isinstance(channel, discord.GroupChannel):
            return [TextContent(type="text", text="Group DM not found")]
        if not channel.voice_client:
            return [TextContent(type="text", text="Not in a voice call in this group. Use join_group_voice first.")]
        state_key = group_id
    elif guild_id:
        guild_id = int(guild_id)
        channel = client.get_guild(guild_id)
        if not channel:
            return [TextContent(type="text", text="Guild not found")]
        if not channel.voice_client:
            return [TextContent(type="text", text="Not in a voice channel. Use join_voice_channel first.")]
        state_key = guild_id
    else:
        return [TextContent(type="text", text="Error: provide guild_id or group_id")]

    state = _get_state(state_key)

    try:
        if "soundcloud.com/" in query:
            stream_url, title, duration, artist = await _get_stream_url(query)
            track = Track(
                url=query, title=title, duration=duration,
                artist=artist, stream_url=stream_url,
            )
        else:
            results = await _search_soundcloud(query, 1)
            if not results:
                return [TextContent(type="text", text="No results found for: " + query)]
            r = results[0]
            stream_url, title, duration, artist = await _get_stream_url(r["webpage_url"])
            track = Track(
                url=r["webpage_url"], title=title, duration=duration,
                artist=artist, stream_url=stream_url,
            )

        state.queue.append(track)

        if not state.is_playing and not state.is_paused:
            await apply_rate_limit("action")
            await _play_track(channel, state)

        position = len(state.queue) + (1 if state.is_playing else 0)
        return [TextContent(type="text", text=json.dumps({
            "status": "added",
            "track": {
                "title": track.title,
                "artist": track.artist,
                "duration": _format_duration(track.duration),
                "url": track.url,
            },
            "queue_position": position,
        }))]

    except Exception as e:
        return [TextContent(type="text", text=f"Error playing track: {str(e)}")]


def _resolve_vc(arguments: dict):
    """Resolve voice client and state key from guild_id or group_id."""
    guild_id = arguments.get("guild_id")
    group_id = arguments.get("group_id")

    if group_id:
        group_id = int(group_id)
        ch = client.get_channel(group_id)
        if not ch or not isinstance(ch, discord.GroupChannel):
            return None, None, "Group DM not found"
        vc = ch.voice_client
        if not vc:
            return None, None, "Not in a voice call. Use join_group_voice first."
        return vc, group_id, None

    if guild_id:
        guild_id = int(guild_id)
        guild = client.get_guild(guild_id)
        if not guild:
            return None, None, "Guild not found"
        vc = guild.voice_client
        if not vc:
            return None, None, "Not in a voice channel. Use join_voice_channel first."
        return vc, guild_id, None

    return None, None, "Provide guild_id or group_id"


MUSIC_ID_SCHEMA = {
    "type": "object",
    "properties": {
        "guild_id": {"type": "string", "description": "Guild ID (use this OR group_id)"},
        "group_id": {"type": "string", "description": "Group DM ID (use this OR guild_id)"},
    },
}


@registry.register(
    name="music_stop",
    description="Stop music playback and clear the queue.",
    input_schema=MUSIC_ID_SCHEMA,
)
async def music_stop(arguments: dict):
    vc, key, err = _resolve_vc(arguments)
    if err:
        return [TextContent(type="text", text=err)]

    state = _get_state(key)
    state.queue.clear()
    state.current = None
    state.is_playing = False
    state.is_paused = False

    if vc.is_playing():
        vc.stop()

    return [TextContent(type="text", text="Stopped playback and cleared queue.")]


@registry.register(
    name="music_pause",
    description="Pause music playback.",
    input_schema=MUSIC_ID_SCHEMA,
)
async def music_pause(arguments: dict):
    vc, key, err = _resolve_vc(arguments)
    if err:
        return [TextContent(type="text", text=err)]

    state = _get_state(key)

    if vc.is_playing():
        vc.pause()
        state.is_paused = True
        return [TextContent(type="text", text="Paused playback.")]
    elif state.is_paused:
        return [TextContent(type="text", text="Already paused.")]
    else:
        return [TextContent(type="text", text="Nothing is playing.")]


@registry.register(
    name="music_resume",
    description="Resume paused music playback.",
    input_schema=MUSIC_ID_SCHEMA,
)
async def music_resume(arguments: dict):
    vc, key, err = _resolve_vc(arguments)
    if err:
        return [TextContent(type="text", text=err)]

    state = _get_state(key)

    if vc.is_paused():
        vc.resume()
        state.is_paused = False
        return [TextContent(type="text", text="Resumed playback.")]
    else:
        return [TextContent(type="text", text="Nothing is paused.")]


@registry.register(
    name="music_skip",
    description="Skip the currently playing track and play the next one in queue.",
    input_schema=MUSIC_ID_SCHEMA,
)
async def music_skip(arguments: dict):
    vc, key, err = _resolve_vc(arguments)
    if err:
        return [TextContent(type="text", text=err)]

    state = _get_state(key)
    skipped = state.current

    if vc.is_playing() or vc.is_paused():
        vc.stop()
        return [TextContent(type="text", text=json.dumps({
            "status": "skipped",
            "skipped_track": {
                "title": skipped.title if skipped else "None",
                "artist": skipped.artist if skipped else "",
            },
            "queue_remaining": len(state.queue),
        }))]
    else:
        return [TextContent(type="text", text="Nothing is playing.")]


@registry.register(
    name="music_queue",
    description="Show the current music queue and now playing track.",
    input_schema=MUSIC_ID_SCHEMA,
)
async def music_queue(arguments: dict):
    _, key, err = _resolve_vc(arguments)
    if err:
        return [TextContent(type="text", text=err)]

    state = _get_state(key)

    result = {
        "now_playing": None,
        "queue": [],
        "queue_length": len(state.queue),
        "is_paused": state.is_paused,
    }

    if state.current:
        result["now_playing"] = {
            "title": state.current.title,
            "artist": state.current.artist,
            "duration": _format_duration(state.current.duration),
            "url": state.current.url,
        }

    for i, track in enumerate(state.queue):
        result["queue"].append({
            "position": i + 1,
            "title": track.title,
            "artist": track.artist,
            "duration": _format_duration(track.duration),
            "url": track.url,
        })

    return [TextContent(type="text", text=json.dumps(result))]


@registry.register(
    name="music_volume",
    description="Set the music playback volume.",
    input_schema={
        "type": "object",
        "properties": {
            "guild_id": {"type": "string", "description": "Guild ID (use this OR group_id)"},
            "group_id": {"type": "string", "description": "Group DM ID (use this OR guild_id)"},
            "volume": {"type": "number", "description": "Volume level from 0.0 to 2.0 (1.0 = normal)"},
        },
        "required": ["volume"],
    },
)
async def music_volume(arguments: dict):
    vc, key, err = _resolve_vc(arguments)
    if err:
        return [TextContent(type="text", text=err)]

    volume = float(arguments.get("volume", 1.0))
    volume = max(0.0, min(2.0, volume))

    state = _get_state(key)
    state.volume = volume

    if vc and vc.source and isinstance(vc.source, discord.PCMVolumeTransformer):
        vc.source.volume = volume

    return [TextContent(type="text", text=f"Volume set to {volume:.0%}")]


@registry.register(
    name="music_now_playing",
    description="Get the currently playing track.",
    input_schema=MUSIC_ID_SCHEMA,
)
async def music_now_playing(arguments: dict):
    vc, key, err = _resolve_vc(arguments)
    if err:
        return [TextContent(type="text", text=err)]

    state = _get_state(key)

    if not state.current:
        return [TextContent(type="text", text="Nothing is currently playing.")]

    return [TextContent(type="text", text=json.dumps({
        "title": state.current.title,
        "artist": state.current.artist,
        "duration": _format_duration(state.current.duration),
        "url": state.current.url,
        "status": "playing" if vc.is_playing() and not state.is_paused else "paused" if state.is_paused else "idle",
        "volume": state.volume,
        "queue_remaining": len(state.queue),
    }))]
