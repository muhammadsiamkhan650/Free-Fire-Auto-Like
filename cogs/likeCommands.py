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
            return {}
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)

    def save_config(self, config=None):
        with open(CONFIG_FILE, 'w') as f:
            json.dump(config or self.config, f, indent=4)

    @tasks.loop(minutes=5)
    async def auto_like_loop(self):
        await self.bot.wait_until_ready()
        config = self.load_config()
        for guild_id, data in config.items():
            for uid, entry in list(data.get('auto_likes', {}).items()):
                last_sent = datetime.fromisoformat(entry['last_sent']) if 'last_sent' in entry else None
                if not last_sent or (datetime.utcnow() - last_sent >= timedelta(hours=24)):
                    try:
                        await self.send_like(entry['server'], uid)
                        entry['last_sent'] = datetime.utcnow().isoformat()
                        await asyncio.sleep(2)
                    except Exception:
                        continue
            self.save_config(config)

    async def send_like(self, server, uid):
        async with self.session.get(f"{self.api_host}/like?server={server}&uid={uid}") as resp:
            return await resp.json()

    @app_commands.command(name="add_autolike", description="Add a UID to auto-like list.")
    @app_commands.describe(server="Server name", uid="Player UID")
    @commands.has_permissions(manage_guild=True)
    async def add_autolike(self, interaction: discord.Interaction, server: str, uid: str):
        async with self.lock:
            config = self.load_config()
            guild_id = str(interaction.guild_id)
            if guild_id not in config:
                config[guild_id] = {"auto_likes": {}}
            config[guild_id]['auto_likes'][uid] = {
                'server': server,
                'added_by': interaction.user.id,
                'added_at': datetime.utcnow().isoformat(),
                'last_sent': datetime.utcnow().isoformat()
            }
            self.save_config(config)

        embed = discord.Embed(title="✅ Added Auto-Like", description=f"UID `{uid}` added for server `{server}`.", color=0x00ff99)
        await interaction.response.send_message(embed=embed, ephemeral=False)

    @app_commands.command(name="remove_autolike", description="Remove UID from auto-like list.")
    @commands.has_permissions(manage_guild=True)
    async def remove_autolike(self, interaction: discord.Interaction, uid: str):
        async with self.lock:
            config = self.load_config()
            guild_id = str(interaction.guild_id)
            if guild_id in config and uid in config[guild_id].get('auto_likes', {}):
                del config[guild_id]['auto_likes'][uid]
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
        config = self.load_config()
        guild_id = str(interaction.guild_id)
        data = config.get(guild_id, {}).get('auto_likes', {})
        if not data:
            embed = discord.Embed(title="ℹ️ No Auto-Likes", description="No UIDs have been added yet.", color=0xcccccc)
            msg = await interaction.response.send_message(embed=embed, ephemeral=False)
            await asyncio.sleep(5)
            await interaction.delete_original_response()
            return

        desc = "\n".join([f"`{uid}` - Server: `{v['server']}`" for uid, v in data.items()])
        embed = discord.Embed(title="📋 Auto-Like List", description=desc, color=0x00bfff)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="clear_autolikes", description="Clear all auto-like entries.")
    @commands.has_permissions(manage_guild=True)
    async def clear_autolikes(self, interaction: discord.Interaction):
        async with self.lock:
            config = self.load_config()
            guild_id = str(interaction.guild_id)
            if guild_id in config:
                config[guild_id]['auto_likes'] = {}
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
