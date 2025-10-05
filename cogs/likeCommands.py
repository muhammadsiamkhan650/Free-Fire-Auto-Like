import discord
from discord.ext import commands, tasks
from discord import app_commands
import aiohttp
from datetime import datetime, timedelta
import json
import os
import asyncio
from dotenv import load_dotenv

load_dotenv()
API_URL = os.getenv("API_URL")
CONFIG_FILE = "like_channels.json"

class LikeCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.api_host = API_URL
        self.session = aiohttp.ClientSession()
        self.autolike_task = self.auto_like_loop.start()
        self.lock = asyncio.Lock()

    def cog_unload(self):
        self.autolike_task.cancel()
        asyncio.create_task(self.session.close())

    def load_config(self):
        if not os.path.exists(CONFIG_FILE):
            return {"servers": {}}
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)

    def save_config(self, config=None):
        with open(CONFIG_FILE, 'w') as f:
            json.dump(config or self.config, f, indent=4)

    async def check_channel(self, ctx):
        if ctx.guild is None:
            return True
        guild_id = str(ctx.guild.id)
        config = self.load_config()
        allowed_channels = config["servers"].get(guild_id, {}).get("autolike_channels", [])
        return not allowed_channels or str(ctx.channel.id) in allowed_channels

    @commands.hybrid_command(name="setautolikechannel", description="Set channels where auto-like commands can be used.")
    @commands.has_permissions(administrator=True)
    @app_commands.describe(channel="Select the channel to allow or disallow auto-like commands.")
    async def set_autolike_channel(self, ctx: commands.Context, channel: discord.TextChannel):
        if ctx.guild is None:
            await ctx.send("This command can only be used in a server.", ephemeral=True)
            return

        config = self.load_config()
        guild_id = str(ctx.guild.id)
        server_config = config["servers"].setdefault(guild_id, {})
        allowed_channels = server_config.setdefault("autolike_channels", [])

        channel_id_str = str(channel.id)

        if channel_id_str in allowed_channels:
            allowed_channels.remove(channel_id_str)
            self.save_config(config)
            await ctx.send(f"❌ {channel.mention} removed from allowed auto-like channels.", ephemeral=True)
        else:
            allowed_channels.append(channel_id_str)
            self.save_config(config)
            await ctx.send(f"✅ {channel.mention} added as an allowed auto-like channel.", ephemeral=True)

    @tasks.loop(minutes=5)
    async def auto_like_loop(self):
        await self.bot.wait_until_ready()
        config = self.load_config()
        for guild_id, data in config.get('servers', {}).items():
            for uid, entry in list(data.get('auto_likes', {}).items()):
                try:
                    last_sent = datetime.fromisoformat(entry.get('last_sent')) if entry.get('last_sent') else None
                    if not last_sent or (datetime.utcnow() - last_sent >= timedelta(hours=24)):
                        already_liked = await self.check_like_status(entry['server'], uid)
                        if not already_liked:
                            await self.send_like(entry['server'], uid)
                            entry['last_sent'] = datetime.utcnow().isoformat()
                            await asyncio.sleep(2)
                except Exception as e:
                    print(f"Auto-like error for {uid}: {e}")
                    continue
            self.save_config(config)

    async def check_like_status(self, server, uid):
        try:
            async with self.session.get(f"{self.api_host}/check_like?server={server}&uid={uid}") as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get('already_liked', False)
        except Exception as e:
            print(f"Error checking like status for {uid}: {e}")
        return False

    async def send_like(self, server, uid):
        async with self.session.get(f"{self.api_host}/like?server={server}&uid={uid}") as resp:
            return await resp.json()

    @app_commands.command(name="add_autolike", description="Add a UID to auto-like list.")
    @app_commands.describe(server="Server name", uid="Player UID")
    @commands.has_permissions(manage_guild=True)
    async def add_autolike(self, interaction: discord.Interaction, server: str, uid: str):
        ctx = await commands.Context.from_interaction(interaction)
        if not await self.check_channel(ctx):
            await interaction.response.send_message("⚠️ This command is not allowed in this channel.", ephemeral=True)
            return

        async with self.lock:
            config = self.load_config()
            guild_id = str(interaction.guild_id)
            guild_config = config['servers'].setdefault(guild_id, {})
            if 'auto_likes' not in guild_config:
                guild_config['auto_likes'] = {}

            guild_config['auto_likes'][uid] = {
                'server': server,
                'added_by': interaction.user.id,
                'added_at': datetime.utcnow().isoformat(),
                'last_sent': None
            }
            self.save_config(config)

        embed = discord.Embed(title="✅ Added Auto-Like", description=f"UID `{uid}` added for server `{server}`.", color=0x00ff99)
        await interaction.response.send_message(embed=embed, ephemeral=False)

    @app_commands.command(name="remove_autolike", description="Remove UID from auto-like list.")
    @commands.has_permissions(manage_guild=True)
    async def remove_autolike(self, interaction: discord.Interaction, uid: str):
        ctx = await commands.Context.from_interaction(interaction)
        if not await self.check_channel(ctx):
            await interaction.response.send_message("⚠️ This command is not allowed in this channel.", ephemeral=True)
            return

        async with self.lock:
            config = self.load_config()
            guild_id = str(interaction.guild_id)
            if guild_id in config.get('servers', {}) and uid in config['servers'][guild_id].get('auto_likes', {}):
                del config['servers'][guild_id]['auto_likes'][uid]
                self.save_config(config)
                embed = discord.Embed(title="🗑️ Removed", description=f"UID `{uid}` removed from auto-like list.", color=0xff6666)
                await interaction.response.send_message(embed=embed)
            else:
                embed = discord.Embed(title="⚠️ Not Found", description=f"UID `{uid}` not found in auto-like list.", color=0xffcc00)
                msg = await interaction.response.send_message(embed=embed, ephemeral=False)
                await asyncio.sleep(5)
                await interaction.delete_original_response()

    @app_commands.command(name="list_autolikes", description="List all auto-like UIDs.")
    async def list_autolikes(self, interaction: discord.Interaction):
        ctx = await commands.Context.from_interaction(interaction)
        if not await self.check_channel(ctx):
            await interaction.response.send_message("⚠️ This command is not allowed in this channel.", ephemeral=True)
            return

        config = self.load_config()
        guild_id = str(interaction.guild_id)
        data = config.get('servers', {}).get(guild_id, {}).get('auto_likes', {})
        if not data:
            embed = discord.Embed(title="ℹ️ No Auto-Likes", description="No UIDs have been added yet.", color=0xcccccc)
            msg = await interaction.response.send_message(embed=embed, ephemeral=False)
            await asyncio.sleep(5)
            await interaction.delete_original_response()
            return

        desc = "\n".join([f"`{uid}` - Server: `{v['server']}` | Last Sent: `{v['last_sent'] or 'Never'}`" for uid, v in data.items()])
        embed = discord.Embed(title="📋 Auto-Like List", description=desc, color=0x00bfff)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="clear_autolikes", description="Clear all auto-like entries.")
    @commands.has_permissions(manage_guild=True)
    async def clear_autolikes(self, interaction: discord.Interaction):
        ctx = await commands.Context.from_interaction(interaction)
        if not await self.check_channel(ctx):
            await interaction.response.send_message("⚠️ This command is not allowed in this channel.", ephemeral=True)
            return

        async with self.lock:
            config = self.load_config()
            guild_id = str(interaction.guild_id)
            if guild_id in config.get('servers', {}):
                config['servers'][guild_id]['auto_likes'] = {}
                self.save_config(config)
                embed = discord.Embed(title="🧹 Cleared", description="All auto-likes have been removed.", color=0x33cc33)
                await interaction.response.send_message(embed=embed)
            else:
                embed = discord.Embed(title="⚠️ Nothing to clear", color=0xffcc00)
                msg = await interaction.response.send_message(embed=embed, ephemeral=False)
                await asyncio.sleep(5)
                await interaction.delete_original_response()

async def setup(bot):
    await bot.add_cog(LikeCommands(bot))
