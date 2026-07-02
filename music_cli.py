"""
Interactive Music CLI for discord.py-self-mcp.

Run: python music_cli.py
"""

import asyncio
import os
import sys
import threading
from collections import deque

try:
    import discord
except ImportError:
    print("discord.py-self not installed.")
    sys.exit(1)

from dotenv import load_dotenv
from soundcloud import SoundCloud as SC
from curl_cffi import requests as curl_req

load_dotenv()
_sc = SC()

# ── SoundCloud helpers ──

def _sc_search(query, limit=5):
    results = []
    for track in _sc.search(query, limit=limit):
        cdn_url = None
        for t in track.media.transcodings:
            if t.format.protocol == 'progressive':
                r = curl_req.get(t.url + '?client_id=' + _sc.client_id, impersonate='chrome', timeout=10)
                if r.status_code == 200:
                    try: cdn_url = r.json().get('url', '')
                    except: pass
                break
        local_path = None
        if cdn_url:
            r = curl_req.get(cdn_url, impersonate='chrome', timeout=30)
            if r.status_code == 200 and len(r.content) > 1000:
                os.makedirs('tmp_music', exist_ok=True)
                safe = ''.join(c if c.isalnum() or c in '-_' else '_' for c in track.title)[:50]
                local_path = os.path.join('tmp_music', f'{track.id}_{safe}.mp3')
                with open(local_path, 'wb') as f: f.write(r.content)
        results.append({
            "title": track.title, "artist": track.user.username if track.user else "Unknown",
            "duration": (track.duration or 0) // 1000, "url": track.permalink_url,
            "stream_url": local_path or cdn_url or "",
        })
    return results

def _sc_resolve(url):
    track = _sc.resolve(url)
    if not track: raise Exception("Track not found")
    cdn_url = None
    for t in track.media.transcodings:
        if t.format.protocol == 'progressive':
            r = curl_req.get(t.url + '?client_id=' + _sc.client_id, impersonate='chrome', timeout=10)
            if r.status_code == 200:
                try: cdn_url = r.json().get('url', '')
                except: pass
            break
    local_path = None
    if cdn_url:
        r = curl_req.get(cdn_url, impersonate='chrome', timeout=30)
        if r.status_code == 200 and len(r.content) > 1000:
            os.makedirs('tmp_music', exist_ok=True)
            safe = ''.join(c if c.isalnum() or c in '-_' else '_' for c in track.title)[:50]
            local_path = os.path.join('tmp_music', f'{track.id}_{safe}.mp3')
            with open(local_path, 'wb') as f: f.write(r.content)
    return {
        "title": track.title, "artist": track.user.username if track.user else "Unknown",
        "duration": (track.duration or 0) // 1000, "url": track.permalink_url,
        "stream_url": local_path or cdn_url or "",
    }

async def search_soundcloud(query, limit=5):
    return await asyncio.get_event_loop().run_in_executor(None, _sc_search, query, limit)

async def get_stream_url(url):
    return await asyncio.get_event_loop().run_in_executor(None, _sc_resolve, url)

def fmt_dur(s):
    if s <= 0: return "?"
    m, sec = divmod(int(s), 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"

# ── State ──

class MusicState:
    def __init__(self):
        self.queue = deque()
        self.current = None
        self.volume = 1.0
        self.is_paused = False
        self.is_playing = False

states = {}
active_channel = None  # currently active group/guild

def get_state(key):
    if key not in states: states[key] = MusicState()
    return states[key]

def get_active_vc():
    if not client.voice_clients: return None, None
    vc = client.voice_clients[0]
    for ch in client.private_channels:
        if isinstance(ch, discord.GroupChannel) and hasattr(vc, 'channel') and str(vc.channel) == ch.name:
            return ch, vc
    for g in client.guilds:
        if g.voice_client: return g, g.voice_client
    return None, vc

def resolve_target(args=None):
    """Resolve target: args override, else auto-detect active."""
    if args:
        if args.isdigit():
            ch = client.get_channel(int(args))
            if ch and isinstance(ch, discord.GroupChannel): return ch
            g = client.get_guild(int(args))
            if g: return g
    ch, vc = get_active_vc()
    return ch

# ── Playback ──

async def play_track(channel, state):
    ch, vc = get_active_vc()
    if not vc:
        state.is_playing = False
        return

    if state.is_paused or not state.queue:
        state.is_playing = bool(state.queue)
        return

    track = state.queue.popleft()
    state.current = track
    state.is_playing = True

    try:
        path = track.get("stream_url", "")
        if not path:
            print(f"  No stream for: {track['title']}")
            state.is_playing = False
            if state.queue: await play_track(channel, state)
            return

        if os.path.isfile(path):
            source = discord.FFmpegPCMAudio(path, options=f"-vn -af volume={state.volume}")
        else:
            source = discord.FFmpegPCMAudio(path, before_options="-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5", options=f"-vn -af volume={state.volume}")
        source = discord.PCMVolumeTransformer(source, volume=state.volume)

        def after(e):
            if e: print(f"  Error: {e}")
            asyncio.run_coroutine_threadsafe(play_track(channel, state), client.loop)

        vc.play(source, after=after)
        dur = fmt_dur(track.get('duration', 0))
        print(f"  ▶ {track['artist']} - {track['title']} [{dur}]")
    except Exception as e:
        print(f"  Error: {e}")
        state.is_playing = False
        state.current = None
        if state.queue: await play_track(channel, state)

# ── Client ──

client = discord.Client()

def get_prompt():
    ch, vc = get_active_vc()
    if ch and vc:
        return f"[{ch.name}] "
    return ""

def repl_thread():
    asyncio.new_event_loop()
    while True:
        try:
            text = input(f"{get_prompt()}> ")
        except (EOFError, KeyboardInterrupt):
            asyncio.run_coroutine_threadsafe(client.close(), client.loop)
            break
        if text.strip():
            asyncio.run_coroutine_threadsafe(handle_command(text), client.loop)

# ── Commands ──

async def handle_command(text):
    parts = text.strip().split()
    if not parts: return
    cmd = parts[0].lower()
    arg = parts[1] if len(parts) > 1 else None

    # Aliases
    ALIASES = {"p": "play", "s": "stop", "ps": "pause", "r": "resume", "n": "now",
               "q": "queue", "v": "volume", "l": "leave", "j": "join", "h": "help"}
    cmd = ALIASES.get(cmd, cmd)

    if cmd == "help":
        print("""
  j <group_id>          Join group voice
  l <group_id>          Leave group voice
  p <file|url|query>    Play (auto-detects active channel)
  s                     Stop & clear
  ps / r                Pause / Resume
  n                     Now playing
  q                     Queue
  sk                    Skip
  v <0.0-2.0>           Volume
  vu / vd               Volume up/down
  cl                    Clear queue
  g                     List groups
  q!                    Quit
""")

    elif cmd == "quit" or cmd == "q!":
        await client.close()
        sys.exit(0)

    elif cmd == "groups" or cmd == "g":
        groups = [ch for ch in client.private_channels if isinstance(ch, discord.GroupChannel)]
        if not groups: print("  No groups"); return
        for g in groups:
            vc = client.voice_clients
            in_vc = any(hasattr(v, 'channel') and str(v.channel) == g.name for v in vc)
            tag = " ●" if in_vc else ""
            print(f"  {g.id}  {g.name}{tag}")

    elif cmd == "join" or cmd == "j":
        if not arg: print("  Usage: j <group_id>"); return
        ch = client.get_channel(int(arg))
        if not ch or not isinstance(ch, discord.GroupChannel):
            print("  Not a group"); return
        try:
            await ch.connect()
            global active_channel
            active_channel = ch
            print(f"  Joined: {ch.name}")
        except Exception as e:
            print(f"  Error: {e}")

    elif cmd == "leave" or cmd == "l":
        ch, vc = get_active_vc()
        if not vc: print("  Not in voice"); return
        if arg:
            target = client.get_channel(int(arg))
            if target:
                for v in client.voice_clients:
                    if hasattr(v, 'channel') and str(v.channel) == target.name:
                        await v.disconnect()
                        print(f"  Left: {target.name}")
                        return
        await vc.disconnect()
        print(f"  Left")

    elif cmd == "play" or cmd == "p":
        if not arg:
            # If paused, resume
            ch, vc = get_active_vc()
            if vc and vc.is_paused():
                vc.resume()
                _, state = get_active_vc()
                key = str(ch.id) if ch else "default"
                get_state(key).is_paused = False
                print("  Resumed")
                return
            print("  Usage: p <file|url|query>"); return

        ch, vc = get_active_vc()
        if not vc: print("  Not in voice. Use j <group_id>"); return
        key = str(ch.id) if ch else "default"
        state = get_state(key)

        try:
            if os.path.isfile(arg):
                track = {"title": os.path.basename(arg), "artist": "File", "duration": 0, "url": arg, "stream_url": arg}
            elif "soundcloud.com/" in arg:
                track = await get_stream_url(arg)
            else:
                results = await search_soundcloud(arg, 1)
                if not results: print("  Not found"); return
                track = results[0]

            state.queue.append(track)
            if not state.is_playing and not state.is_paused:
                await play_track(ch, state)
            else:
                dur = fmt_dur(track.get('duration', 0))
                print(f"  + {track['artist']} - {track['title']} [{dur}]")
        except Exception as e:
            print(f"  Error: {e}")

    elif cmd == "stop":
        ch, vc = get_active_vc()
        if not vc: print("  Not in voice"); return
        key = str(ch.id) if ch else "default"
        state = get_state(key)
        state.queue.clear(); state.current = None
        state.is_playing = False; state.is_paused = False
        if vc.is_playing(): vc.stop()
        print("  Stopped")

    elif cmd == "pause":
        ch, vc = get_active_vc()
        if not vc: print("  Not in voice"); return
        if vc.is_playing():
            vc.pause()
            key = str(ch.id) if ch else "default"
            get_state(key).is_paused = True
            print("  Paused")
        else: print("  Nothing playing")

    elif cmd == "resume":
        ch, vc = get_active_vc()
        if not vc: print("  Not in voice"); return
        if vc.is_paused():
            vc.resume()
            key = str(ch.id) if ch else "default"
            get_state(key).is_paused = False
            print("  Resumed")
        else: print("  Not paused")

    elif cmd == "skip":
        ch, vc = get_active_vc()
        if not vc: print("  Not in voice"); return
        if vc.is_playing() or vc.is_paused():
            key = str(ch.id) if ch else "default"
            state = get_state(key)
            name = state.current['title'] if state.current else "?"
            vc.stop()
            print(f"  Skipped: {name}")
        else: print("  Nothing playing")

    elif cmd == "queue":
        ch, vc = get_active_vc()
        if not vc: print("  Not in voice"); return
        key = str(ch.id) if ch else "default"
        state = get_state(key)
        if state.current:
            s = "❚❚" if state.is_paused else "▶"
            print(f"  {s} {state.current['artist']} - {state.current['title']} [{fmt_dur(state.current['duration'])}]")
        if state.queue:
            for i, t in enumerate(state.queue, 1):
                print(f"  {i}. {t['artist']} - {t['title']} [{fmt_dur(t['duration'])}]")
        elif not state.current:
            print("  Empty")

    elif cmd == "now" or cmd == "n":
        ch, vc = get_active_vc()
        if not vc: print("  Not in voice"); return
        key = str(ch.id) if ch else "default"
        state = get_state(key)
        if not state.current: print("  Nothing playing"); return
        s = "▶" if vc.is_playing() and not state.is_paused else "❚❚" if state.is_paused else "○"
        print(f"  {s} {state.current['artist']} - {state.current['title']}")
        print(f"    {fmt_dur(state.current['duration'])}  vol {state.volume:.0%}  q:{len(state.queue)}")

    elif cmd == "volume" or cmd == "v":
        if not arg: print("  Usage: v <0.0-2.0>"); return
        vol = max(0.0, min(2.0, float(arg)))
        ch, vc = get_active_vc()
        if not vc: print("  Not in voice"); return
        key = str(ch.id) if ch else "default"
        get_state(key).volume = vol
        if vc.source and isinstance(vc.source, discord.PCMVolumeTransformer):
            vc.source.volume = vol
        print(f"  Vol: {vol:.0%}")

    elif cmd == "vu":
        ch, vc = get_active_vc()
        if not vc: print("  Not in voice"); return
        key = str(ch.id) if ch else "default"
        state = get_state(key)
        state.volume = min(2.0, state.volume + 0.1)
        if vc.source and isinstance(vc.source, discord.PCMVolumeTransformer):
            vc.source.volume = state.volume
        print(f"  Vol: {state.volume:.0%}")

    elif cmd == "vd":
        ch, vc = get_active_vc()
        if not vc: print("  Not in voice"); return
        key = str(ch.id) if ch else "default"
        state = get_state(key)
        state.volume = max(0.0, state.volume - 0.1)
        if vc.source and isinstance(vc.source, discord.PCMVolumeTransformer):
            vc.source.volume = state.volume
        print(f"  Vol: {state.volume:.0%}")

    elif cmd == "cl":
        ch, vc = get_active_vc()
        if not vc: print("  Not in voice"); return
        key = str(ch.id) if ch else "default"
        state = get_state(key)
        n = len(state.queue)
        state.queue.clear()
        print(f"  Cleared {n} track(s)")

    elif cmd == "search":
        if not arg: print("  Usage: search <query>"); return
        query = " ".join(parts[1:])
        results = await search_soundcloud(query, 5)
        if not results: print("  Nothing found"); return
        for i, r in enumerate(results, 1):
            print(f"  {i}. {r['artist']} - {r['title']} [{fmt_dur(r['duration'])}]")
            print(f"     {r['url']}")

    elif cmd == "status":
        ch, vc = get_active_vc()
        if vc:
            print(f"  Connected: {getattr(vc, 'channel', '?')}")
        else:
            print("  Not connected")

    else:
        print(f"  ? '{cmd}' — type h for help")

# ── Main ──

async def main():
    token = os.getenv("DISCORD_TOKEN")
    if not token: print("DISCORD_TOKEN not set"); sys.exit(1)

    @client.event
    async def on_ready():
        print(f"  Logged in: {client.user}")
        groups = [ch for ch in client.private_channels if isinstance(ch, discord.GroupChannel)]
        print(f"  {len(client.guilds)} servers, {len(groups)} groups")
        print(f"  Type h for help\n")
        threading.Thread(target=repl_thread, daemon=True).start()

    await client.start(token)

if __name__ == "__main__":
    asyncio.run(main())
