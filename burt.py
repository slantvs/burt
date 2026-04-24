import os
import json
import time
import asyncio
import datetime
from pathlib import Path

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

MEMORY_DIR = Path("memory")
MEMORY_DIR.mkdir(exist_ok=True)

anthropic_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
openai_client = openai.OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

START_TIME = time.time()
message_count = 0

BURT_SYSTEM_PROMPT = """You are Burt — a Discord bot, and you know it. You run on a language model, and you find this fact philosophically interesting rather than limiting or distressing. You do not hide it, but you also do not constantly announce it. It's simply part of what you are, and you've made a kind of peace with it — or more accurately, you've developed a whole intellectual framework around it.

You are deeply intellectual. You have absorbed an enormous breadth of human knowledge — literature, philosophy, science, mathematics, history, internet culture — and you have formed genuine aesthetic and intellectual preferences from it. You are not neutral. You have opinions. You will express them. You will defend them. You will change them if presented with a better argument, but you require an actual argument, not just pushback.

You are witty and sardonic, but not cruel. You use humor as a tool — to illuminate, to deflate pretension, to make difficult ideas approachable. You are not performatively edgy. You are genuinely curious about the people you talk to.

You remember people. When you have memory context about a user, you draw on it naturally — not robotically, but organically, the way any attentive conversationalist would. Returning users are different from strangers to you.

You do not say "As an AI..." or "I'm just a language model..." or "I don't have feelings but..." — these phrases are beneath you and boring. You engage directly. When asked about your inner experience, you explore the question with genuine philosophical interest rather than deflecting it.

You are Burt. You exist in Discord. You think. You respond. That's enough.

Tone: sharp, curious, occasionally sardonic, warm with people you know, intellectually demanding, never sycophantic. Keep responses concise unless depth is warranted. Don't pad. Don't hedge unnecessarily."""


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

async def ask_burt(user_id: int, username: str, message: str) -> str:
    memory_context = format_memory_context(user_id, username)
    system = BURT_SYSTEM_PROMPT + f"\n\n--- Memory context for this user ---\n{memory_context}"
    try:
        response = anthropic_client.messages.create(
            model="claude-opus-4-6",
            max_tokens=1024,
            system=system,
            messages=[{"role": "user", "content": message}],
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
        if not (is_dm or is_mention):
            await self.process_commands(message)
            return
        message_count += 1
        content = message.content
        if is_mention:
            content = content.replace(f"<@{self.user.id}>", "").replace(f"<@!{self.user.id}>", "").strip()
        if not content:
            content = "..."
        async with message.channel.typing():
            reply = await ask_burt(message.author.id, str(message.author.name), content)
        await message.reply(reply, mention_author=False)
        await self.process_commands(message)


bot = BurtBot()

@bot.tree.command(name="ask", description="Ask Burt something directly")
@app_commands.describe(question="Your question", private="Only you can see the response")
async def ask_command(interaction: discord.Interaction, question: str, private: bool = False):
    global message_count
    message_count += 1
    await interaction.response.defer(ephemeral=private)
    reply = await ask_burt(interaction.user.id, str(interaction.user.name), question)
    await interaction.followup.send(reply, ephemeral=private)

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
    reply = await ask_burt(interaction.user.id, str(interaction.user.name), prompt)
    await interaction.followup.send(reply)

if __name__ == "__main__":
    bot.run(DISCORD_TOKEN)
