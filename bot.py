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
from datetime import datetime
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

def fetch_rss_news():
    """Fetches news from defined RSS feeds."""
    news_items = []
    print("📡 Fetching RSS feeds...")
    for feed_url in RSS_FEEDS:
        try:
            feed = feedparser.parse(feed_url)
            # Limit to 5 per feed
            for entry in feed.entries[:5]:
                is_research = "research" in feed_url or "blog" in feed_url
                news_items.append({
                    "title": entry.title,
                    "summary": clean_html(getattr(entry, 'summary', '')),
                    "source": feed.feed.get('title', 'Unknown Source'),
                    "url": entry.link,
                    "published_at": getattr(entry, 'published', datetime.now().isoformat()),
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
        url = f"https://www.reddit.com/r/{sub}/top/.rss?t=day&limit=3"
        try:
            response = requests.get(url, headers=headers, timeout=10)
            if response.status_code == 200:
                feed = feedparser.parse(response.content)
                # Limit to 5 per subreddit
                for entry in feed.entries[:5]:
                    is_research = sub in ["MachineLearning", "LocalLLaMA", "singularity"]
                    news_items.append({
                        "title": entry.title,
                        "summary": "Reddit Discussion",
                        "source": f"r/{sub}",
                        "url": entry.link,
                        "published_at": getattr(entry, 'updated', datetime.now().isoformat()),
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

def generate_digest(news_items, seen_urls=None):
    """Uses Gemini to generate the Telegram message via JSON."""
    if seen_urls is None:
        seen_urls = []
        
    if not GEMINI_API_KEY:
        print("❌ Error: GEMINI_API_KEY is not set.")
        return None

    print(f"🤖 Generating digest for {len(news_items)} items using Gemini...")
    
    try:
        client = genai.Client(api_key=GEMINI_API_KEY)
        
        ist = pytz.timezone('Asia/Kolkata')
        today_str = datetime.now(ist).strftime("%B %d, %Y")
        
        input_data = {
            "items": news_items,
            "seen_urls": seen_urls
        }
        
        prompt = rf"""
        You are Tech News by VJ, an AI-powered daily tech news curator for @technewsbyvj.
        Today is {today_str}.
        
        INPUT DATA:
        {json.dumps(input_data, indent=2)}
        
        TASK:
        Select the best items to create a curated tech digest in JSON format.
        
        CRITICAL RULES:
        1. DUPLICATE PREVENTION: 
           - 'seen_urls' contains previously posted URLs. NEVER select any item found in this list.
           - Check closely for duplicate topics/stories even if URLs differ.
        
        2. RESEARCH SELECTION (Priority: Arxiv, HuggingFace, DeepMind, OpenAI):
           - Select exactly 5 items.
           - Exclude GitHub PRs/commits/issues/changelogs.
           - Exclude simple code releases without major significance.
           - Include: Recent papers (~7 days), AI concepts, strong engineering blogs.
        
        3. NEWS SELECTION (Priority: TechCrunch, Verge, Wired, VentureBeat):
           - Select exactly 3 items.
           - Focus on: Product launches, Funding, Policy, Major moves.
           - Avoid: Clickbait, duplicate topics.
        
        4. CONTENT STYLE:
           - Titles: Clean, unformatted text.
           - Summaries: Plain text, factual, neutral tone, <25 words.
           - Sources: Clean name (e.g., "TechCrunch", "Arxiv").
           - Diversity: Max 2 items from the same source.
        
        5. AI CONCEPTS TO COVER:
           - MoE, SSM, Mamba, Transformers++
           - RLHF, DPO, LoRA, RAG
           - Agents (CoT, ToT), Multimodal
        
        OUTPUT FORMAT:
        Return valid JSON only. Do NOT output Markdown.
        
        JSON SCHEMA:
        {{
          "research": [
            {{
              "type": "📄" or "🧠",
              "title": "Title String",
              "summary": "Summary String",
              "source": "Source Name",
              "url": "URL"
            }}
          ],
          "news": [
            {{
              "headline": "Headline String",
              "summary": "Summary String",
              "source": "Source Name",
              "url": "URL"
            }}
          ]
        }}
        """
        
        response = client.models.generate_content(
            model='gemini-2.0-flash',
            contents=prompt
        )
        
        # Parse JSON
        raw_text = response.text.replace('```json', '').replace('```', '').strip()
        data = json.loads(raw_text)
        
        return format_digest_from_json(data)
        
    except Exception as e:
        print(f"⚠️ Gemini Generation/Parsing Error: {e}")
        return None

def send_telegram_message(message):
    """Sends the formatted message to Telegram."""
    if not BOT_TOKEN or not CHAT_ID:
        print("❌ Telegram config missing.")
        return

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        'chat_id': CHAT_ID,
        'text': message,
        'parse_mode': 'MarkdownV2',
        'disable_web_page_preview': True
    }
    
    try:
        response = requests.post(url, json=payload, timeout=20)
        if response.status_code == 200:
            print(f"✅ Message sent successfully")
            return True
        else:
            print(f"❌ Telegram Send Failed: {response.text}")
            return False
            
    except Exception as e:
        print(f"⚠️ Telegram Connection Error: {e}")
        return False

def job():
    print(f"⏰ Starting scheduled job at {datetime.now()}...")
    all_news = fetch_rss_news() + fetch_reddit_news()
    
    if not all_news:
        print("⚠️ No news found! Check connections.")
        return

    seen_urls = load_seen_urls()
    digest = generate_digest(all_news, seen_urls)
    
    if digest:
        success = send_telegram_message(digest)
        if success:
             new_urls = extract_urls_from_post(digest)
             save_seen_urls(seen_urls, new_urls)
             print(f"📝 Saved {len(new_urls)} new URLs to history.")
    else:
        print("⚠️ Failed to generate digest.")

if __name__ == "__main__":
    if not GEMINI_API_KEY:
        print("🚨 WARNING: GEMINI_API_KEY is missing.")
    if not BOT_TOKEN:
         print("🚨 WARNING: TELEGRAM_BOT_TOKEN is missing.")

    if os.getenv('GITHUB_ACTIONS'):
        print("🚀 Running in GitHub Actions mode (Single execution)")
        job()
        sys.exit(0)

    print(f"🤖 GM Bot Online. Monitoring... (Press Ctrl+C to stop)")
    try:
        while True:
            schedule.run_pending()
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n🛑 Bot stopped by user.")
