import os
import asyncio
import random
from pathlib import Path

import discord
from discord.ext import commands

# ============================================================
# Load .env manually (no extra dependencies)
# ============================================================

SCRIPT_DIR = Path(__file__).resolve().parent
ENV_FILE = SCRIPT_DIR / ".env"

def load_env(path: Path):
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key, value)

load_env(ENV_FILE)

# ============================================================
# Configuration
# ============================================================

TOKEN = os.getenv("DISCORD_BOT_TOKEN")
GUILD_ID = int(os.getenv("DISCORD_GUILD_ID", "0"))

if not TOKEN:
    raise RuntimeError("DISCORD_BOT_TOKEN missing")
if not GUILD_ID:
    raise RuntimeError("DISCORD_GUILD_ID missing")

CATEGORY_NAME = "Seeded Validation"

CHANNEL_SPECS = [
    ("general-validate", 1500),
    ("random-validate", 1500),
    ("logs-validate", 2000),
]

DUMMY_TEXT = [
    "Dummy message for validation.",
    "Testing archive pipeline.",
    "Lorem ipsum dolor sit amet.",
    "Seeded data for archive verification.",
    "Formatting test: **bold**, *italic*, `code`, > quote",
]

# ============================================================
# Fake users (10 simulated members)
# ============================================================

FAKE_USERS = [
    {"name": "Alice",   "avatar": None},
    {"name": "Bob",     "avatar": None},
    {"name": "Charlie", "avatar": None},
    {"name": "Dina",    "avatar": None},
    {"name": "Evan",    "avatar": None},
    {"name": "Farah",   "avatar": None},
    {"name": "Giorgos", "avatar": None},
    {"name": "Hana",    "avatar": None},
    {"name": "Ivan",    "avatar": None},
    {"name": "Jade",    "avatar": None},
]

# ============================================================
# Bot setup
# ============================================================

INTENTS = discord.Intents.default()
INTENTS.guilds = True
INTENTS.message_content = True

bot = commands.Bot(command_prefix="!", intents=INTENTS)

# ============================================================
# Helpers: content generation
# ============================================================

def pick_channel_mention(guild: discord.Guild) -> str | None:
    channels = [
        c for c in guild.text_channels
        if c.permissions_for(guild.me).view_channel
    ]
    if not channels:
        return None
    ch = random.choice(channels)
    return f"<#{ch.id}>"

def pick_role_mention(guild: discord.Guild) -> str | None:
    roles = [
        r for r in guild.roles
        if not r.is_default() and r.name.lower() != "everyone"
    ]
    if not roles:
        return None
    r = random.choice(roles)
    return f"<@&{r.id}>"

def random_code_snippet() -> str:
    snippets = [
        ("python", "def hello(name):\n    return f\"Hello, {name}!\""),
        ("js", "export const sum = (a, b) => a + b;"),
        ("sql", "SELECT user_id, COUNT(*) FROM messages GROUP BY user_id;"),
        ("bash", "curl -X GET 'http://localhost:8000/health'"),
        ("json", '{ "event": "seed", "ok": true, "count": 123 }'),
    ]
    lang, code = random.choice(snippets)
    return f"```{lang}\n{code}\n```"

def random_markdown_message(guild: discord.Guild) -> str:
    ch_mention = pick_channel_mention(guild)
    role_mention = pick_role_mention(guild)

    templates = [
        lambda: "**Deploy succeeded** ✅",
        lambda: "Inline code: `pip install discord.py`",
        lambda: f"Multiline code:\n{random_code_snippet()}",
        lambda: "> Quote test\n> second line\n\nNormal text after.",
        lambda: "Checklist:\n- [x] create channels\n- [x] seed messages\n- [ ] archive validation",
        lambda: "Spoiler test: ||this content is hidden||",
        lambda: "Emoji burst 😄 🚀 🔥 ✅",
        lambda: "**bold**, *italic*, ~~strike~~ formatting",
        lambda: "Link preview test: https://example.com",
        lambda: "Pseudo log:\n`INFO 2026-01-20 webhook send ok`",
        lambda: f"Channel mention: {ch_mention}" if ch_mention else "Channel mention: (none)",
        lambda: f"Role mention: {role_mention}" if role_mention else "Role mention: (none)",
        lambda: "Table-like block:\n```\nuser  msgs\nalice 12\nbob   9\n```",
        lambda: "Steps:\n1) **Seed**\n2) `archive()`\n3) done ✅",
        lambda: random.choice(DUMMY_TEXT),
    ]

    return random.choice(templates)()

# ============================================================
# Helpers: Discord objects
# ============================================================

async def get_or_create_category(guild: discord.Guild, name: str) -> discord.CategoryChannel:
    cat = discord.utils.get(guild.categories, name=name)
    if cat:
        return cat
    return await guild.create_category(name)

async def get_or_create_text_channel(
    guild: discord.Guild,
    category: discord.CategoryChannel,
    name: str
) -> discord.TextChannel:
    existing = discord.utils.get(category.text_channels, name=name)
    if existing:
        return existing
    return await guild.create_text_channel(name, category=category)

async def get_or_create_webhook(
    channel: discord.TextChannel,
    name: str = "SeederWebhook"
) -> discord.Webhook:
    hooks = await channel.webhooks()
    for h in hooks:
        if h.name == name:
            return h
    return await channel.create_webhook(name=name)

# ============================================================
# Seeding logic
# ============================================================

async def seed_channel_as_fake_users(
    guild: discord.Guild,
    channel: discord.TextChannel,
    message_count: int
):
    webhook = await get_or_create_webhook(channel)

    # Store some "previous message tags" so we can simulate reply chains in content
    previous_tags: list[str] = []

    for i in range(message_count):
        fake = FAKE_USERS[i % len(FAKE_USERS)]
        tag = f"[seed:{channel.name}:{i+1}]"

        body = random_markdown_message(guild)

        # 25% chance to simulate a reply in content
        if previous_tags and random.random() < 0.25:
            replied_to = random.choice(previous_tags[-10:])  # reply to something recent
            content = f"{tag} ↪️ replying to {replied_to}\n{body}"
        else:
            content = f"{tag} {body}"

        await webhook.send(
            content=content,
            username=fake["name"],
            avatar_url=fake["avatar"],
            wait=True,
            allowed_mentions=discord.AllowedMentions.none(),  # avoid real pings
        )

        previous_tags.append(tag)
        await asyncio.sleep(0.4)

async def seed_guild(guild: discord.Guild):
    print(f"Seeding public channels in: {guild.name}")

    category = await get_or_create_category(guild, CATEGORY_NAME)

    for channel_name, msg_count in CHANNEL_SPECS:
        channel = await get_or_create_text_channel(guild, category, channel_name)
        await seed_channel_as_fake_users(guild, channel, msg_count)

    print("Seeding complete.")

# ============================================================
# Lifecycle
# ============================================================

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")

    guild = bot.get_guild(GUILD_ID)
    if not guild:
        raise RuntimeError("Bot is not in this guild (check DISCORD_GUILD_ID).")

    await seed_guild(guild)
    await bot.close()

bot.run(TOKEN)
