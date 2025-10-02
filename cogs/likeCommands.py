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
        self.config_data = self.load_config()
        self.session = aiohttp.ClientSession()
        self.auto_like_task.start()

    # === CONFIG ===
    def load_config(self):
        default_config = {"servers": {}}
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r") as f:
                    loaded_config = json.load(f)
                    loaded_config.setdefault("servers", {})
                    return loaded_config
            except json.JSONDecodeError:
                print("⚠️ WARNING: Corrupt config. Resetting.")
        self.save_config(default_config)
        return default_config

    def save_config(self, config_to_save=None):
        data_to_save = config_to_save if config_to_save else self.config_data
        temp_file = CONFIG_FILE + ".tmp"
        with open(temp_file, "w") as f:
            json.dump(data_to_save, f, indent=4)
        os.replace(temp_file, CONFIG_FILE)

    # === UTILS: EMBED SYSTEM ===
    def make_embed(self, title, description, color, footer="Panther Corporation", delete_after=None):
        embed = discord.Embed(
            title=title,
            description=description,
            color=color,
            timestamp=datetime.now()
        )
        embed.set_footer(text=footer)
        return embed, delete_after

    async def send_embed(self, ctx, title, description, color=discord.Color.blue(), footer="Panther Corporation", delete_after=10):
        embed, da = self.make_embed(title, description, color, footer, delete_after)
        await ctx.send(embed=embed, delete_after=da)

    # === ADD UID ===
    @commands.hybrid_command(
        name="addautolike", description="Add a player UID to auto-like every 24h"
    )
    @app_commands.describe(server="Server region", uid="Player UID")
    async def add_auto_like(self, ctx: commands.Context, server: str, uid: str):
        if not uid.isdigit() or len(uid) < 6:
            return await self.send_embed(ctx, "⚠️ Invalid UID", "UID must be numbers and at least 6 digits.", discord.Color.red())

        guild_id = str(ctx.guild.id)
        server_config = self.config_data["servers"].setdefault(guild_id, {})
        auto_list = server_config.setdefault("auto_like_list", [])

        if any(e["uid"] == uid and e["server"] == server for e in auto_list):
            return await self.send_embed(ctx, "⚠️ Already Exists", f"UID `{uid}` ({server}) is already in auto-like list.", discord.Color.orange())

        entry = {"uid": uid, "server": server, "last_liked": None}
        auto_list.append(entry)
        self.save_config()

        await self.send_embed(ctx, "✅ Added to Auto-Like",
                              f"UID `{uid}` ({server}) added.\nIt will receive likes automatically every 24h.",
                              discord.Color.green())

    # === REMOVE UID ===
    @commands.hybrid_command(
        name="removeautolike", description="Remove a player UID from the auto-like list"
    )
    @app_commands.describe(server="Server region", uid="Player UID")
    async def remove_auto_like(self, ctx: commands.Context, server: str, uid: str):
        guild_id = str(ctx.guild.id)
        server_config = self.config_data["servers"].setdefault(guild_id, {})
        auto_list = server_config.setdefault("auto_like_list", [])

        entry = next((e for e in auto_list if e["uid"] == uid and e["server"] == server), None)
        if not entry:
            return await self.send_embed(ctx, "⚠️ Not Found", f"UID `{uid}` ({server}) is not in the auto-like list.", discord.Color.red())

        auto_list.remove(entry)
        self.save_config()

        await self.send_embed(ctx, "🗑️ Removed from Auto-Like",
                              f"UID `{uid}` ({server}) has been removed from auto-like list.",
                              discord.Color.orange())

    # === LIST UID ===
    @commands.hybrid_command(
        name="listautolike", description="Show all UIDs currently in the auto-like list"
    )
    async def list_auto_like(self, ctx: commands.Context):
        guild_id = str(ctx.guild.id)
        server_config = self.config_data["servers"].setdefault(guild_id, {})
        auto_list = server_config.setdefault("auto_like_list", [])

        if not auto_list:
            return await self.send_embed(ctx, "📭 Auto-Like List", "No UIDs are in the auto-like list.", discord.Color.orange())

        embed = discord.Embed(
            title="📌 Auto-Like List (with cooldown)",
            color=discord.Color.blue(),
            timestamp=datetime.now()
        )
        embed.set_footer(text="Panther Corporation")

        for i, entry in enumerate(auto_list, start=1):
            last_liked = entry.get("last_liked")
            if last_liked:
                last_dt = datetime.fromisoformat(last_liked)
                next_time = last_dt + timedelta(hours=24)
                remaining = next_time - datetime.now()
                if remaining.total_seconds() > 0:
                    hours, remainder = divmod(int(remaining.total_seconds()), 3600)
                    minutes, _ = divmod(remainder, 60)
                    timer_text = f"⏳ {hours}h {minutes}m left"
                else:
                    timer_text = "✅ Ready for next like"
            else:
                timer_text = "✅ Not liked yet"

            embed.add_field(
                name=f"{i}. UID: {entry['uid']}",
                value=f"🌍 Server: {entry['server']}\n{timer_text}",
                inline=False
            )

        await ctx.send(embed=embed)

    # === SET AUTO LIKE CHANNEL ===
    @commands.hybrid_command(
        name="setautolikechannel", description="Set which channel auto-like updates will be posted in"
    )
    @commands.has_permissions(administrator=True)
    @app_commands.describe(channel="Channel where auto-like updates will appear")
    async def set_auto_like_channel(self, ctx: commands.Context, channel: discord.TextChannel):
        guild_id = str(ctx.guild.id)
        server_config = self.config_data["servers"].setdefault(guild_id, {})
        server_config["auto_like_channel"] = str(channel.id)
        self.save_config()

        await self.send_embed(ctx, "✅ Channel Set",
                              f"Auto-like updates will now be sent in {channel.mention}.",
                              discord.Color.green())

    # === AUTO TASK ===
    @tasks.loop(hours=24)
    async def auto_like_task(self):
        print("⏳ Running auto-like task...")
        for guild_id, server_config in self.config_data["servers"].items():
            auto_list = server_config.get("auto_like_list", [])
            channel_id = server_config.get("auto_like_channel")
            channel = None
            if channel_id:
                channel = self.bot.get_channel(int(channel_id))

            for entry in auto_list:
                uid = entry["uid"]
                server = entry["server"]

                try:
                    url = f"{self.api_host}/like?uid={uid}&server={server}"
                    async with self.session.get(url) as response:
                        if response.status == 200:
                            data = await response.json()
                            if data.get("status") == 1:
                                entry["last_liked"] = datetime.now().isoformat()
                                print(f"✅ Auto-liked {uid} ({server})")
                                if channel:
                                    embed, _ = self.make_embed("✅ Auto-Like Success",
                                        f"UID `{uid}` ({server}) has been auto-liked successfully!",
                                        discord.Color.green())
                                    await channel.send(embed=embed)
                            else:
                                print(f"❌ Failed auto-like {uid} ({server}) - Already max today")
                                if channel:
                                    embed, _ = self.make_embed("⚠️ Auto-Like Skipped",
                                        f"UID `{uid}` ({server}) already reached max likes today.",
                                        discord.Color.orange())
                                    await channel.send(embed=embed)
                        else:
                            print(f"⚠️ API Error: {response.status}")
                except Exception as e:
                    print(f"Error in auto_like_task: {e}")

            self.save_config()  # save after finishing guild loop

    @auto_like_task.before_loop
    async def before_auto_like(self):
        await self.bot.wait_until_ready()
        print("✅ Auto-like task ready.")

    def cog_unload(self):
        self.bot.loop.create_task(self.session.close())
        self.auto_like_task.cancel()


async def setup(bot):
    await bot.add_cog(LikeCommands(bot))
