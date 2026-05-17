import discord
from discord.ext import commands
from discord.ui import Button, View, Select
import asyncio
import io
import os

# ===================== НАСТРОЙКИ =====================
TOKEN = os.getenv("TOKEN")
CATEGORY_NAME = "Тикеты"           # Категория в Discord где создаются тикеты
SUPPORT_ROLE_NAME = "Support"      # Роль, которая видит тикеты
LOG_CHANNEL_NAME = "ticket-logs"   # Канал для логов
ARCHIVE_CHANNEL_NAME = "архив-тикетов"  # Канал-ветка для архива (только для админов)
CLOSE_DELAY = 10                        # Секунд до удаления канала после закрытия

# Ссылки на картинки (замени на свои)
IMAGE_PANEL  = "https://cdn.discordapp.com/attachments/1497777455199682580/1505353425896865932/grzue2pxqaa94te.jpg?ex=6a0a5120&is=6a08ffa0&hm=f6b288bb8f7f720cb2e28a3ceeb9af8acec7663a9dbfa8aefd83f0cb6fc28c0c&"  # Картинка в панели !panel
IMAGE_TICKET = "https://cdn.discordapp.com/attachments/1497777455199682580/1505353425896865932/grzue2pxqaa94te.jpg?ex=6a0a5120&is=6a08ffa0&hm=f6b288bb8f7f720cb2e28a3ceeb9af8acec7663a9dbfa8aefd83f0cb6fc28c0c&"  # Картинка внутри тикета

# Динамические войсы
VOICE_LOBBY_NAME     = "➕・Ожидание администратора"  # Канал-триггер (1 слот)
VOICE_CATEGORY_NAME  = "Приватные войсы"              # Категория для создаваемых войсов
# =====================================================

# Словарь: голос канал → владелец (для авто-удаления)
temp_voice_channels = {}

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True
intents.voice_states = True

bot = commands.Bot(command_prefix="!", intents=intents)


# ───────────────────────────────────────────────────
#  Выбор категории тикета
# ───────────────────────────────────────────────────
class TicketCategorySelect(Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="🛠️ Поддержка",  value="support",   description="Техническая помощь"),
            discord.SelectOption(label="⚠️ Жалоба",     value="complaint", description="Пожаловаться на пользователя"),
            discord.SelectOption(label="❓ Другое",     value="other",     description="Прочие вопросы"),
        ]
        super().__init__(placeholder="Выберите тему тикета...", options=options)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        user  = interaction.user

        category_map = {
            "support":   "🛠️ Поддержка",
            "complaint": "⚠️ Жалоба",
            "other":     "❓ Другое",
        }
        topic = category_map[self.values[0]]

        # Найти или создать категорию каналов
        discord_category = discord.utils.get(guild.categories, name=CATEGORY_NAME)
        if not discord_category:
            discord_category = await guild.create_category(CATEGORY_NAME)

        # Права доступа к каналу
        support_role = discord.utils.get(guild.roles, name=SUPPORT_ROLE_NAME)
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            user:               discord.PermissionOverwrite(view_channel=True, send_messages=True),
            guild.me:           discord.PermissionOverwrite(view_channel=True, send_messages=True),
        }
        if support_role:
            overwrites[support_role] = discord.PermissionOverwrite(view_channel=True, send_messages=True)

        # Создать канал
        channel_name = f"ticket-{user.name}".lower().replace(" ", "-")
        ticket_channel = await discord_category.create_text_channel(
            name=channel_name,
            overwrites=overwrites,
            topic=f"Тикет от {user} | Тема: {topic}"
        )

        # Embed внутри тикета
        embed = discord.Embed(
            title=f"Тикет — {topic}",
            description=(
                f"Привет, {user.mention}! 👋\n\n"
                f"Опиши свою проблему, и команда поддержки скоро ответит.\n\n"
                f"Чтобы закрыть тикет — нажми кнопку ниже."
            ),
            color=discord.Color.blurple()
        )
        embed.set_image(url=IMAGE_TICKET)
        embed.set_footer(text=f"ID: {user.id} • {topic}")

        await ticket_channel.send(
            content=f"{user.mention}" + (f" | {support_role.mention}" if support_role else ""),
            embed=embed,
            view=CloseTicketView()
        )

        await interaction.followup.send(
            f"✅ Тикет создан! → {ticket_channel.mention}", ephemeral=True
        )

        # Лог
        log_ch = discord.utils.get(guild.text_channels, name=LOG_CHANNEL_NAME)
        if log_ch:
            log_embed = discord.Embed(
                title="📂 Новый тикет",
                color=discord.Color.green()
            )
            log_embed.add_field(name="Пользователь", value=user.mention)
            log_embed.add_field(name="Тема",         value=topic)
            log_embed.add_field(name="Канал",        value=ticket_channel.mention)
            await log_ch.send(embed=log_embed)


class TicketCategoryView(View):
    def __init__(self):
        super().__init__(timeout=60)
        self.add_item(TicketCategorySelect())


# ───────────────────────────────────────────────────
#  Кнопка открытия тикета
# ───────────────────────────────────────────────────
class OpenTicketView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="📩 Открыть тикет", style=discord.ButtonStyle.primary, custom_id="open_ticket")
    async def open_ticket(self, interaction: discord.Interaction, button: Button):
        # Проверить, нет ли уже открытого тикета
        existing = discord.utils.get(
            interaction.guild.text_channels,
            name=f"ticket-{interaction.user.name}".lower().replace(" ", "-")
        )
        if existing:
            await interaction.response.send_message(
                f"У тебя уже есть открытый тикет: {existing.mention}", ephemeral=True
            )
            return

        await interaction.response.send_message(
            "Выбери тему тикета:", view=TicketCategoryView(), ephemeral=True
        )


# ───────────────────────────────────────────────────
#  Кнопка закрытия тикета
# ───────────────────────────────────────────────────
class CloseTicketView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🔒 Закрыть тикет", style=discord.ButtonStyle.danger, custom_id="close_ticket")
    async def close_ticket(self, interaction: discord.Interaction, button: Button):
        await interaction.response.defer()

        channel = interaction.channel
        guild   = interaction.guild
        user    = interaction.user

        # ── 1. Сохранить лог переписки в архив ──────────────────────────
        archive_ch = discord.utils.get(guild.text_channels, name=ARCHIVE_CHANNEL_NAME)
        if not archive_ch:
            # Создать канал только для админов если его нет
            admin_role = discord.utils.find(lambda r: r.permissions.administrator, guild.roles)
            overwrites = {
                guild.default_role: discord.PermissionOverwrite(view_channel=False),
                guild.me:           discord.PermissionOverwrite(view_channel=True, send_messages=True),
            }
            if admin_role:
                overwrites[admin_role] = discord.PermissionOverwrite(view_channel=True, send_messages=True)
            archive_ch = await guild.create_text_channel(ARCHIVE_CHANNEL_NAME, overwrites=overwrites)

        # Собрать все сообщения из тикета
        messages = []
        async for msg in channel.history(limit=500, oldest_first=True):
            if msg.author.bot and not msg.embeds:
                continue
            timestamp = msg.created_at.strftime("%d.%m.%Y %H:%M")
            content = msg.content or ""
            if msg.embeds:
                for e in msg.embeds:
                    if e.title:
                        content += f"[Embed: {e.title}]"
            messages.append(f"[{timestamp}] {msg.author.display_name}: {content}")

        transcript = "\n".join(messages) if messages else "— переписка пуста —"
        transcript_file = discord.File(
            fp=io.BytesIO(transcript.encode("utf-8")),
            filename=f"transcript-{channel.name}.txt"
        )

        archive_embed = discord.Embed(
            title=f"📁 Архив тикета — #{channel.name}",
            color=discord.Color.orange()
        )
        archive_embed.add_field(name="Закрыл",  value=user.mention, inline=True)
        archive_embed.add_field(name="Канал",   value=channel.name, inline=True)
        archive_embed.add_field(name="Тема",    value=channel.topic or "—", inline=False)
        archive_embed.set_footer(text="Транскрипт прикреплён ниже")

        await archive_ch.send(embed=archive_embed, file=transcript_file)

        # ── 2. Лог закрытия ─────────────────────────────────────────────
        log_ch = discord.utils.get(guild.text_channels, name=LOG_CHANNEL_NAME)
        if log_ch:
            log_embed = discord.Embed(title="🔒 Тикет закрыт", color=discord.Color.red())
            log_embed.add_field(name="Закрыл", value=user.mention)
            log_embed.add_field(name="Канал",  value=channel.name)
            await log_ch.send(embed=log_embed)

        # ── 3. Отсчёт 10 секунд и удаление ─────────────────────────────
        countdown_msg = await channel.send(f"🔒 Тикет закрыт. Канал удалится через **{CLOSE_DELAY}** сек...")
        for i in range(CLOSE_DELAY - 1, 0, -1):
            await asyncio.sleep(1)
            await countdown_msg.edit(content=f"🔒 Тикет закрыт. Канал удалится через **{i}** сек...")
        await asyncio.sleep(1)
        await channel.delete(reason=f"Тикет закрыт пользователем {user}")


# ───────────────────────────────────────────────────
#  Команда: отправить панель с кнопкой тикета
# ───────────────────────────────────────────────────
@bot.command(name="panel")
@commands.has_permissions(administrator=True)
async def ticket_panel(ctx):
    """!panel — отправить панель открытия тикетов"""
    await ctx.message.delete()

    embed = discord.Embed(
        title="🎫 Система тикетов",
        description=(
            "Если у тебя есть вопрос или проблема — открой тикет.\n\n"
            "Нажми кнопку ниже, выбери тему и команда поддержки поможет тебе."
        ),
        color=discord.Color.blurple()
    )
    embed.set_image(url=IMAGE_PANEL)
    embed.set_footer(text="Один открытый тикет на пользователя")

    await ctx.send(embed=embed, view=OpenTicketView())


# ───────────────────────────────────────────────────
#  Динамические войсы
# ───────────────────────────────────────────────────
@bot.event
async def on_voice_state_update(member, before, after):
    guild = member.guild

    # ── Игрок зашёл в лобби-триггер ─────────────────
    if after.channel and after.channel.name == VOICE_LOBBY_NAME:

        # Найти или создать категорию для войсов
        voice_category = discord.utils.get(guild.categories, name=VOICE_CATEGORY_NAME)
        if not voice_category:
            admin_role = discord.utils.find(lambda r: r.permissions.administrator, guild.roles)
            cat_overwrites = {
                guild.default_role: discord.PermissionOverwrite(view_channel=False),
                guild.me:           discord.PermissionOverwrite(view_channel=True, manage_channels=True, connect=True),
            }
            if admin_role:
                cat_overwrites[admin_role] = discord.PermissionOverwrite(view_channel=True, connect=True)
            voice_category = await guild.create_category(VOICE_CATEGORY_NAME, overwrites=cat_overwrites)

        # Права: только владелец + админы
        admin_role = discord.utils.find(lambda r: r.permissions.administrator, guild.roles)
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False, connect=False),
            member:             discord.PermissionOverwrite(view_channel=True, connect=True, speak=True),
            guild.me:           discord.PermissionOverwrite(view_channel=True, connect=True, manage_channels=True),
        }
        if admin_role:
            overwrites[admin_role] = discord.PermissionOverwrite(view_channel=True, connect=True, speak=True)

        # Создать приватный войс
        new_channel = await guild.create_voice_channel(
            name=f"🔒 {member.display_name}",
            category=voice_category,
            user_limit=0,
            overwrites=overwrites
        )

        # Переместить игрока
        await member.move_to(new_channel)

        # Запомнить канал
        temp_voice_channels[new_channel.id] = member.id

    # ── Игрок вышел из приватного войса → удалить если пусто ───
    if before.channel and before.channel.id in temp_voice_channels:
        if len(before.channel.members) == 0:
            await before.channel.delete(reason="Приватный войс пуст")
            temp_voice_channels.pop(before.channel.id, None)


# ───────────────────────────────────────────────────
#  Команда: создать канал-лобби
# ───────────────────────────────────────────────────
@bot.command(name="voicesetup")
@commands.has_permissions(administrator=True)
async def voice_setup(ctx):
    """!voicesetup — создать канал-лобби для динамических войсов"""
    await ctx.message.delete()

    guild = ctx.guild

    # Найти или создать категорию
    voice_category = discord.utils.get(guild.categories, name=VOICE_CATEGORY_NAME)
    if not voice_category:
        admin_role = discord.utils.find(lambda r: r.permissions.administrator, guild.roles)
        cat_overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            guild.me:           discord.PermissionOverwrite(view_channel=True, manage_channels=True, connect=True),
        }
        if admin_role:
            cat_overwrites[admin_role] = discord.PermissionOverwrite(view_channel=True, connect=True)
        voice_category = await guild.create_category(VOICE_CATEGORY_NAME, overwrites=cat_overwrites)

    # Создать лобби-триггер (виден всем, 1 слот)
    existing_lobby = discord.utils.get(guild.voice_channels, name=VOICE_LOBBY_NAME)
    if not existing_lobby:
        await guild.create_voice_channel(
            name=VOICE_LOBBY_NAME,
            category=voice_category,
            user_limit=1
        )

    await ctx.send("✅ Войс-лобби создано! Заходи в **➕ Ожидание администратора**", delete_after=5)



    # Регистрируем persistent views чтобы кнопки работали после перезапуска
    bot.add_view(OpenTicketView())
    bot.add_view(CloseTicketView())
    print(f"✅ Бот запущен как {bot.user} (ID: {bot.user.id})")


bot.run(TOKEN)
