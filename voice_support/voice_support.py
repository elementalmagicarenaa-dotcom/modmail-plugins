import discord
from discord.ext import commands

from core import checks
from core.models import PermissionLevel, getLogger

logger = getLogger(__name__)


class VoiceSupport(commands.Cog):
    """A plugin that provides voice support to users."""

    def __init__(self, bot):
        self.bot = bot
        self.db = bot.db["plugins.VoiceSupport"]
        self.config = {}
        self.bot.loop.create_task(self.load_config())

    async def load_config(self):
        config = await self.db.find_one({"_id": "config"})
        if config is None:
            config = {
                "_id": "config",
                "enabled": False,
                "voice_channel_id": None,
                "notification_channel_id": None,
                "staff_role_id": None,
                "waiting_music_path": None,
                "notification_message": "{staff_role} User {user} is waiting for support in {channel}.",
            }
            await self.db.insert_one(config)
        self.config = config

    async def update_config(self):
        self.config = await self.db.find_one({"_id": "config"})

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        await self.update_config()
        if not self.config.get("enabled"):
            return

        voice_channel_id = self.config.get("voice_channel_id")
        if not voice_channel_id:
            return

        # User joins the target channel
        if after.channel and after.channel.id == voice_channel_id:
            is_first_user = not any(not m.bot for m in after.channel.members if m != member)

            if is_first_user:
                if not member.guild.voice_client or not member.guild.voice_client.is_connected():
                    try:
                        await after.channel.connect()
                    except Exception as e:
                        logger.error(f"Failed to connect to voice channel {voice_channel_id}: {e}")
                        return
                elif member.guild.voice_client.channel != after.channel:
                    await member.guild.voice_client.move_to(after.channel)

                vc = member.guild.voice_client

                music_path = self.config.get("waiting_music_path")
                if music_path and not vc.is_playing():
                    def play_loop(error=None):
                        if error:
                            logger.error(f"Player error: {error}")
                        if vc.is_connected() and not vc.is_playing():
                            try:
                                vc.play(discord.FFmpegPCMAudio(music_path), after=play_loop)
                            except Exception as e:
                                logger.error(f"Error playing audio: {e}")
                    try:
                        vc.play(discord.FFmpegPCMAudio(music_path), after=play_loop)
                    except Exception as e:
                        logger.error(f"Error playing audio: {e}")

                notification_channel_id = self.config.get("notification_channel_id")
                staff_role_id = self.config.get("staff_role_id")
                notification_message = self.config.get("notification_message")

                if notification_channel_id and staff_role_id and notification_message:
                    notification_channel = self.bot.get_channel(notification_channel_id)
                    staff_role = member.guild.get_role(staff_role_id)

                    if notification_channel and staff_role:
                        message = notification_message.format(
                            staff_role=staff_role.mention,
                            user=member.mention,
                            channel=after.channel.mention,
                        )
                        await notification_channel.send(message)

        # User leaves the target channel
        elif before.channel and before.channel.id == voice_channel_id:
            is_bot_alone = len(before.channel.members) == 1 and self.bot.user in before.channel.members

            if is_bot_alone:
                if before.channel.guild.voice_client:
                    await before.channel.guild.voice_client.disconnect()

    @commands.group(invoke_without_command=True)
    @checks.has_permissions(PermissionLevel.ADMINISTRATOR)
    async def voicesupport(self, ctx):
        """Configure the Voice Support plugin."""
        await ctx.send_help(ctx.command)

    @voicesupport.command(name="config")
    @checks.has_permissions(PermissionLevel.ADMINISTRATOR)
    async def show_config(self, ctx, key: str = None, *, value: str = None):
        """Shows or sets configuration. Usage: ?voicesupport config [key] [value]"""
        await self.update_config()

        if key and value:
            valid_keys = ["enabled", "voice_channel_id", "notification_channel_id", "staff_role_id", "waiting_music_path", "notification_message"]
            if key not in valid_keys:
                return await ctx.send(f"Invalid key. Valid keys are: `{', '.join(valid_keys)}`")

            if key == "enabled":
                new_value = value.lower() in ("true", "yes", "1", "on")
            elif key.endswith("_id"):
                try:
                    new_value = int(value)
                except ValueError:
                    return await ctx.send("ID must be a number.")
            else:
                new_value = value

            await self.db.update_one({"_id": "config"}, {"$set": {key: new_value}}, upsert=True)
            await self.update_config()
            await ctx.send(f"Set `{key}` to `{new_value}`.")
        else:
            embed = discord.Embed(title="Voice Support Configuration", color=self.bot.main_color)
            for key, value in self.config.items():
                if key == "_id":
                    continue
                embed.add_field(name=key, value=f"`{value}`" if value is not None else "Not Set", inline=False)
            await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(VoiceSupport(bot))
