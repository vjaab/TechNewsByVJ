# GM Bot Setup Guide

## 1. Get a Free Gemini API Key
To use the AI summarization feature for free:
1. Go to [Google AI Studio](https://aistudio.google.com/).
2. Click "Get API key".
3. Create a key in a new project.
4. Copy the key.

## 2. Configuration
Open `.env` and add your key:
```bash
TELEGRAM_BOT_TOKEN=your_telegram_token
TELEGRAM_CHAT_ID=your_chat_id
GEMINI_API_KEY=your_gemini_key_here
```

## 3. Install Requirements
```bash
pip install -r requirements.txt
```

## 4. Run the Bot
```bash
python bot.py
```
The bot will scour news sources and send a digest at 9:00 AM daily.
