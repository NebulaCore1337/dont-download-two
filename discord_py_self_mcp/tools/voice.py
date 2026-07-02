import discord
from mcp.types import TextContent
from .registry import registry
from ..bot import client
from ..tool_utils import apply_rate_limit

@registry.register(
    name="join_voice_channel",
    description="Join a voice channel in a server",
    input_schema={
        "type": "object",
        "properties": {
            "channel_id": {"type": "string"}
        },
        "required": ["channel_id"]
    }
)
async def join_voice_channel(arguments: dict):
    try:
        channel_id = int(arguments["channel_id"])
        channel = client.get_channel(channel_id)
        if not channel:
            return [TextContent(type="text", text="Channel not found")]

        if not isinstance(channel, discord.VoiceChannel):
             return [TextContent(type="text", text="Channel is not a voice channel")]

        await apply_rate_limit("action")
        await channel.connect()
        return [TextContent(type="text", text=f"Joined voice channel {channel.name}")]
    except Exception as e:
        return [TextContent(type="text", text=f"Error joining voice channel: {str(e)}")]

@registry.register(
    name="join_group_voice",
    description="Join a voice call in a Group DM",
    input_schema={
        "type": "object",
        "properties": {
            "group_id": {"type": "string", "description": "Group DM ID"}
        },
        "required": ["group_id"]
    }
)
async def join_group_voice(arguments: dict):
    try:
        group_id = int(arguments["group_id"])
        channel = client.get_channel(group_id)
        if not channel:
            return [TextContent(type="text", text="Group not found")]

        if not isinstance(channel, discord.GroupChannel):
            return [TextContent(type="text", text="Channel is not a Group DM")]

        await apply_rate_limit("action")
        vc = await channel.connect()
        return [TextContent(type="text", text=f"Joined voice call in group: {channel.name}")]
    except Exception as e:
        return [TextContent(type="text", text=f"Error joining group voice: {str(e)}")]

@registry.register(
    name="leave_voice_channel",
    description="Leave the voice channel in a guild",
    input_schema={
        "type": "object",
        "properties": {
            "guild_id": {"type": "string"}
        },
        "required": ["guild_id"]
    }
)
async def leave_voice_channel(arguments: dict):
    try:
        guild_id = int(arguments["guild_id"])
        guild = client.get_guild(guild_id)
        if not guild:
            return [TextContent(type="text", text="Guild not found")]

        if guild.voice_client:
            await apply_rate_limit("action")
            await guild.voice_client.disconnect()
            return [TextContent(type="text", text=f"Left voice channel in {guild.name}")]
        else:
            return [TextContent(type="text", text="Not in a voice channel in this guild")]
    except Exception as e:
        return [TextContent(type="text", text=f"Error leaving voice channel: {str(e)}")]

@registry.register(
    name="leave_group_voice",
    description="Leave a voice call in a Group DM",
    input_schema={
        "type": "object",
        "properties": {
            "group_id": {"type": "string", "description": "Group DM ID"}
        },
        "required": ["group_id"]
    }
)
async def leave_group_voice(arguments: dict):
    try:
        group_id = int(arguments["group_id"])
        channel = client.get_channel(group_id)
        if not channel:
            return [TextContent(type="text", text="Group not found")]

        if isinstance(channel, discord.GroupChannel) and channel.voice_client:
            await apply_rate_limit("action")
            await channel.voice_client.disconnect()
            return [TextContent(type="text", text=f"Left voice call in {channel.name}")]
        else:
            return [TextContent(type="text", text="Not in a voice call in this group")]
    except Exception as e:
        return [TextContent(type="text", text=f"Error leaving group voice: {str(e)}")]

@registry.register(
    name="list_group_dms",
    description="List all Group DMs the user is in",
    input_schema={
        "type": "object",
        "properties": {},
    }
)
async def list_group_dms(arguments: dict):
    groups = [ch for ch in client.private_channels if isinstance(ch, discord.GroupChannel)]
    if not groups:
        return [TextContent(type="text", text="No group DMs found")]
    lines = []
    for g in groups:
        members = ", ".join(m.name for m in g.members)
        lines.append(f"{g.id} - {g.name} ({len(g.members)} members: {members})")
    return [TextContent(type="text", text="\n".join(lines))]
