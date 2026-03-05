# -*- coding: utf-8 -*-
import os
import sys
import time
import json
import re
import random
import sqlite3
import requests
import schedule
import feedparser
import pytz
import google.generativeai as genai
from datetime import datetime, timedelta
from dateutil import parser as date_parser
from bs4 import BeautifulSoup
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# --- Configuration ---
BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')

# WhatsApp Config
WHATSAPP_TOKEN = os.getenv('WHATSAPP_ACCESS_TOKEN')
WHATSAPP_PHONE_ID = os.getenv('WHATSAPP_PHONE_NUMBER_ID')
WHATSAPP_RECIPIENT = os.getenv('WHATSAPP_RECIPIENT_PHONE_NUMBER')

DB_FILE = "seen_urls.db"

# News Sources
RSS_FEEDS = [
    # Tech News
    "https://techcrunch.com/feed/",
    "http://feeds.arstechnica.com/arstechnica/index",
    "https://www.theverge.com/rss/index.xml",
    "https://www.wired.com/feed/rss",
    "https://venturebeat.com/category/ai/feed/",
    
    # AI Research & Engineering
    "https://openai.com/blog/rss/",
    "https://research.google/blog/rss/", 
    "https://www.anthropic.com/rss",
    "https://huggingface.co/blog/feed.xml",
    "https://aws.amazon.com/blogs/machine-learning/feed/",
    "https://news.ycombinator.com/rss", 
]

REDDIT_SUBREDDITS = [
    "MachineLearning",
    "artificial",
    "LocalLLaMA", 
    "technology",
    "singularity" 
]

USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/114.0'
]

# --- Database Setup (SQLite replacing JSON) ---
def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS seen_urls 
                 (url TEXT PRIMARY KEY, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)''')
    conn.commit()
    conn.close()

def is_url_seen(url):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT 1 FROM seen_urls WHERE url = ?", (url,))
    result = c.fetchone()
    conn.close()
    return result is not None

def save_seen_urls(new_urls):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    for url in new_urls:
        try:
            c.execute("INSERT OR IGNORE INTO seen_urls (url) VALUES (?)", (url,))
        except Exception as e:
            print(f"⚠️ DB Insert Error: {e}")
    
    # Auto-cleanup: keep only URLs from the last 60 days
    c.execute("DELETE FROM seen_urls WHERE timestamp < datetime('now', '-60 days')")
    conn.commit()
    conn.close()

# --- Helper Functions ---
def clean_html(html_content):
    if not html_content:
        return ""
    soup = BeautifulSoup(html_content, "html.parser")
    return soup.get_text()[:400] + "..."

def fetch_deep_article_content(url):
    """Visits the actual URL to grab real paragraph text for a better LLM summary."""
    try:
        headers = {'User-Agent': random.choice(USER_AGENTS)}
        r = requests.get(url, headers=headers, timeout=5)
        if r.status_code == 200:
            soup = BeautifulSoup(r.content, 'html.parser')
            # Extract text from paragraphs
            paragraphs = soup.find_all('p')
            text = " ".join([p.get_text(strip=True) for p in paragraphs if len(p.get_text(strip=True)) > 20])
            return text[:1000] # Return the first 1000 characters
    except Exception:
        pass
    return ""

def is_within_24_hours(published_date_str):
    if not published_date_str:
         return True
    try:
        pub_date = date_parser.parse(published_date_str)
        if pub_date.tzinfo is None:
             pub_date = pytz.utc.localize(pub_date)
        now = datetime.now(pytz.utc)
        return (now - pub_date) < timedelta(hours=24)
    except Exception:
        return True

# --- Fetching Logic ---
def fetch_rss_news():
    news_items = []
    print("📡 Fetching RSS feeds...")
    for feed_url in RSS_FEEDS:
        try:
            feed = feedparser.parse(feed_url)
            for entry in feed.entries[:25]:
                published = getattr(entry, 'published', getattr(entry, 'updated', None))
                if published and not is_within_24_hours(published):
                    continue
                
                url = entry.link
                if is_url_seen(url):
                    continue

                rss_summary = clean_html(getattr(entry, 'summary', ''))
                # Fetch deeper content if summary is too short (teaser problem)
                deep_content = ""
                if len(rss_summary) < 150:
                    deep_content = fetch_deep_article_content(url)

                is_research = "research" in feed_url or "blog" in feed_url
                news_items.append({
                    "title": entry.title,
                    "summary": deep_content if deep_content else rss_summary,
                    "source": feed.feed.get('title', 'Unknown Source'),
                    "url": url,
                    "published_at": published or datetime.now().isoformat(),
                    "type": "research" if is_research else "news"
                })
        except Exception as e:
            print(f"⚠️ Error fetching {feed_url}: {e}")
    return news_items

def fetch_reddit_news():
    news_items = []
    print("👽 Fetching Reddit top posts...")
    
    for sub in REDDIT_SUBREDDITS:
        url = f"https://www.reddit.com/r/{sub}/top/.rss?t=day&limit=10"
        headers = {'User-Agent': random.choice(USER_AGENTS)}
        try:
            response = requests.get(url, headers=headers, timeout=10)
            if response.status_code == 200:
                feed = feedparser.parse(response.content)
                for entry in feed.entries[:15]:
                    published = getattr(entry, 'updated', None)
                    if published and not is_within_24_hours(published):
                        continue
                        
                    post_url = entry.link
                    if is_url_seen(post_url):
                        continue

                    # Attempt to extract some actual text from Reddit if possible
                    deep_content = fetch_deep_article_content(post_url)
                        
                    is_research = sub in ["MachineLearning", "LocalLLaMA", "singularity"]
                    news_items.append({
                        "title": entry.title,
                        "summary": deep_content if deep_content else "Reddit Discussion",
                        "source": f"r/{sub}",
                        "url": post_url,
                        "published_at": published or datetime.now().isoformat(),
                        "type": "research" if is_research else "news"
                    })
            else:
                print(f"⚠️ Reddit Error {response.status_code} for r/{sub}")
            
            # Prevent rate limiting (Error 429)
            time.sleep(2)
        except Exception as e:
            print(f"⚠️ Error fetching r/{sub}: {e}")
            
    return news_items

def escape_markdown_v2(text):
    if not text: return ""
    return re.sub(r'([_*\[\]()~`>#+\-=|{}.!])', r'\\\1', text)

# --- AI Generation ---
def generate_digest(news_items, mode):
    if not GEMINI_API_KEY:
        print("❌ Error: GEMINI_API_KEY is not set.")
        return None

    print(f"🤖 Generating digest for {len(news_items)} fresh items in '{mode}' mode using Gemini Native JSON...")
    
    try:
        genai.configure(api_key=GEMINI_API_KEY)
        model_name = 'gemini-1.5-pro'
        ist = pytz.timezone('Asia/Kolkata')
        today_str = datetime.now(ist).strftime("%B %d, %Y")
        
        system_instruction = f"""
        You are Tech News by VJ, an AI-powered daily tech news curator for @technewsbyvj.
        Today is {today_str}. Current Mode: {mode.upper()}
        """

        task_instruction = f"""
        INPUT DATA:
        {json.dumps({"items": news_items}, indent=2)}
        
        TASK:
        Select the best 5-10 items to create a highly curated tech digest.
        All provided input items are fresh and unseen.
        """

        if mode == 'research':
            task_instruction += """
        RESEARCH PRIORITY (Arxiv, HuggingFace, DeepMind, OpenAI):
        - Focus heavily on new models, training techniques, and genuine AI breakthroughs.
        - Exclude minor github commits or trivial code drops.
        - Only select items with type="research" or heavily related to AI research.
            """
        elif mode == 'news':
            task_instruction += """
        NEWS PRIORITY (TechCrunch, Verge, VC, Corporate):
        - Focus on product launches, massive funding rounds, policy changes, and major corporate shifts.
        - Only select items with type="news" or related to tech industry movements.
            """

        task_instruction += """
        CONTENT STYLE:
        - Summaries must be extremely concise (strictly under 25 words), factual, and punchy.
        - Source names should be clean (e.g., 'Ars Technica' not 'Ars Technica Feed').
        - Diversity: Max 2 links per source. Max 2 links from Reddit total.
        
        JSON SCHEMA REQUIRED:
        {
          "items": [
            {
              "type": "📄",
              "title": "Cleaned Headline String",
              "summary": "25-word punchy summary string",
              "source": "Clean Source Name",
              "url": "Exact URL provided"
            }
          ]
        }
        """
        
        prompt = system_instruction + task_instruction
        
        response = None
        for attempt in range(3):
            try:
                model = genai.GenerativeModel(model_name)
                # Guaranteed JSON Generation using the fast legacy API wrapper structure
                response = model.generate_content(
                    prompt,
                    generation_config=dict(
                        response_mime_type="application/json",
                        temperature=0.3
                    )
                )
                break
            except Exception as e:
                err_str = str(e)
                if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str or "Quota" in err_str:
                    if attempt == 0:
                        print(f"⚠️ Quota exceeded for {model_name} (429). Falling back to gemini-2.0-flash...")
                        model_name = 'gemini-2.0-flash'
                        time.sleep(2)
                    elif attempt < 2:
                        wait_time = (attempt + 1) * 20
                        print(f"⚠️ Quota exceeded on fallback (429). Retrying in {wait_time}s...")
                        time.sleep(wait_time)
                    else:
                        raise e
                else:
                    raise e
                    
        if not response:
             return None
             
        data = json.loads(response.text)
        return data
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"⚠️ Gemini Generation/Parsing Error: {e}")
        return None

# --- Output Formatting & Sending ---
def format_telegram_digest(data, mode):
    ist = pytz.timezone('Asia/Kolkata')
    today_str = datetime.now(ist).strftime("%B %d, %Y")
    now_hour = datetime.now(ist).hour
    
    header_date = escape_markdown_v2(today_str)
    greeting = "🌅 *GM*" if now_hour < 12 else "☕ *Good Afternoon*"
    
    topic_header = "🗞️ *TECH DIGEST*"
    if mode == 'research': topic_header = "🔬 *RESEARCH & AI PAPERS*"
    elif mode == 'news': topic_header = "📰 *TECH NEWS & UPDATES*"

    msg = f"{greeting} — {topic_header}\n{header_date}\n\n"
    
    items = data.get('items', [])
    if not items:
        msg += "_(No massive updates found at this time)_\n\n"
        
    for i, item in enumerate(items):
        title = escape_markdown_v2(item.get('title', 'Untitled'))
        summary = escape_markdown_v2(item.get('summary', ''))
        source = escape_markdown_v2(item.get('source', 'Source'))
        url = item.get('url', '')
        if not url.startswith('http'): url = 'https://google.com'
            
        type_icon = escape_markdown_v2(item.get('type', '🔹'))
        msg += f"{i+1}\\. {type_icon} *{title}*\n{summary}\n📎 [{source}]({url})\n\n"
        
    msg += "━━━━━━━━━━━━━━━━━━━━\n🤖 _Tech News by VJ_"
    return msg

def format_whatsapp_digest(data, mode):
    ist = pytz.timezone('Asia/Kolkata')
    today_str = datetime.now(ist).strftime("%B %d, %Y")
    now_hour = datetime.now(ist).hour
    
    greeting = "🌅 *GM*" if now_hour < 12 else "☕ *Good Afternoon*"
    
    topic_header = "🗞️ *TECH DIGEST*"
    if mode == 'research': topic_header = "🔬 *RESEARCH & AI PAPERS*"
    elif mode == 'news': topic_header = "📰 *TECH NEWS & UPDATES*"

    msg = f"{greeting} — {topic_header}\n{today_str}\n\n"
    
    items = data.get('items', [])
    if not items:
        msg += "_(No massive updates found at this time)_\n\n"
        
    for i, item in enumerate(items):
        title = item.get('title', 'Untitled').replace('*', '')
        summary = item.get('summary', '')
        source = item.get('source', 'Source')
        url = item.get('url', '')
        if not url.startswith('http'): url = 'https://google.com'
            
        type_icon = item.get('type', '🔹')
        msg += f"{i+1}. {type_icon} *{title}*\n{summary}\n📎 {source}: {url}\n\n"
        
    msg += "━━━━━━━━━━━━━━━━━━━━\n🤖 _Tech News by VJ_"
    return msg

def send_telegram_message(message):
    if not BOT_TOKEN or not CHAT_ID:
        print("❌ Telegram config missing.")
        return False

    max_length = 4000
    messages = []
    if len(message) > max_length:
        parts = message.split('\n\n')
        current_chunk = ""
        for part in parts:
             if len(current_chunk) + len(part) + 2 > max_length:
                 messages.append(current_chunk)
                 current_chunk = part + "\n\n"
             else:
                 current_chunk += part + "\n\n"
        if current_chunk: messages.append(current_chunk)
    else:
        messages = [message]

    success = True
    for i, msg in enumerate(messages):
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        payload = {
            'chat_id': CHAT_ID,
            'text': msg,
            'parse_mode': 'MarkdownV2',
            'disable_web_page_preview': True
        }
        try:
            r = requests.post(url, json=payload, timeout=20)
            if r.status_code == 200:
                print(f"✅ Telegram part {i+1}/{len(messages)} sent")
            else:
                print(f"❌ Telegram Send Failed: {r.text}")
                success = False
        except Exception as e:
            print(f"⚠️ Telegram Error: {e}")
            success = False
    return success

def send_whatsapp_message(message):
    if not WHATSAPP_TOKEN or not WHATSAPP_PHONE_ID or not WHATSAPP_RECIPIENT:
        print("❌ WhatsApp config missing. Skipping.")
        return False

    # Meta strictly requires no '+', spaces, or dashes in the recipient number
    clean_recipient = WHATSAPP_RECIPIENT.replace('+', '').replace('-', '').replace(' ', '').strip()
    template_name = os.getenv('WHATSAPP_TEMPLATE_NAME')

    url = f"https://graph.facebook.com/v22.0/{WHATSAPP_PHONE_ID}/messages"
    headers = {'Authorization': f'Bearer {WHATSAPP_TOKEN}', 'Content-Type': 'application/json'}

    messages = []
    max_length = 4000
    if len(message) > max_length:
        parts = message.split('\n\n')
        current_chunk = ""
        for part in parts:
             if len(current_chunk) + len(part) + 2 > max_length:
                 messages.append(current_chunk)
                 current_chunk = part + "\n\n"
             else:
                 current_chunk += part + "\n\n"
        if current_chunk: messages.append(current_chunk)
    else:
        messages = [message]

    success = True
    for i, msg_part in enumerate(messages):
        # Default payload (Text mode - requires 24h interaction)
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": clean_recipient,
            "type": "text",
            "text": {
                "body": msg_part,
                "preview_url": False
            }
        }
        
        # Override with Template Mode if specified in .env
        if template_name:
            payload = {
                "messaging_product": "whatsapp",
                "to": clean_recipient,
                "type": "template",
                "template": {
                    "name": template_name,
                    "language": {"code": "en_US"},
                    "components": [{
                        "type": "body",
                        "parameters": [{"type": "text", "text": msg_part[:1024]}] # FB Templates limit vars to 1024 chars
                    }]
                }
            }

        try:
            r = requests.post(url, headers=headers, json=payload, timeout=20)
            if r.status_code in [200, 201]:
                print(f"✅ WhatsApp part {i+1}/{len(messages)} sent via {'Template' if template_name else 'Text'}")
            else:
                resp_json = r.json()
                err_code = resp_json.get('error', {}).get('code')
                
                print(f"❌ WhatsApp Send Failed: {r.status_code} - {r.text}")
                
                if err_code == 131047:
                    print("\n⚠️ ISSUE: The 24-hour session window has closed.")
                    print("   To fix:")
                    print("   1. Send any message from your phone TO the bot's WhatsApp number to re-open the window.")
                    print("   2. OR create an approved template in Meta Developer Console, and set WHATSAPP_TEMPLATE_NAME in your .env file.\n")
                success = False
        except Exception as e:
            print(f"⚠️ WhatsApp Error: {e}")
            success = False
    return success

# --- Main Job Logic ---
def job(mode='all'):
    print(f"⏰ Starting scheduled job ({mode}) at {datetime.now()}...")
    init_db()
    
    all_news = fetch_rss_news() + fetch_reddit_news()
    
    if not all_news:
        print("⚠️ No news found! Check connections.")
        return

    if mode == 'research':
        all_news = [n for n in all_news if n.get('type') == 'research']
    elif mode == 'news':
        all_news = [n for n in all_news if n.get('type') == 'news']
    
    if not all_news:
         print(f"⚠️ No fresh items found for mode '{mode}'.")
         return

    all_news.sort(key=lambda x: x.get('published_at', ''), reverse=True)
    
    # Cap input context to prevent token overload
    if len(all_news) > 80:
        all_news = all_news[:80]

    digest_data = generate_digest(all_news, mode)
    
    if digest_data:
        # 1. Telegram
        tg_message = format_telegram_digest(digest_data, mode)
        tg_success = send_telegram_message(tg_message)
        
        # 2. WhatsApp
        wa_message = format_whatsapp_digest(digest_data, mode)
        wa_success = send_whatsapp_message(wa_message)

        if tg_success or wa_success:
             new_urls = [item.get('url') for item in digest_data.get('items', []) if item.get('url')]
             save_seen_urls(new_urls)
             print(f"📝 Saved {len(new_urls)} dispatched URLs to SQLite database.")
    else:
        print("⚠️ Failed to generate digest.")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description='Run Tech News Bot')
    parser.add_argument('--mode', type=str, default='all', choices=['all', 'research', 'news'], help='Mode to run: research, news, or all')
    args = parser.parse_args()

    if not GEMINI_API_KEY:
        print("🚨 WARNING: GEMINI_API_KEY is missing.")
    if not BOT_TOKEN:
        print("🚨 WARNING: TELEGRAM_BOT_TOKEN is missing.")

    if os.getenv('GITHUB_ACTIONS'):
        print(f"🚀 Running in GitHub Actions mode ({args.mode})")
        job(args.mode)
        sys.exit(0)

    print(f"🤖 Tech News by VJ Bot Online. Monitoring... (Press Ctrl+C to stop)")
    init_db()
    
    try:
        if args.mode != 'all':
             job(args.mode)
             sys.exit(0)
             
        while True:
            schedule.run_pending()
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n🛑 Bot stopped by user.")
