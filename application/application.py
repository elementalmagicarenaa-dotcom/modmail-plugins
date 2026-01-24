"""
Application Plugin - Interactive Staff Application System
"""

import discord
from discord.ext import commands
from discord import ui
from datetime import datetime
from core import checks
from core.models import PermissionLevel
from core.utils import getLogger

logger = getLogger(__name__)


class ApplicationModal(ui.Modal):
    def __init__(self, questions, plugin_instance):
        super().__init__(title="Staff Application")
        self.questions = questions
        self.plugin = plugin_instance
        for i, q in enumerate(questions[:5]):
            self.add_item(ui.TextInput(label=q["question"][:45], style=discord.TextStyle.paragraph if q.get("long") else discord.TextStyle.short, required=q.get("required", True), max_length=1024, placeholder=f"Your answer here..."))

    async def on_submit(self, interaction: discord.Interaction):
        answers = {self.questions[i]["question"]: child.value for i, child in enumerate(self.children)}
        await self.plugin.submit_application(interaction, answers)


class ApplicationButtons(ui.View):
    def __init__(self, plugin_instance, app_id, user_id):
        super().__init__(timeout=None)
        self.plugin = plugin_instance
        self.app_id = app_id
        self.user_id = user_id

    @ui.button(label="✅ Accept", style=discord.ButtonStyle.success, custom_id="app_accept")
    async def accept(self, interaction: discord.Interaction, button: ui.Button):
        await self.plugin.handle_decision(interaction, self.app_id, self.user_id, True)

    @ui.button(label="❌ Deny", style=discord.ButtonStyle.danger, custom_id="app_deny")
    async def deny(self, interaction: discord.Interaction, button: ui.Button):
        await self.plugin.handle_decision(interaction, self.app_id, self.user_id, False)

    @ui.button(label="📝 Notes", style=discord.ButtonStyle.secondary, custom_id="app_notes")
    async def notes(self, interaction: discord.Interaction, button: ui.Button):
        modal = ui.Modal(title="Add Review Notes")
        modal.add_item(ui.TextInput(label="Notes", style=discord.TextStyle.paragraph, max_length=500))
        
        async def on_submit_notes(inter):
            note = modal.children[0].value
            await self.plugin.db.update_one({"_id": self.app_id}, {"$push": {"notes": {"reviewer": inter.user.id, "note": note, "time": datetime.utcnow()}}})
            await inter.response.send_message(f"✅ Note added!", ephemeral=True)
        
        modal.on_submit = on_submit_notes
        await interaction.response.send_modal(modal)


class SetupView(ui.View):
    def __init__(self, plugin_instance, ctx):
        super().__init__(timeout=180)
        self.plugin = plugin_instance
        self.ctx = ctx
        self.config = {}

    @ui.button(label="📢 Set Channel", style=discord.ButtonStyle.primary, row=0)
    async def set_channel(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_message("Please mention the channel where applications will be posted:", ephemeral=True)
        
        def check(m):
            return m.author == interaction.user and m.channel == interaction.channel and m.channel_mentions
        
        try:
            msg = await self.plugin.bot.wait_for('message', timeout=60.0, check=check)
            channel = msg.channel_mentions[0]
            await self.plugin._update_config({"channel": channel.id})
            self.config['channel'] = channel
            await msg.add_reaction("✅")
            await self.update_embed(interaction)
        except:
            pass

    @ui.button(label="👥 Set Role", style=discord.ButtonStyle.primary, row=0)
    async def set_role(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_message("Please mention the role to give accepted applicants:", ephemeral=True)
        
        def check(m):
            return m.author == interaction.user and m.channel == interaction.channel and m.role_mentions
        
        try:
            msg = await self.plugin.bot.wait_for('message', timeout=60.0, check=check)
            role = msg.role_mentions[0]
            await self.plugin._update_config({"role": role.id})
            self.config['role'] = role
            await msg.add_reaction("✅")
            await self.update_embed(interaction)
        except:
            pass

    @ui.button(label="❓ Add Question", style=discord.ButtonStyle.success, row=1)
    async def add_question(self, interaction: discord.Interaction, button: ui.Button):
        modal = ui.Modal(title="Add Application Question")
        modal.add_item(ui.TextInput(label="Question", style=discord.TextStyle.short, max_length=100))
        modal.add_item(ui.TextInput(label="Answer Type (short/long)", style=discord.TextStyle.short, max_length=5, placeholder="short"))
        modal.add_item(ui.TextInput(label="Required? (yes/no)", style=discord.TextStyle.short, max_length=3, placeholder="yes"))
        
        async def on_submit_q(inter):
            config = await self.plugin._get_config()
            questions = config.get("questions", [])
            if len(questions) >= 5:
                return await inter.response.send_message("❌ Maximum 5 questions!", ephemeral=True)
            
            q_text = modal.children[0].value
            q_type = modal.children[1].value.lower() == "long"
            q_req = modal.children[2].value.lower() != "no"
            
            questions.append({"question": q_text, "long": q_type, "required": q_req})
            await self.plugin._update_config({"questions": questions})
            await inter.response.send_message(f"✅ Added question: {q_text}", ephemeral=True)
            await self.update_embed(inter)
        
        modal.on_submit = on_submit_q
        await interaction.response.send_modal(modal)

    @ui.button(label="🗑️ Remove Question", style=discord.ButtonStyle.danger, row=1)
    async def remove_question(self, interaction: discord.Interaction, button: ui.Button):
        config = await self.plugin._get_config()
        questions = config.get("questions", [])
        if not questions:
            return await interaction.response.send_message("❌ No questions to remove!", ephemeral=True)
        
        options = [discord.SelectOption(label=f"{i+1}. {q['question'][:50]}", value=str(i)) for i, q in enumerate(questions)]
        select = ui.Select(placeholder="Select question to remove", options=options)
        
        async def select_callback(inter):
            idx = int(select.values[0])
            questions.pop(idx)
            await self.plugin._update_config({"questions": questions})
            await inter.response.send_message(f"✅ Question removed!", ephemeral=True)
            await self.update_embed(inter)
        
        select.callback = select_callback
        view = ui.View(timeout=60)
        view.add_item(select)
        await interaction.response.send_message("Select a question to remove:", view=view, ephemeral=True)

    @ui.button(label="🟢 Open Applications", style=discord.ButtonStyle.success, row=2)
    async def toggle_open(self, interaction: discord.Interaction, button: ui.Button):
        await self.plugin._update_config({"enabled": True})
        await interaction.response.send_message("✅ Applications opened!", ephemeral=True)
        await self.update_embed(interaction)

    @ui.button(label="🔴 Close Applications", style=discord.ButtonStyle.danger, row=2)
    async def toggle_close(self, interaction: discord.Interaction, button: ui.Button):
        await self.plugin._update_config({"enabled": False})
        await interaction.response.send_message("🔴 Applications closed!", ephemeral=True)
        await self.update_embed(interaction)

    @ui.button(label="✅ Done", style=discord.ButtonStyle.primary, row=3)
    async def done(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_message("✅ Setup complete!", ephemeral=True)
        self.stop()

    async def update_embed(self, interaction):
        config = await self.plugin._get_config()
        embed = await self.plugin.create_setup_embed(config)
        try:
            await interaction.message.edit(embed=embed)
        except:
            pass


class Application(commands.Cog):
    """Interactive staff application system."""

    def __init__(self, bot):
        self.bot = bot
        self.db = bot.api.get_plugin_partition(self)

    async def _get_config(self):
        config = await self.db.find_one({"_id": "config"})
        return config or {"enabled": False, "channel": None, "questions": [], "role": None, "dm_response": True}

    async def _update_config(self, updates):
        await self.db.update_one({"_id": "config"}, {"$set": updates}, upsert=True)

    async def create_setup_embed(self, config):
        channel = self.bot.get_channel(int(config["channel"])) if config.get("channel") else None
        role = self.bot.modmail_guild.get_role(int(config["role"])) if config.get("role") else None
        
        embed = discord.Embed(title="📋 Application Setup Panel", color=0x5865F2)
        embed.add_field(name="Status", value="🟢 Open" if config.get("enabled") else "🔴 Closed", inline=True)
        embed.add_field(name="Channel", value=channel.mention if channel else "❌ Not set", inline=True)
        embed.add_field(name="Role", value=role.mention if role else "❌ Not set", inline=True)
        
        questions = config.get("questions", [])
        if questions:
            q_list = "\n".join([f"{i+1}. {q['question'][:50]} ({'Long' if q['long'] else 'Short'}, {'Required' if q['required'] else 'Optional'})" for i, q in enumerate(questions)])
            embed.add_field(name=f"Questions ({len(questions)}/5)", value=q_list, inline=False)
        else:
            embed.add_field(name="Questions (0/5)", value="❌ No questions added", inline=False)
        
        embed.set_footer(text="Use the buttons below to configure your application system")
        return embed

    async def submit_application(self, interaction, answers):
        config = await self._get_config()
        if not config.get("enabled") or not config.get("channel"):
            return await interaction.response.send_message("❌ Applications are currently closed.", ephemeral=True)

        channel = self.bot.get_channel(int(config["channel"]))
        if not channel:
            return await interaction.response.send_message("❌ Application channel not found.", ephemeral=True)

        app_id = f"{interaction.user.id}-{int(datetime.utcnow().timestamp())}"
        await self.db.insert_one({"_id": app_id, "user_id": interaction.user.id, "answers": answers, "status": "pending", "timestamp": datetime.utcnow(), "notes": []})

        embed = discord.Embed(title="📋 New Staff Application", color=0x5865F2, timestamp=datetime.utcnow())
        embed.set_author(name=str(interaction.user), icon_url=interaction.user.display_avatar.url)
        embed.add_field(name="👤 Applicant", value=f"{interaction.user.mention}\n`{interaction.user.id}`", inline=False)
        
        for q, a in answers.items():
            embed.add_field(name=f"❓ {q}", value=f"```{a[:1000]}```", inline=False)
        
        embed.set_footer(text=f"ID: {app_id}")

        view = ApplicationButtons(self, app_id, interaction.user.id)
        await channel.send(embed=embed, view=view)
        
        success_embed = discord.Embed(title="✅ Application Submitted!", description="Your application has been sent to our staff team. You'll receive a DM when it's reviewed.", color=0x57F287)
        await interaction.response.send_message(embed=success_embed, ephemeral=True)

    async def handle_decision(self, interaction, app_id, user_id, accepted):
        if not interaction.user.guild_permissions.manage_guild:
            return await interaction.response.send_message("❌ No permission.", ephemeral=True)

        app = await self.db.find_one({"_id": app_id})
        if not app or app["status"] != "pending":
            return await interaction.response.send_message("❌ Application already processed.", ephemeral=True)

        await self.db.update_one({"_id": app_id}, {"$set": {"status": "accepted" if accepted else "denied", "reviewer": interaction.user.id, "reviewed_at": datetime.utcnow()}})

        config = await self._get_config()
        user = self.bot.get_user(user_id)
        
        if user and config.get("dm_response"):
            try:
                dm_embed = discord.Embed(
                    title="✅ Application Accepted!" if accepted else "❌ Application Denied",
                    description=f"Your staff application has been **{'accepted' if accepted else 'denied'}**.\n\n{'Welcome to the team!' if accepted else 'Thank you for applying. Feel free to apply again in the future.'}",
                    color=0x57F287 if accepted else 0xED4245
                )
                await user.send(embed=dm_embed)
            except:
                pass

        if accepted and config.get("role"):
            try:
                member = interaction.guild.get_member(user_id)
                role = interaction.guild.get_role(int(config["role"]))
                if member and role:
                    await member.add_roles(role, reason=f"Application accepted by {interaction.user}")
            except:
                pass

        embed = interaction.message.embeds[0]
        embed.color = 0x57F287 if accepted else 0xED4245
        embed.set_footer(text=f"{'✅ Accepted' if accepted else '❌ Denied'} by {interaction.user} • {embed.footer.text}")
        await interaction.message.edit(embed=embed, view=None)
        
        response_embed = discord.Embed(title=f"✅ Application {'Accepted' if accepted else 'Denied'}", color=0x57F287 if accepted else 0xED4245)
        await interaction.response.send_message(embed=response_embed, ephemeral=True)

    @commands.group(invoke_without_command=True)
    @checks.has_permissions(PermissionLevel.MODERATOR)
    async def app(self, ctx):
        """Interactive application management."""
        config = await self._get_config()
        embed = await self.create_setup_embed(config)
        view = SetupView(self, ctx)
        await ctx.send(embed=embed, view=view)

    @app.command(name="post")
    @checks.has_permissions(PermissionLevel.ADMINISTRATOR)
    async def post(self, ctx, channel: discord.TextChannel = None):
        """Post application button."""
        config = await self._get_config()
        if not config.get("questions"):
            return await ctx.send("❌ Add questions first using `?app`")
        
        channel = channel or ctx.channel
        embed = discord.Embed(
            title="📋 Staff Applications",
            description="**We're looking for dedicated staff members!**\n\nClick the button below to submit your application. Make sure to answer all questions honestly and thoroughly.\n\n*Good luck!* 🍀",
            color=0x5865F2
        )
        embed.set_thumbnail(url=ctx.guild.icon.url if ctx.guild.icon else None)
        embed.add_field(name="📝 Questions", value=f"{len(config['questions'])} questions", inline=True)
        embed.add_field(name="⏱️ Time", value="~5 minutes", inline=True)
        embed.set_footer(text=f"Applications are currently {'OPEN' if config.get('enabled') else 'CLOSED'}")
        
        class ApplyButton(ui.View):
            def __init__(self, plugin):
                super().__init__(timeout=None)
                self.plugin = plugin

            @ui.button(label="Apply Now", style=discord.ButtonStyle.primary, emoji="📝", custom_id="apply_button")
            async def apply(self, interaction: discord.Interaction, button: ui.Button):
                config = await self.plugin._get_config()
                if not config.get("enabled"):
                    return await interaction.response.send_message("❌ Applications are currently closed.", ephemeral=True)
                modal = ApplicationModal(config["questions"], self.plugin)
                await interaction.response.send_modal(modal)

        await channel.send(embed=embed, view=ApplyButton(self))
        await ctx.send(f"✅ Posted in {channel.mention}")

    @app.command(name="stats")
    @checks.has_permissions(PermissionLevel.MODERATOR)
    async def stats(self, ctx):
        """View statistics."""
        total = await self.db.count_documents({"status": {"$exists": True}})
        pending = await self.db.count_documents({"status": "pending"})
        accepted = await self.db.count_documents({"status": "accepted"})
        denied = await self.db.count_documents({"status": "denied"})

        embed = discord.Embed(title="📊 Application Statistics", color=self.bot.main_color)
        embed.add_field(name="📋 Total", value=f"```{total}```", inline=True)
        embed.add_field(name="⏳ Pending", value=f"```{pending}```", inline=True)
        embed.add_field(name="✅ Accepted", value=f"```{accepted}```", inline=True)
        embed.add_field(name="❌ Denied", value=f"```{denied}```", inline=True)
        
        if total > 0:
            accept_rate = (accepted / total) * 100
            embed.add_field(name="📈 Acceptance Rate", value=f"```{accept_rate:.1f}%```", inline=True)
        
        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(Application(bot))
