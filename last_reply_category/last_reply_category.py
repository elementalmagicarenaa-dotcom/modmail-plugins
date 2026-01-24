"""
Last Reply Category Plugin - Advanced
Moves threads between categories based on who replied last with advanced features.
"""

import discord
from discord.ext import commands

from core import checks
from core.models import PermissionLevel
from core.utils import getLogger

logger = getLogger(__name__)


class LastReplyCategory(commands.Cog):
    """Advanced thread categorization based on last reply."""

    def __init__(self, bot):
        self.bot = bot
        self.db = bot.api.get_plugin_partition(self)
        self.stats = {"mod_moves": 0, "user_moves": 0}

    async def _get_config(self):
        config = await self.db.find_one({"_id": "config"})
        if not config:
            config = {"enabled": True, "mod_category": None, "user_category": None, "exclude_categories": [], "show_status": False, "log_moves": False}
        return config

    async def _update_config(self, updates):
        await self.db.update_one({"_id": "config"}, {"$set": updates}, upsert=True)

    async def _update_status(self, thread, status_type, config):
        if not config.get("show_status"):
            return
        
        emoji = "⏳" if status_type == "user" else "✅"
        status = "Waiting for User" if status_type == "mod" else "Waiting for Moderator"
        
        try:
            topic = thread.channel.topic or ""
            if "│" in topic:
                topic = topic.split("│")[0].strip()
            await thread.channel.edit(topic=f"{topic} │ {emoji} {status}")
        except (discord.Forbidden, discord.HTTPException):
            pass

    @commands.Cog.listener()
    async def on_thread_reply(self, thread, from_mod, message, anonymous, plain):
        if not from_mod:
            return
        
        config = await self._get_config()
        if not config.get("enabled") or thread.channel.category_id in config.get("exclude_categories", []):
            return

        target_id = config.get("mod_category")
        if not target_id:
            return

        try:
            target_category = self.bot.modmail_guild.get_channel(int(target_id))
            if target_category and thread.channel.category_id != target_category.id:
                await thread.channel.edit(category=target_category, reason="Moderator replied")
                await self._update_status(thread, "mod", config)
                self.stats["mod_moves"] += 1
                
                if config.get("log_moves"):
                    logger.info(f"Moved thread {thread.id} to {target_category.name} (mod reply)")
        except (ValueError, AttributeError, discord.Forbidden, discord.HTTPException) as e:
            logger.warning("Failed to move thread after mod reply: %s", e)

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot or not isinstance(message.channel, discord.DMChannel):
            return

        config = await self._get_config()
        if not config.get("enabled"):
            return

        thread = await self.bot.threads.find(recipient=message.author)
        if not thread or not thread.ready or thread.channel.category_id in config.get("exclude_categories", []):
            return

        target_id = config.get("user_category")
        if not target_id:
            return

        try:
            target_category = self.bot.modmail_guild.get_channel(int(target_id))
            if target_category and thread.channel.category_id != target_category.id:
                await thread.channel.edit(category=target_category, reason="User replied")
                await self._update_status(thread, "user", config)
                self.stats["user_moves"] += 1
                
                if config.get("log_moves"):
                    logger.info(f"Moved thread {thread.id} to {target_category.name} (user reply)")
        except (ValueError, AttributeError, discord.Forbidden, discord.HTTPException) as e:
            logger.warning("Failed to move thread after user reply: %s", e)

    @commands.group(invoke_without_command=True)
    @checks.has_permissions(PermissionLevel.MODERATOR)
    async def lastreply(self, ctx):
        """Manage last reply category settings."""
        config = await self._get_config()
        
        mod_cat = config.get("mod_category")
        user_cat = config.get("user_category")
        mod_name = self.bot.modmail_guild.get_channel(int(mod_cat)).name if mod_cat else "Not set"
        user_name = self.bot.modmail_guild.get_channel(int(user_cat)).name if user_cat else "Not set"
        
        embed = discord.Embed(title="Last Reply Category Settings", color=self.bot.main_color)
        embed.add_field(name="Status", value="🟢 Enabled" if config.get("enabled") else "🔴 Disabled", inline=False)
        embed.add_field(name="Mod Reply Category", value=mod_name, inline=True)
        embed.add_field(name="User Reply Category", value=user_name, inline=True)
        embed.add_field(name="Stats", value=f"Mod moves: {self.stats['mod_moves']}\nUser moves: {self.stats['user_moves']}", inline=False)
        await ctx.send(embed=embed)

    @lastreply.command(name="setmod")
    @checks.has_permissions(PermissionLevel.MODERATOR)
    async def setmod(self, ctx, category: discord.CategoryChannel):
        """Set category for mod replies."""
        await self._update_config({"mod_category": category.id})
        await ctx.send(f"✅ Mod reply category: **{category.name}**")

    @lastreply.command(name="setuser")
    @checks.has_permissions(PermissionLevel.MODERATOR)
    async def setuser(self, ctx, category: discord.CategoryChannel):
        """Set category for user replies."""
        await self._update_config({"user_category": category.id})
        await ctx.send(f"✅ User reply category: **{category.name}**")

    @lastreply.command(name="toggle")
    @checks.has_permissions(PermissionLevel.MODERATOR)
    async def toggle(self, ctx):
        """Enable/disable the plugin."""
        config = await self._get_config()
        current = config.get("enabled", True)
        await self._update_config({"enabled": not current})
        await ctx.send(f"{'🟢 Enabled' if not current else '🔴 Disabled'} last reply categorization.")

    @lastreply.command(name="exclude")
    @checks.has_permissions(PermissionLevel.MODERATOR)
    async def exclude(self, ctx, category: discord.CategoryChannel):
        """Exclude a category from auto-moving."""
        config = await self._get_config()
        excluded = config.get("exclude_categories", [])
        if category.id in excluded:
            excluded.remove(category.id)
            await ctx.send(f"✅ Removed **{category.name}** from exclusions.")
        else:
            excluded.append(category.id)
            await ctx.send(f"✅ Added **{category.name}** to exclusions.")
        await self._update_config({"exclude_categories": excluded})

    @lastreply.command(name="status")
    @checks.has_permissions(PermissionLevel.MODERATOR)
    async def status_toggle(self, ctx):
        """Toggle status indicators in thread topics."""
        config = await self._get_config()
        current = config.get("show_status", False)
        await self._update_config({"show_status": not current})
        await ctx.send(f"{'🟢 Enabled' if not current else '🔴 Disabled'} status indicators.")

    @lastreply.command(name="logging")
    @checks.has_permissions(PermissionLevel.MODERATOR)
    async def logging_toggle(self, ctx):
        """Toggle move logging."""
        config = await self._get_config()
        current = config.get("log_moves", False)
        await self._update_config({"log_moves": not current})
        await ctx.send(f"{'🟢 Enabled' if not current else '🔴 Disabled'} move logging.")


async def setup(bot):
    await bot.add_cog(LastReplyCategory(bot))
