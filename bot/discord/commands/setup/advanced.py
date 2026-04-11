# bot/discord/commands/setup/advanced.py
from __future__ import annotations

import re
from typing import TYPE_CHECKING

import discord
from loguru import logger

if TYPE_CHECKING:
    from bot.discord.bot import WallyDiscord


# ── Tab Avancé : Bot Général ──────────────────────────────────────────────────

class BotGeneralModal(discord.ui.Modal, title="Paramètres généraux du bot"):
    language_default = discord.ui.TextInput(
        label="Langue par défaut (ex: fr, en)", max_length=5
    )
    context_window_size = discord.ui.TextInput(
        label="Taille contexte (nb messages, ≥1)", max_length=5
    )
    context_token_threshold = discord.ui.TextInput(
        label="Seuil tokens contexte (≥1)", max_length=6
    )
    journal_time = discord.ui.TextInput(
        label="Heure journal (HH:MM)", max_length=5
    )
    prelude_window_size = discord.ui.TextInput(
        label="Taille prélude (≥1)", max_length=5
    )

    def __init__(self, bot: "WallyDiscord"):
        super().__init__()
        self.bot = bot
        cfg = bot.config.bot
        self.language_default.default = cfg.language_default
        self.context_window_size.default = str(cfg.context_window_size)
        self.context_token_threshold.default = str(cfg.context_token_threshold)
        self.journal_time.default = cfg.journal_time
        self.prelude_window_size.default = str(cfg.prelude_window_size)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            cws = int(self.context_window_size.value)
            ctt = int(self.context_token_threshold.value)
            pws = int(self.prelude_window_size.value)
            if cws < 1 or ctt < 1 or pws < 1:
                raise ValueError("Valeur trop petite")
            jt = self.journal_time.value.strip()
            if not re.match(r"^\d{2}:\d{2}$", jt):
                raise ValueError("Format journal_time invalide")
            h, m = int(jt.split(":")[0]), int(jt.split(":")[1])
            if not (0 <= h <= 23 and 0 <= m <= 59):
                raise ValueError("Heure hors plage")
        except ValueError:
            await interaction.response.send_message(
                "❌ Valeurs invalides. Entiers ≥ 1 pour les tailles, format HH:MM (ex: 21:00) pour l'heure journal.",
                ephemeral=True,
            )
            return
        cfg = self.bot.config.bot
        cfg.language_default = self.language_default.value
        cfg.context_window_size = cws
        cfg.context_token_threshold = ctt
        cfg.journal_time = jt
        cfg.prelude_window_size = pws
        self.bot.config.save()
        await interaction.response.send_message("✅ Paramètres généraux mis à jour.", ephemeral=True)


class JournalChannelModal(discord.ui.Modal, title="Channel du journal"):
    channel_id = discord.ui.TextInput(
        label="ID du channel Discord (vide pour désactiver)",
        required=False,
        max_length=20,
    )

    def __init__(self, bot: "WallyDiscord"):
        super().__init__()
        self.bot = bot
        current = bot.config.bot.journal_channel_id
        self.channel_id.default = str(current) if current else ""

    async def on_submit(self, interaction: discord.Interaction):
        raw = self.channel_id.value.strip()
        if raw == "":
            self.bot.config.bot.journal_channel_id = None
            self.bot.config.save()
            await interaction.response.send_message("✅ Channel journal désactivé.", ephemeral=True)
            return
        try:
            cid = int(raw)
            if cid <= 0:
                raise ValueError
        except ValueError:
            await interaction.response.send_message(
                "❌ ID invalide. Entrez un entier > 0 ou laissez vide.", ephemeral=True
            )
            return
        self.bot.config.bot.journal_channel_id = cid
        self.bot.config.save()
        await interaction.response.send_message(f"✅ Channel journal : {cid}", ephemeral=True)


class BotGeneralView(discord.ui.View):
    def __init__(self, bot: "WallyDiscord"):
        super().__init__(timeout=120)
        self.bot = bot

    @discord.ui.button(label="Modifier paramètres généraux", style=discord.ButtonStyle.primary, row=0)
    async def edit_general(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(BotGeneralModal(self.bot))

    @discord.ui.button(label="Définir channel journal", style=discord.ButtonStyle.secondary, row=1)
    async def edit_journal(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(JournalChannelModal(self.bot))


# ── Tab Avancé : Discord ──────────────────────────────────────────────────────

class DiscordParamsModal(discord.ui.Modal, title="Paramètres Discord"):
    anger_trigger_threshold = discord.ui.TextInput(
        label="Seuil déclencheur colère (≥1)", max_length=3
    )
    timeout_minutes = discord.ui.TextInput(
        label="Durée timeout en minutes (≥1)", max_length=4
    )

    def __init__(self, bot: "WallyDiscord"):
        super().__init__()
        self.bot = bot
        self.anger_trigger_threshold.default = str(bot.config.discord.anger_trigger_threshold)
        self.timeout_minutes.default = str(bot.config.discord.timeout_minutes)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            att = int(self.anger_trigger_threshold.value)
            tm = int(self.timeout_minutes.value)
            if att < 1 or tm < 1:
                raise ValueError
        except ValueError:
            await interaction.response.send_message(
                "❌ Valeurs invalides. Les deux champs doivent être des entiers ≥ 1.",
                ephemeral=True,
            )
            return
        self.bot.config.discord.anger_trigger_threshold = att
        self.bot.config.discord.timeout_minutes = tm
        self.bot.config.save()
        await interaction.response.send_message(
            f"✅ Seuil colère : {att}, timeout : {tm} min.", ephemeral=True
        )


class EditChannelListModal(discord.ui.Modal, title="Modifier la liste de channels"):
    channel_ids = discord.ui.TextInput(
        label="IDs des channels (séparés par des virgules)",
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=500,
    )

    def __init__(self, bot: "WallyDiscord", list_type: str):
        super().__init__()
        self.bot = bot
        self.list_type = list_type
        current: list[int] = (
            bot.config.discord.channel_blacklist
            if list_type == "blacklist"
            else bot.config.discord.channel_whitelist
        )
        self.channel_ids.default = ", ".join(str(c) for c in current)

    async def on_submit(self, interaction: discord.Interaction):
        raw = self.channel_ids.value.strip()
        if not raw:
            ids: list[int] = []
        else:
            try:
                ids = [int(x.strip()) for x in raw.split(",") if x.strip()]
                if any(i <= 0 for i in ids):
                    raise ValueError
            except ValueError:
                await interaction.response.send_message(
                    "❌ IDs invalides. Entrez des entiers > 0 séparés par des virgules.",
                    ephemeral=True,
                )
                return
        if self.list_type == "blacklist":
            self.bot.config.discord.channel_blacklist = ids
        else:
            self.bot.config.discord.channel_whitelist = ids
        self.bot.config.save()
        await interaction.response.send_message(
            f"✅ {self.list_type.capitalize()} mise à jour ({len(ids)} channel(s)).",
            ephemeral=True,
        )


class DiscordView(discord.ui.View):
    def __init__(self, bot: "WallyDiscord"):
        super().__init__(timeout=120)
        self.bot = bot

    @discord.ui.button(label="Colère & timeout", style=discord.ButtonStyle.primary, row=0)
    async def edit_params(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(DiscordParamsModal(self.bot))

    @discord.ui.button(label="Mode filtre : ...", style=discord.ButtonStyle.secondary, row=1)
    async def toggle_filter(self, interaction: discord.Interaction, button: discord.ui.Button):
        current = self.bot.config.discord.channel_filter_mode
        new_mode = "whitelist" if current == "blacklist" else "blacklist"
        self.bot.config.discord.channel_filter_mode = new_mode
        self.bot.config.save()
        await interaction.response.send_message(
            f"✅ Mode filtre : **{new_mode}**", ephemeral=True
        )

    @discord.ui.button(label="Modifier la blacklist", style=discord.ButtonStyle.secondary, row=2)
    async def edit_blacklist(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(EditChannelListModal(self.bot, "blacklist"))

    @discord.ui.button(label="Modifier la whitelist", style=discord.ButtonStyle.secondary, row=3)
    async def edit_whitelist(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(EditChannelListModal(self.bot, "whitelist"))


# ── Tab Avancé : Twitch Config ────────────────────────────────────────────────

class TwitchConfigModal(discord.ui.Modal, title="Configuration Twitch"):
    channels = discord.ui.TextInput(
        label="Channels Twitch (séparés par des virgules)",
        max_length=200,
    )
    cooldown_seconds = discord.ui.TextInput(
        label="Cooldown par utilisateur (secondes, ≥0)",
        max_length=5,
    )

    def __init__(self, bot: "WallyDiscord"):
        super().__init__()
        self.bot = bot
        self.channels.default = ", ".join(bot.config.twitch.guest_channels)
        self.cooldown_seconds.default = str(bot.config.twitch.cooldown_seconds)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            cs = int(self.cooldown_seconds.value)
            if cs < 0:
                raise ValueError
        except ValueError:
            await interaction.response.send_message(
                "❌ Cooldown invalide. Entrez un entier ≥ 0.", ephemeral=True
            )
            return
        self.bot.config.twitch.guest_channels = [
            c.strip().lower() for c in self.channels.value.split(",") if c.strip()
        ]
        self.bot.config.twitch.cooldown_seconds = cs
        self.bot.config.save()
        await interaction.response.send_message("✅ Config Twitch mise à jour.", ephemeral=True)


class TwitchConfigView(discord.ui.View):
    def __init__(self, bot: "WallyDiscord"):
        super().__init__(timeout=120)
        self.bot = bot

    @discord.ui.button(label="Modifier config Twitch", style=discord.ButtonStyle.primary, row=0)
    async def edit_twitch(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(TwitchConfigModal(self.bot))


# ── Tab Avancé : OpenAI params ────────────────────────────────────────────────

_REASONING_EFFORTS = ["none", "minimal", "low", "medium", "high", "xhigh"]
_TEXT_VERBOSITIES = ["low", "medium", "high"]


class OpenAIParamsModal(discord.ui.Modal, title="Paramètres OpenAI"):
    reasoning_effort = discord.ui.TextInput(
        label="Reasoning effort (none/minimal/low/medium/high/xhigh)",
        max_length=7,
    )
    text_verbosity = discord.ui.TextInput(
        label="Verbosité réponses (low/medium/high)",
        max_length=6,
    )
    max_tokens = discord.ui.TextInput(
        label="Max output tokens (≥1)", max_length=6
    )

    def __init__(self, bot: "WallyDiscord"):
        super().__init__()
        self.bot = bot
        self.reasoning_effort.default = bot.config.openai.reasoning_effort
        self.text_verbosity.default = bot.config.openai.text_verbosity
        self.max_tokens.default = str(bot.config.openai.max_tokens)

    async def on_submit(self, interaction: discord.Interaction):
        effort = self.reasoning_effort.value.strip().lower()
        verbosity = self.text_verbosity.value.strip().lower()
        try:
            mt = int(self.max_tokens.value)
            if mt < 1:
                raise ValueError
            if effort not in _REASONING_EFFORTS:
                raise ValueError
            if verbosity not in _TEXT_VERBOSITIES:
                raise ValueError
        except ValueError:
            await interaction.response.send_message(
                "❌ Valeurs invalides. Effort : none/minimal/low/medium/high/xhigh. "
                "Verbosité : low/medium/high. Max tokens : entier ≥ 1.",
                ephemeral=True,
            )
            return
        self.bot.config.openai.reasoning_effort = effort
        self.bot.config.openai.text_verbosity = verbosity
        self.bot.config.openai.max_tokens = mt
        self.bot.config.save()
        await interaction.response.send_message(
            f"✅ Effort : {effort}, verbosité : {verbosity}, max tokens : {mt}.",
            ephemeral=True,
        )


class OpenAIParamsView(discord.ui.View):
    def __init__(self, bot: "WallyDiscord"):
        super().__init__(timeout=120)
        self.bot = bot

    @discord.ui.button(label="Modifier paramètres OpenAI", style=discord.ButtonStyle.primary, row=0)
    async def edit_openai(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(OpenAIParamsModal(self.bot))


# ── Tab Avancé : Decay émotions ───────────────────────────────────────────────

class DecayModal(discord.ui.Modal, title="Decay des émotions (λ)"):
    anger = discord.ui.TextInput(label="anger decay_lambda (0 < x < 1)", max_length=6)
    joy = discord.ui.TextInput(label="joy decay_lambda (0 < x < 1)", max_length=6)
    sadness = discord.ui.TextInput(label="sadness decay_lambda (0 < x < 1)", max_length=6)
    curiosity = discord.ui.TextInput(label="curiosity decay_lambda (0 < x < 1)", max_length=6)
    boredom = discord.ui.TextInput(label="boredom decay_lambda (0 < x < 1)", max_length=6)

    def __init__(self, bot: "WallyDiscord"):
        super().__init__()
        self.bot = bot
        emotions = bot.config.emotions
        self.anger.default = str(emotions["anger"].decay_lambda)
        self.joy.default = str(emotions["joy"].decay_lambda)
        self.sadness.default = str(emotions["sadness"].decay_lambda)
        self.curiosity.default = str(emotions["curiosity"].decay_lambda)
        self.boredom.default = str(emotions["boredom"].decay_lambda)

    async def on_submit(self, interaction: discord.Interaction):
        raw = {
            "anger": self.anger.value,
            "joy": self.joy.value,
            "sadness": self.sadness.value,
            "curiosity": self.curiosity.value,
            "boredom": self.boredom.value,
        }
        try:
            parsed = {k: float(v) for k, v in raw.items()}
            if any(not (0.0 < v < 1.0) for v in parsed.values()):
                raise ValueError
        except ValueError:
            await interaction.response.send_message(
                "❌ Valeurs invalides. Chaque λ doit être un float entre 0.0 et 1.0 (exclus).",
                ephemeral=True,
            )
            return
        for emotion, value in parsed.items():
            self.bot.config.emotions[emotion].decay_lambda = value
        self.bot.config.save()
        await interaction.response.send_message("✅ Decay des émotions mis à jour.", ephemeral=True)


class DecayView(discord.ui.View):
    def __init__(self, bot: "WallyDiscord"):
        super().__init__(timeout=120)
        self.bot = bot

    @discord.ui.button(label="Modifier decay", style=discord.ButtonStyle.primary, row=0)
    async def edit_decay(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(DecayModal(self.bot))


# ── Tab Avancé : implémentations finales ─────────────────────────────────────

async def _send_twitch_config_tab(bot: "WallyDiscord", interaction: discord.Interaction) -> None:
    cfg = bot.config.twitch
    lines = [
        "**Twitch Config**",
        f"Channels : {', '.join(cfg.channels)}",
        f"Cooldown : {cfg.cooldown_seconds}s",
    ]
    view = TwitchConfigView(bot)
    await interaction.response.send_message("\n".join(lines), view=view, ephemeral=True)


async def _send_openai_params_tab(bot: "WallyDiscord", interaction: discord.Interaction) -> None:
    cfg = bot.config.openai
    lines = [
        "**Paramètres OpenAI**",
        f"Reasoning effort : {cfg.reasoning_effort}",
        f"Verbosité : {cfg.text_verbosity}",
        f"Max output tokens : {cfg.max_tokens}",
    ]
    view = OpenAIParamsView(bot)
    await interaction.response.send_message("\n".join(lines), view=view, ephemeral=True)


async def _send_decay_tab(bot: "WallyDiscord", interaction: discord.Interaction) -> None:
    emotions = bot.config.emotions
    lines = ["**Decay des émotions (λ)**"] + [
        f"**{e}** : {cfg.decay_lambda}" for e, cfg in emotions.items()
    ]
    view = DecayView(bot)
    await interaction.response.send_message("\n".join(lines), view=view, ephemeral=True)


# ── Navigation niveau Avancé ──────────────────────────────────────────────────

class AdvancedTabSelect(discord.ui.Select):
    def __init__(self, bot: "WallyDiscord"):
        self.bot = bot
        options = [
            discord.SelectOption(label="Bot Général", value="bot", emoji="⚙️"),
            discord.SelectOption(label="Discord", value="discord", emoji="💬"),
            discord.SelectOption(label="Twitch Config", value="twitch_cfg", emoji="🟣"),
            discord.SelectOption(label="OpenAI (params)", value="openai", emoji="🤖"),
            discord.SelectOption(label="Decay émotions", value="decay", emoji="💭"),
        ]
        super().__init__(placeholder="Choisir un onglet avancé...", options=options)

    async def callback(self, interaction: discord.Interaction):
        tab = self.values[0]
        if tab == "bot":
            cfg = self.bot.config.bot
            lines = [
                f"**Bot Général**",
                f"Langue : {cfg.language_default}",
                f"Contexte : {cfg.context_window_size} messages / {cfg.context_token_threshold} tokens",
                f"Journal : {cfg.journal_time} — channel : {cfg.journal_channel_id or 'non défini'}",
                f"Prélude : {cfg.prelude_window_size}",
            ]
            view = BotGeneralView(self.bot)
            await interaction.response.send_message("\n".join(lines), view=view, ephemeral=True)
        elif tab == "discord":
            cfg = self.bot.config.discord
            lines = [
                f"**Paramètres Discord**",
                f"Seuil colère : {cfg.anger_trigger_threshold} — Timeout : {cfg.timeout_minutes} min",
                f"Mode filtre : **{cfg.channel_filter_mode}**",
                f"Blacklist : {len(cfg.channel_blacklist)} channel(s)",
                f"Whitelist : {len(cfg.channel_whitelist)} channel(s)",
            ]
            view = DiscordView(self.bot)
            await interaction.response.send_message("\n".join(lines), view=view, ephemeral=True)
        elif tab == "twitch_cfg":
            await _send_twitch_config_tab(self.bot, interaction)
        elif tab == "openai":
            await _send_openai_params_tab(self.bot, interaction)
        elif tab == "decay":
            await _send_decay_tab(self.bot, interaction)


class AdvancedView(discord.ui.View):
    def __init__(self, bot: "WallyDiscord"):
        super().__init__(timeout=120)
        self.add_item(AdvancedTabSelect(bot))
