# -*- coding: utf-8 -*-
import os
import sys
import time
import json
import re
import requests
import schedule
import feedparser
import pytz
import google.genai as genai
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

SEEN_URLS_FILE = "seen_urls.json"

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

def load_seen_urls():
    if os.path.exists(SEEN_URLS_FILE):
        try:
            with open(SEEN_URLS_FILE, "r") as f:
                return json.load(f)
        except Exception:
            return []
    return []

def save_seen_urls(seen_urls, new_urls):
    # Keep last 30 days worth of URLs (approx 300 items)
    # Combine and deduplicate
    all_urls = list(set(seen_urls + new_urls))
    # Keep last 300
    updated = all_urls[-300:]
    try:
        with open(SEEN_URLS_FILE, "w") as f:
            json.dump(updated, f)
    except Exception as e:
        print(f"⚠️ Error saving seen_urls: {e}")

def extract_urls_from_post(post_text):
    # Extract URLs that are inside matching Markdown links [Source](URL)
    return re.findall(r'\]\((https?://[^)]+)\)', post_text)

def clean_html(html_content):
    """Removes HTML tags from summary text."""
    if not html_content:
        return ""
    soup = BeautifulSoup(html_content, "html.parser")
    return soup.get_text()[:300] + "..."

def is_within_24_hours(published_date_str):
    """Checks if the published date string is within the last 24 hours."""
    if not published_date_str:
        return True # Default to True if no date, or handle appropriately
        
    try:
        # Parse the date string using dateutil for robust parsing
        pub_date = date_parser.parse(published_date_str)
        
        # Ensure pub_date is timezone-aware if possible, or naive if system is naive
        # Standardize to UTC for comparison if possible
        if pub_date.tzinfo is None:
             pub_date = pytz.utc.localize(pub_date)
        
        now = datetime.now(pytz.utc)
        
        # Calculate difference
        diff = now - pub_date
        return diff < timedelta(hours=24)
    except Exception as e:
        # print(f"Date parsing error: {e}")
        return True # Fallback

def fetch_rss_news():
    """Fetches news from defined RSS feeds."""
    news_items = []
    print("📡 Fetching RSS feeds...")
    for feed_url in RSS_FEEDS:
        try:
            feed = feedparser.parse(feed_url)
            # Fetch all items (limit 20 per feed to avoid overload, but more than 5)
            for entry in feed.entries[:30]:
                published = getattr(entry, 'published', getattr(entry, 'updated', None))
                
                # Check if within 24 hours
                if published and not is_within_24_hours(published):
                    continue
                    
                is_research = "research" in feed_url or "blog" in feed_url
                news_items.append({
                    "title": entry.title,
                    "summary": clean_html(getattr(entry, 'summary', '')),
                    "source": feed.feed.get('title', 'Unknown Source'),
                    "url": entry.link,
                    "published_at": published or datetime.now().isoformat(),
                    "type": "research" if is_research else "news"
                })
        except Exception as e:
            print(f"⚠️ Error fetching {feed_url}: {e}")
    return news_items

def fetch_reddit_news():
    """Fetches top daily posts from Reddit via RSS (No API Key needed)."""
    news_items = []
    print("👽 Fetching Reddit top posts...")
    headers = {'User-Agent': 'Mozilla/5.0 (compatible; GMBot/1.0)'}
    
    for sub in REDDIT_SUBREDDITS:
        url = f"https://www.reddit.com/r/{sub}/top/.rss?t=day&limit=10"
        try:
            response = requests.get(url, headers=headers, timeout=10)
            if response.status_code == 200:
                feed = feedparser.parse(response.content)
                # Fetch all items
                for entry in feed.entries[:20]:
                    published = getattr(entry, 'updated', None)
                    
                    # Check if within 24 hours
                    if published and not is_within_24_hours(published):
                        continue
                        
                    is_research = sub in ["MachineLearning", "LocalLLaMA", "singularity"]
                    news_items.append({
                        "title": entry.title,
                        "summary": "Reddit Discussion",
                        "source": f"r/{sub}",
                        "url": entry.link,
                        "published_at": published or datetime.now().isoformat(),
                        "type": "research" if is_research else "news"
                    })
            else:
                print(f"⚠️ Reddit Error {response.status_code} for r/{sub}")
        except Exception as e:
            print(f"⚠️ Error fetching r/{sub}: {e}")
            
    return news_items

def escape_markdown_v2(text):
    """Escapes characters for Telegram MarkdownV2."""
    if not text: return ""
    # Characters to escape: _ * [ ] ( ) ~ ` > # + - = | { } . !
    return re.sub(r'([_*\[\]()~`>#+\-=|{}.!])', r'\\\1', text)

def format_digest_from_json(data):
    """Formats JSON data into Telegram MarkdownV2 string."""
    ist = pytz.timezone('Asia/Kolkata')
    today_str = datetime.now(ist).strftime("%B %d, %Y")
    
    header_date = escape_markdown_v2(today_str)
    
    msg = f"🌅 *GM\! Tech News by VJ* — {header_date}\n\n"
    
    msg += "🔬 *RESEARCH & AI CONCEPTS*\n\n"
    research_items = data.get('research', [])
    if not research_items:
        msg += "_(No research items today)_\n\n"
        
    for i, item in enumerate(research_items):
        title = escape_markdown_v2(item.get('title', 'Untitled'))
        summary = escape_markdown_v2(item.get('summary', ''))
        source = escape_markdown_v2(item.get('source', 'Source'))
        url = item.get('url', '')
        if not url.startswith('http'): url = 'https://google.com'
            
        type_icon = item.get('type', '📄')
        
        msg += f"{i+1}\. {type_icon} *{title}*\n{summary}\n📎 [{source}]({url})\n\n"
        
    msg += "📰 *TOP STORIES*\n\n"
    news_items = data.get('news', [])
    for i, item in enumerate(news_items):
        title = escape_markdown_v2(item.get('title', item.get('headline', 'Untitled')))
        summary = escape_markdown_v2(item.get('summary', ''))
        source = escape_markdown_v2(item.get('source', 'Source'))
        url = item.get('url', '')
        if not url.startswith('http'): url = 'https://google.com'
        
        msg += f"{i+1}\. 🔹 *{title}*\n{summary}\n📎 [{source}]({url})\n\n"
        
    msg += "━━━━━━━━━━━━━━━━━━━━\n🤖 _Tech News by VJ_"
    return msg


def generate_digest(news_items, mode, seen_urls=None):
    """Uses Gemini to generate the Telegram message via JSON."""
    if seen_urls is None:
        seen_urls = []
        
    if not GEMINI_API_KEY:
        print("❌ Error: GEMINI_API_KEY is not set.")
        return None

    print(f"🤖 Generating digest for {len(news_items)} items in '{mode}' mode using Gemini...")
    
    try:
        client = genai.Client(api_key=GEMINI_API_KEY)
        
        ist = pytz.timezone('Asia/Kolkata')
        today_str = datetime.now(ist).strftime("%B %d, %Y")
        
        input_data = {
            "items": news_items,
            "seen_urls": seen_urls
        }
        
        system_instruction = f"""
        You are Tech News by VJ, an AI-powered daily tech news curator for @technewsbyvj.
        Today is {today_str}.
        Current Mode: {mode.upper()}
        """

        task_instruction = f"""
        INPUT DATA:
        {json.dumps(input_data, indent=2)}
        
        TASK:
        Select the best items to create a curated tech digest in JSON format for the '{mode}' category.
        
        CRITICAL RULES:
        1. DUPLICATE PREVENTION: 
           - 'seen_urls' contains previously posted URLs. NEVER select any item found in this list.
           - Check closely for duplicate topics/stories even if URLs differ.
        """

        if mode == 'research':
            task_instruction += """
        2. RESEARCH SELECTION (Priority: Arxiv, HuggingFace, DeepMind, OpenAI):
           - Select ALL high-quality, relevant items found. DO NOT limit to 5.
           - STRICTLY DEDUPLICATE: If multiple feeds cover the same paper/topic, keep only the best one.
           - Exclude GitHub PRs/commits/issues/changelogs.
           - Exclude simple code releases without major significance.
           - Include: Recent papers (~7 days), AI concepts, strong engineering blogs.
           - ONLY return items with type="research" or relevant to research.
            """
        elif mode == 'news':
            task_instruction += """
        2. NEWS SELECTION (Priority: TechCrunch, Verge, Wired, VentureBeat):
           - Select ALL relevant, significant news items. DO NOT limit to 5.
           - STRICTLY DEDUPLICATE: If multiple feeds cover the same story, choose the ONE best source.
           - Focus on: Product launches, Funding, Policy, Major moves.
           - Avoid: Clickbait, duplicate topics.
           - ONLY return items with type="news" or relevant to tech news.
            """
        else: # mixed/all
             task_instruction += """
        2. SELECTION MIX:
           - Select ALL relevant Research AND News items. Provide a comprehensive digest.
             """

        task_instruction += """
        3. CONTENT STYLE:
           - Titles: Clean, unformatted text.
           - Summaries: Plain text, factual, neutral tone, <25 words.
           - Sources: Clean name (e.g., "TechCrunch", "Arxiv").
           - Diversity: Max 2 items from the same source.
        
        4. AI CONCEPTS TO COVER (if applicable):
           - MoE, SSM, Mamba, Transformers++
           - RLHF, DPO, LoRA, RAG
           - Agents (CoT, ToT), Multimodal
        
        OUTPUT FORMAT:
        Return valid JSON only. Do NOT output Markdown.
        
        JSON SCHEMA:
        {
          "items": [
            {
              "type": "📄" or "🧠" (for research) / "🔹" (for news),
              "title": "Title String",
              "summary": "Summary String",
              "source": "Source Name",
              "url": "URL"
            }
          ]
        }
        """
        
        prompt = system_instruction + task_instruction
        
        response = None
        for attempt in range(3):
            try:
                response = client.models.generate_content(
                    model='gemini-2.0-flash',
                    contents=prompt
                )
                break
            except Exception as e:
                # Catch 429 specifically
                if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                    if attempt < 2:
                        wait_time = (attempt + 1) * 20
                        print(f"⚠️ Quota exceeded (429). Retrying in {wait_time}s...")
                        time.sleep(wait_time)
                    else:
                        print("❌ Max retries for Gemini API reached.")
                        raise e
                else:
                    raise e
                    
        if not response:
             return None
        
        # Parse JSON
        raw_text = response.text.replace('```json', '').replace('```', '').strip()
        data = json.loads(raw_text)
        
        return format_digest_from_json(data, mode)
        
    except Exception as e:
        print(f"⚠️ Gemini Generation/Parsing Error: {e}")
        return None

def format_digest_from_json(data, mode):
    """Formats JSON data into Telegram MarkdownV2 string."""
    ist = pytz.timezone('Asia/Kolkata')
    today_str = datetime.now(ist).strftime("%B %d, %Y")
    now_hour = datetime.now(ist).hour
    
    header_date = escape_markdown_v2(today_str)
    
    greeting = "🌅 *GM*" if now_hour < 12 else "☕ *Good Afternoon*"
    
    topic_header = ""
    if mode == 'research':
        topic_header = "🔬 *RESEARCH & AI PAPERS*"
    elif mode == 'news':
        topic_header = "📰 *TECH NEWS & UPDATES*"
    else:
        topic_header = "🗞️ *TECH DIGEST*"

    msg = f"{greeting} — {topic_header}\n{header_date}\n\n"
    
    items = data.get('items', [])
    if not items:
         # Fallback for old schema if model hallucinates old structure
         items = data.get('research', []) + data.get('news', [])

    if not items:
        msg += "_(No updates found at this time)_\n\n"
        
    for i, item in enumerate(items):
        title = escape_markdown_v2(item.get('title', 'Untitled'))
        summary = escape_markdown_v2(item.get('summary', ''))
        source = escape_markdown_v2(item.get('source', 'Source'))
        url = item.get('url', '')
        if not url.startswith('http'): url = 'https://google.com'
            
        type_icon = item.get('type', '🔹')
        
        msg += f"{i+1}\. {type_icon} *{title}*\n{summary}\n📎 [{source}]({url})\n\n"
        
    msg += "━━━━━━━━━━━━━━━━━━━━\n🤖 _Tech News by VJ_"
    return msg

def send_telegram_message(message):
    """Sends the formatted message to Telegram, splitting if necessary."""
    if not BOT_TOKEN or not CHAT_ID:
        print("❌ Telegram config missing.")
        return False

    # Split message if too long
    max_length = 4000
    messages = []
    if len(message) > max_length:
        print(f"⚠️ Message length {len(message)} exceeds limit. Splitting...")
        # Simple split by double newline to keep items together
        parts = message.split('\n\n')
        current_chunk = ""
        for part in parts:
             if len(current_chunk) + len(part) + 2 > max_length:
                 messages.append(current_chunk)
                 current_chunk = part + "\n\n"
             else:
                 current_chunk += part + "\n\n"
        if current_chunk:
            messages.append(current_chunk)
    else:
        messages = [message]

    success = True
    for i, msg in enumerate(messages):
        if not msg.strip(): continue
        
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        payload = {
            'chat_id': CHAT_ID,
            'text': msg,
            'parse_mode': 'MarkdownV2',
            'disable_web_page_preview': True
        }
        
        try:
            response = requests.post(url, json=payload, timeout=20)
            if response.status_code == 200:
                print(f"✅ Message part {i+1}/{len(messages)} sent successfully")
            else:
                print(f"❌ Telegram Send Failed for part {i+1}: {response.text}")
                success = False
                
        except Exception as e:
            print(f"⚠️ Telegram Connection Error: {e}")
            success = False
            
    return success

def job(mode='all'):
    print(f"⏰ Starting scheduled job ({mode}) at {datetime.now()}...")
    all_news = fetch_rss_news() + fetch_reddit_news()
    
    if not all_news:
        print("⚠️ No news found! Check connections.")
        return

    # Filter based on mode if needed, though LLM handles it best, 
    # pre-filtering saves tokens and reduces noise.
    if mode == 'research':
        all_news = [n for n in all_news if n.get('type') == 'research']
    elif mode == 'news':
        all_news = [n for n in all_news if n.get('type') == 'news']
    
    if not all_news:
         print(f"⚠️ No items found for mode '{mode}'.")
         return

    # Sort by date (newest first) to prioritize fresh content
    all_news.sort(key=lambda x: x.get('published_at', ''), reverse=True)
    
    # Limit to top 60 items to prevent Token Limit Exceeded / 429 Errors
    if len(all_news) > 60:
        print(f"⚠️ Truncating input from {len(all_news)} to 60 items to save quota.")
        all_news = all_news[:60]

    seen_urls = load_seen_urls()
    digest = generate_digest(all_news, mode, seen_urls)
    
    if digest:
        success = send_telegram_message(digest)
        if success:
             new_urls = extract_urls_from_post(digest)
             save_seen_urls(seen_urls, new_urls)
             print(f"📝 Saved {len(new_urls)} new URLs to history.")
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

    print(f"🤖 GM Bot Online. Monitoring... (Press Ctrl+C to stop)")
    # For local testing without args, it runs 'all'
    # To schedule specifically locally, you'd need to adjust this loop or run via cron
    
    # Simple local schedule simulation for testing
    # schedule.every().day.at("09:00").do(job, mode='research')
    # schedule.every().day.at("14:00").do(job, mode='news')
    
    try:
        if args.mode != 'all':
             job(args.mode) # Run once if mode is specified manually
             sys.exit(0)
             
        while True:
            schedule.run_pending()
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n🛑 Bot stopped by user.")
