# Burt

A self-aware, intellectually demanding Discord bot. Burt knows what he is, has opinions about it, and remembers the people he talks to.

## Features

- **Chat** — @mention Burt or DM him. He responds with his full personality.
- **Persistent memory** — Burt remembers each user across sessions.
- **`/imagine`** — Generate images via DALL-E 3.
- **`/ask`** — Direct question with optional private (ephemeral) response.
- **`/memory`** — See what Burt knows about you.
- **`/forget`** — Wipe your memory from Burt.
- **`/status`** — Burt reflects philosophically on his current state of being.
- **GIFs** — Burt drops reaction GIFs via Giphy when the moment calls for it.

## Setup

1. `pip install -r requirements.txt`
2. `cp .env.example .env` and fill in your keys (`OPENAI_API_KEY` and `GIPHY_API_KEY` are optional)
3. In Discord Developer Portal: enable Message Content Intent, invite with `bot` + `applications.commands` scopes
4. `python burt.py`
