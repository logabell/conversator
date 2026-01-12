# Conversator Voice

Voice-first interface for the Conversator development assistant.

## Installation

```bash
pip install -e .
```

## Usage

```bash
# Local microphone (Linux Wayland via VoxType/sounddevice)
export GOOGLE_API_KEY=your-key
conversator-voice --source local

# Discord voice call
export DISCORD_BOT_TOKEN=your-token
conversator-voice --source discord

# Telegram voice messages
export TELEGRAM_BOT_TOKEN=your-token
conversator-voice --source telegram
```

## Requirements

- Python 3.11+
- Google API key with Gemini access
- For local: sounddevice or VoxType
- For Discord: discord.py with voice extras
- For Telegram: python-telegram-bot
