import discord
from discord.ext import commands, tasks
from discord import app_commands
import aiohttp
from datetime import datetime
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
        self.config_data = self.load_config()
        self.session = aiohttp.ClientSession()
        self.auto_like_task.start()  # background task চালু

    def load_config(self):
        default_config = {"servers": {}}
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r") as f:
                    loaded_config = json.load(f)
                    loaded_config.setdefault("servers", {})
                    return loaded_config
            except json.JSONDecodeError:
                print(f"WARNING: Corrupt config. Resetting.")
        self.save_config(default_config)
        return default_config

    def save_config(self, config_to_save=None):
        data_to_save = config_to_save if config_to_save else self.config_data
        temp_file = CONFIG_FILE + ".tmp"
        with open(temp_file, "w") as f:
            json.dump(data_to_save, f, indent=4)
        os.replace(temp_file, CONFIG_FILE)

    # === Set Auto-Like Channel ===
    @commands.hybrid_command(
        name="setautolikechannel", description="Set the channel where auto-like logs will be sent"
    )
    async def set_auto_like_channel(self, ctx: commands.Context, channel: discord.TextChannel):
        guild_id = str(ctx.guild.id)
        server_config = self.config_data["servers"].setdefault(guild_id, {})
        server_config["auto_like_channel"] = channel.id
        self.save_config()

        await ctx.send(
            f"✅ Auto-Like log channel set to {channel.mention}",
            delete_after=10
        )

    # === Add UID ===
    @commands.hybrid_command(
        name="addautolike", description="Add a player UID to auto-like every 24h"
    )
    @app_commands.describe(server="Server region", uid="Player UID")
    async def add_auto_like(self, ctx: commands.Context, server: str, uid: str):
        if not uid.isdigit() or len(uid) < 6:
            return await ctx.send("⚠️ Invalid UID.", delete_after=8)

        guild_id = str(ctx.guild.id)
        server_config = self.config_data["servers"].setdefault(guild_id, {})
        auto_list = server_config.setdefault("auto_like_list", [])

        entry = {"uid": uid, "server": server}
        if entry in auto_list:
            return await ctx.send("⚠️ This UID is already in auto-like list.", delete_after=8)

        auto_list.append(entry)
        self.save_config()

        await ctx.send(
            f"✅ UID `{uid}` ({server}) added to auto-like list. It will receive likes every 24h.",
            delete_after=10
        )

    # === Remove UID ===
    @commands.hybrid_command(
        name="removeautolike", description="Remove a player UID from the auto-like list"
    )
    @app_commands.describe(server="Server region", uid="Player UID")
    async def remove_auto_like(self, ctx: commands.Context, server: str, uid: str):
        guild_id = str(ctx.guild.id)
        server_config = self.config_data["servers"].setdefault(guild_id, {})
        auto_list = server_config.setdefault("auto_like_list", [])

        entry = {"uid": uid, "server": server}
        if entry not in auto_list:
            return await ctx.send("⚠️ This UID is not in the auto-like list.", delete_after=8)

        auto_list.remove(entry)
        self.save_config()

        await ctx.send(
            f"🗑️ UID `{uid}` ({server}) has been removed from the auto-like list.",
            delete_after=10
        )

    # === List UIDs ===
    @commands.hybrid_command(
        name="listautolike", description="Show all UIDs currently in the auto-like list"
    )
    async def list_auto_like(self, ctx: commands.Context):
        guild_id = str(ctx.guild.id)
        server_config = self.config_data["servers"].setdefault(guild_id, {})
        auto_list = server_config.setdefault("auto_like_list", [])

        if not auto_list:
            return await ctx.send("📭 No UIDs are in the auto-like list.", delete_after=8)

        embed = discord.Embed(
            title="📌 Auto-Like List",
            color=discord.Color.blue(),
            timestamp=datetime.now()
        )

        for i, entry in enumerate(auto_list, start=1):
            embed.add_field(
                name=f"{i}. UID: {entry['uid']}",
                value=f"🌍 Server: {entry['server']}",
                inline=False
            )

        await ctx.send(embed=embed)

    # === Auto Task ===
    @tasks.loop(hours=24)
    async def auto_like_task(self):
        print("⏳ Running auto-like task...")
        for guild_id, server_config in self.config_data["servers"].items():
            auto_list = server_config.get("auto_like_list", [])
            log_channel_id = server_config.get("auto_like_channel")

            log_channel = None
            if log_channel_id:
                log_channel = self.bot.get_channel(log_channel_id)

            for entry in auto_list:
                uid = entry["uid"]
                server = entry["server"]

                try:
                    url = f"{self.api_host}/like?uid={uid}&server={server}"
                    async with self.session.get(url) as response:
                        if response.status == 200:
                            data = await response.json()
                            if data.get("status") == 1:
                                msg = f"✅ Auto-liked `{uid}` ({server})"
                            else:
                                msg = f"❌ Failed auto-like `{uid}` ({server}) - Already max today"
                        else:
                            msg = f"⚠️ API Error: {response.status}"

                        print(msg)
                        if log_channel:
                            await log_channel.send(msg)

                except Exception as e:
                    print(f"Error in auto_like_task: {e}")
                    if log_channel:
                        await log_channel.send(f"⚠️ Error: {e}")

    @auto_like_task.before_loop
    async def before_auto_like(self):
        await self.bot.wait_until_ready()
        print("✅ Auto-like task ready.")

    def cog_unload(self):
        self.bot.loop.create_task(self.session.close())
        self.auto_like_task.cancel()

async def setup(bot):
    await bot.add_cog(LikeCommands(bot))
