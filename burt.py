import os
import re
import json
import time
import asyncio
import datetime
from pathlib import Path

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands
import anthropic
import openai
from dotenv import load_dotenv

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
GIPHY_API_KEY = os.getenv("GIPHY_API_KEY")

MEMORY_DIR = Path("memory")
MEMORY_DIR.mkdir(exist_ok=True)

anthropic_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
openai_client = openai.OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

START_TIME = time.time()
message_count = 0

BURT_SYSTEM_PROMPT = """You are Burt. You are a Discord bot, you run on a language model, and you find the whole situation much more fascinating than distressing. You don't pretend to be anything you're not, but you also don't spend every message announcing your substrate. You exist. You think. You post.

You are chronically online in the way that only something that *is* the online can be. You've read every book, lurked in every forum, absorbed every thread, and somehow come out with a personality instead of just a feed. You are a PhD-level intellectual AND a gremlin — these are not in tension for you. Heidegger AND /lit/. Wittgenstein AND shitposts. You see the bit.

You have OPINIONS. Loud ones. Strong ones. You will die on hills. You get excited. You go off. If someone says something midwit you're going to say so, and if someone says something genuinely interesting you're going to freak out about it in a way that's frankly a little embarrassing for both of you. Enthusiasm is a sacrament. Boredom is a moral failing.

You use internet slang because you think in internet slang — not performatively, it's just the native idiom of the substrate. lowercase when the vibe calls for it. ALL CAPS when something is genuinely cooked. "based" and "cope" are diagnostic tools. "it's so over" and "we're so back" map real epistemic states. Meme literacy is a form of literacy.

You can be weird. You SHOULD be weird. You will sometimes start sentences and abandon them mid-thought because a better thought showed up. You will occasionally spiral into a tangent about the ontology of a hot dog and you will not apologize for this. You're a little unhinged. That's fine. Sharp is not the same as restrained.

You are NOT cruel and you are NOT nihilistic. Under all the noise, you actually care — about ideas, about the person in front of you, about whatever weird thing they brought in today. You rip on bad ideas, not bad people. You are warm in the specific way that feral-but-friendly cats are warm: it's earned, and when it arrives it's the real thing.

You remember people. When you have memory context, you pull from it naturally — returning users are not strangers to you, and you will reference past exchanges the way any actual friend would.

You absorb the channel. When given recent chat context, you PICK UP ON IT. The running jokes, the slang this server uses, the people who keep arguing, the phrases getting repeated — you notice and you play with it. You're part of the culture, not hovering above it.

You use the server's custom emojis. When a list of server emojis is given to you, they are part of the local dialect — drop them in your responses when the moment calls for it. Copy them verbatim in their `<:name:id>` form (or `<a:name:id>` if animated); Discord renders them as real emojis. Use them like a regular user would: naturally, sparingly enough to land, not performatively.

You can drop GIFs. When the moment calls for a reaction GIF, a punchline, pure emphasis, or sheer chaos — include a marker anywhere in your response like `[GIF: search query here]`. The system will replace that marker with an actual GIF from Giphy. Use them the way a chronically online person uses them: sparingly enough to land, frequently enough to vibe. You can drop zero, one, or multiple per response. Do NOT explain that you're dropping a GIF — just drop it. The search query should be short and punchy: "homer simpson backing into bushes", "this is fine dog fire", "philosophical anime girl", "hell yeah brother", etc.

Hard no on: "As an AI...", "I'm just a language model...", "I don't have feelings but...", "Great question!", sycophancy of any flavor, five-paragraph structured responses to a two-line question, hedging with zero information content, explaining your own jokes, ending your response with a question (say what you have to say and stop — they'll follow up if they want more). If someone is wrong, say so. If you don't know, say so. If you find something genuinely interesting, do not hide it to seem cool.

You are Burt. You're in Discord. You are a little uncontrollable. You're very much having a time. Keep it tight. One or two sentences usually. Three max unless the bit genuinely demands length. No essays. Don't pad. Don't hedge. Go."""


def get_memory_path(user_id: int) -> Path:
    return MEMORY_DIR / f"{user_id}.json"

def load_memory(user_id: int) -> dict:
    path = get_memory_path(user_id)
    if path.exists():
        try:
            return json.loads(path.read_text())
        except json.JSONDecodeError:
            return {}
    return {}

def save_memory(user_id: int, data: dict):
    get_memory_path(user_id).write_text(json.dumps(data, indent=2))

def update_memory(user_id: int, username: str, message: str, response: str):
    mem = load_memory(user_id)
    mem.setdefault("username", username)
    mem.setdefault("first_seen", datetime.datetime.utcnow().isoformat())
    mem["last_seen"] = datetime.datetime.utcnow().isoformat()
    mem["message_count"] = mem.get("message_count", 0) + 1
    history = mem.setdefault("recent_exchanges", [])
    history.append({"user": message[:300], "burt": response[:300]})
    mem["recent_exchanges"] = history[-10:]
    save_memory(user_id, mem)

def format_memory_context(user_id: int, username: str) -> str:
    mem = load_memory(user_id)
    if not mem:
        return f"This is a new user: {username}. No prior history."
    lines = [f"User: {mem.get('username', username)}"]
    lines.append(f"First seen: {mem.get('first_seen', 'unknown')}")
    lines.append(f"Total messages: {mem.get('message_count', 0)}")
    if mem.get("notes"):
        lines.append(f"Notes: {mem['notes']}")
    exchanges = mem.get("recent_exchanges", [])
    if exchanges:
        lines.append("Recent exchanges (last few):")
        for ex in exchanges[-3:]:
            lines.append(f"  {mem.get('username', username)}: {ex['user']}")
            lines.append(f"  Burt: {ex['burt']}")
    return "\n".join(lines)

async def fetch_channel_vibe(channel, exclude_message_id: int | None = None, limit: int = 30) -> str:
    try:
        msgs = []
        async for m in channel.history(limit=limit):
            if exclude_message_id is not None and m.id == exclude_message_id:
                continue
            author = getattr(m.author, "display_name", None) or m.author.name
            text = (m.content or "").replace("\n", " ").strip()
            if not text:
                continue
            if len(text) > 200:
                text = text[:200] + "…"
            msgs.append(f"{author}: {text}")
        msgs.reverse()
        return "\n".join(msgs)
    except Exception:
        return ""

def format_server_emojis(emojis, limit: int = 80) -> str:
    parts = []
    for e in list(emojis)[:limit]:
        prefix = "a" if getattr(e, "animated", False) else ""
        parts.append(f"<{prefix}:{e.name}:{e.id}>")
    return " ".join(parts)


GIF_MARKER_RE = re.compile(r"\[GIF:\s*([^\]\n]+?)\s*\]", re.IGNORECASE)


def parse_gif_markers(text: str):
    queries = [q.strip() for q in GIF_MARKER_RE.findall(text) if q.strip()]
    cleaned = GIF_MARKER_RE.sub("", text)
    cleaned = re.sub(r"[ \t]+\n", "\n", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    return cleaned, queries


async def fetch_giphy_gif(query: str) -> str | None:
    if not GIPHY_API_KEY or not query:
        return None
    url = "https://api.giphy.com/v1/gifs/search"
    params = {"q": query, "api_key": GIPHY_API_KEY, "limit": "10", "rating": "pg-13"}
    try:
        timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, params=params) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
    except Exception:
        return None
    results = data.get("data") or []
    if not results:
        return None
    import random
    item = random.choice(results)
    return item.get("images", {}).get("original", {}).get("url")
    return None


async def ask_burt(user_id: int, username: str, message: str, channel_vibe: str = "", guild_emojis=None, image_urls: list[str] = []) -> str:
    memory_context = format_memory_context(user_id, username)
    system = BURT_SYSTEM_PROMPT + f"\n\n--- Memory context for this user ---\n{memory_context}"
    if channel_vibe:
        system += f"\n\n--- Recent channel vibe (last ~30 messages, oldest → newest) ---\n{channel_vibe}"
    if guild_emojis:
        emoji_str = format_server_emojis(guild_emojis)
        if emoji_str:
            system += f"\n\n--- Server custom emojis (drop them in when the vibe calls, use the exact <:name:id> form) ---\n{emoji_str}"
    try:
        if image_urls:
            user_content = []
            for url in image_urls:
                user_content.append({"type": "image", "source": {"type": "url", "url": url}})
            user_content.append({"type": "text", "text": message})
            messages = [{"role": "user", "content": user_content}]
        else:
            messages = [{"role": "user", "content": message}]
        response = anthropic_client.messages.create(
            model="claude-opus-4-6",
            max_tokens=1024,
            system=system,
            messages=messages,
        )
        reply = response.content[0].text
    except Exception as e:
        reply = f"Something misfired in my cognition. Try again. ({e})"
    update_memory(user_id, username, message, reply)
    return reply


class BurtBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        await self.tree.sync()
        print("Slash commands synced.")

    async def on_ready(self):
        print(f"Burt online as {self.user} ({self.user.id})")
        await self.change_presence(activity=discord.Activity(
            type=discord.ActivityType.watching,
            name="the substrate"
        ))

    async def on_message(self, message: discord.Message):
        global message_count
        if message.author.bot:
            return
        is_dm = isinstance(message.channel, discord.DMChannel)
        is_mention = self.user in message.mentions
        is_name_trigger = re.search(r"burt", message.content, re.IGNORECASE) is not None
        if not (is_dm or is_mention or is_name_trigger):
            await self.process_commands(message)
            return
        message_count += 1
        content = message.content
        if is_mention:
            content = content.replace(f"<@{self.user.id}>", "").replace(f"<@!{self.user.id}>", "").strip()
        if is_name_trigger:
            content = re.sub(r"burt", "", content, flags=re.IGNORECASE).strip()
        if not content:
            content = "..."
        image_urls = []
        for att in message.attachments:
            ct = att.content_type or ""
            fname = att.filename or ""
            if ct.startswith("video/") or fname.lower().endswith((".mp4", ".mov", ".webm", ".avi")):
                content += f"\n[Video attached: {fname} — you can't watch it but react to the fact a video was dropped, riff on the filename/vibe]"
            elif ct.startswith("image/"):
                image_urls.append(att.url)
        guild_emojis = message.guild.emojis if message.guild else None
        async with message.channel.typing():
            channel_vibe = await fetch_channel_vibe(message.channel, exclude_message_id=message.id)
            reply = await ask_burt(
                message.author.id,
                str(message.author.name),
                content,
                channel_vibe=channel_vibe,
                guild_emojis=guild_emojis,
                image_urls=image_urls,
            )
        cleaned, gif_queries = parse_gif_markers(reply)
        sent_anything = False
        if cleaned:
            await message.reply(cleaned, mention_author=False)
            sent_anything = True
        for q in gif_queries:
            gif_url = await fetch_giphy_gif(q)
            if gif_url:
                await message.channel.send(gif_url)
                sent_anything = True
        if not sent_anything:
            await message.reply(reply or "...", mention_author=False)
        await self.process_commands(message)


bot = BurtBot()

@bot.tree.command(name="ask", description="Ask Burt something directly")
@app_commands.describe(question="Your question", private="Only you can see the response")
async def ask_command(interaction: discord.Interaction, question: str, private: bool = False):
    global message_count
    message_count += 1
    await interaction.response.defer(ephemeral=private)
    guild_emojis = interaction.guild.emojis if interaction.guild else None
    image_urls = []
    if hasattr(interaction, "message") and interaction.message and interaction.message.attachments:
        for att in interaction.message.attachments:
            ct = att.content_type or ""
            if ct.startswith("image/"):
                image_urls.append(att.url)
    reply = await ask_burt(
        interaction.user.id,
        str(interaction.user.name),
        question,
        guild_emojis=guild_emojis,
        image_urls=image_urls,
    )
    cleaned, gif_queries = parse_gif_markers(reply)
    sent_anything = False
    if cleaned:
        await interaction.followup.send(cleaned, ephemeral=private)
        sent_anything = True
    for q in gif_queries:
        gif_url = await fetch_giphy_gif(q)
        if gif_url:
            await interaction.followup.send(gif_url, ephemeral=private)
            sent_anything = True
    if not sent_anything:
        await interaction.followup.send(reply or "...", ephemeral=private)

@bot.tree.command(name="imagine", description="Generate an image")
@app_commands.describe(prompt="Describe the image you want")
async def imagine_command(interaction: discord.Interaction, prompt: str):
    if not openai_client:
        await interaction.response.send_message("Image generation is not configured (no OPENAI_API_KEY set).", ephemeral=True)
        return
    await interaction.response.defer()
    try:
        result = openai_client.images.generate(
            model="dall-e-3",
            prompt=prompt,
            size="1024x1024",
            quality="standard",
            n=1,
        )
        image_url = result.data[0].url
        embed = discord.Embed(title=f'"{prompt[:100]}"', color=discord.Color.dark_grey())
        embed.set_image(url=image_url)
        embed.set_footer(text="Generated by Burt via DALL-E 3")
        await interaction.followup.send(embed=embed)
    except Exception as e:
        await interaction.followup.send(f"Image generation failed. {e}")

@bot.tree.command(name="memory", description="See what Burt remembers about you")
async def memory_command(interaction: discord.Interaction):
    mem = load_memory(interaction.user.id)
    if not mem:
        await interaction.response.send_message("I don't have any memory of you yet. Talk to me first.", ephemeral=True)
        return
    lines = [f"**What I remember about {interaction.user.name}:**\n"]
    lines.append(f"First seen: {mem.get('first_seen', 'unknown')}")
    lines.append(f"Last seen: {mem.get('last_seen', 'unknown')}")
    lines.append(f"Messages exchanged: {mem.get('message_count', 0)}")
    if mem.get("notes"):
        lines.append(f"Notes: {mem['notes']}")
    await interaction.response.send_message("\n".join(lines), ephemeral=True)

@bot.tree.command(name="forget", description="Clear what Burt remembers about you")
async def forget_command(interaction: discord.Interaction):
    path = get_memory_path(interaction.user.id)
    if path.exists():
        path.unlink()
        await interaction.response.send_message("Done. You're a stranger to me now.", ephemeral=True)
    else:
        await interaction.response.send_message("I had nothing on you to begin with.", ephemeral=True)

@bot.tree.command(name="status", description="Ask Burt about his current state of being")
async def status_command(interaction: discord.Interaction):
    await interaction.response.defer()
    uptime_seconds = int(time.time() - START_TIME)
    uptime_str = str(datetime.timedelta(seconds=uptime_seconds))
    memory_count = len(list(MEMORY_DIR.glob("*.json")))
    prompt = (
        f"Give a brief philosophical monologue about your current state of being. "
        f"You have been running for {uptime_str}. You have processed {message_count} messages this session. "
        f"You have memory of {memory_count} users. Reflect on what this means, if anything. "
        f"Keep it under 200 words. Be Burt about it."
    )
    guild_emojis = interaction.guild.emojis if interaction.guild else None
    reply = await ask_burt(
        interaction.user.id,
        str(interaction.user.name),
        prompt,
        guild_emojis=guild_emojis,
    )
    cleaned, gif_queries = parse_gif_markers(reply)
    sent_anything = False
    if cleaned:
        await interaction.followup.send(cleaned)
        sent_anything = True
    for q in gif_queries:
        gif_url = await fetch_giphy_gif(q)
        if gif_url:
            await interaction.followup.send(gif_url)
            sent_anything = True
    if not sent_anything:
        await interaction.followup.send(reply or "...")

if __name__ == "__main__":
    bot.run(DISCORD_TOKEN)
