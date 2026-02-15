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
    # The new format is 📎 [Source](URL)
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
    # We include dot (.) and exclamation mark (!) which are common triggers of errors
    return re.sub(r'([_*\[\]()~`>#+\-=|{}.!])', r'\\\1', text)

def format_digest_from_json(data):
    """Formats JSON data into Telegram MarkdownV2 string."""
    ist = pytz.timezone('Asia/Kolkata')
    today_str = datetime.now(ist).strftime("%B %d, %Y")
    
    # No escape for today_str in this specific format as comma/space are safe
    # But if dot appears, it needs escape. safe:
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
        # Ensure url is valid
        if not url.startswith('http'): url = 'https://google.com'
            
        type_icon = item.get('type', '📄')
        
        # Structure: 1\. 📄 *Title*
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
        
        # Prepare input data
        input_data = {
            "items": news_items,
            "seen_urls": seen_urls
        }
        
        prompt = rf"""
        You are Tech News by VJ, an AI-powered daily tech news curator.
        Today is {today_str}.
        
        INPUT DATA:
        {json.dumps(input_data, indent=2)}
        
        TASK:
        Select the best items and return a JSON object.
        
        CRITICAL RULES:
        1. DUPLICATE PREVENTION: 
           - 'seen_urls' contains previously posted URLs. NEVER select these.
           - Filter out multiple items about the same story/release.
        2. RESEARCH QUALITY:
           - Exclude GitHub PRs/commits/issues.
           - Exclude Reddit threads unless they contain significant discussion/insight.
           - Prefer recent papers (last 7 days).
        3. DIVERSITY:
           - Max 2 items from same source.
           - Research section: min 3 different sources.
        4. CONTENT:
           - Research Section: 5 items (Papers 📄 or Concepts 🧠).
           - Top Stories: 3 items (News 🔹).
           - Summaries: Plain text, factual, under 25 words. No markdown.
           - Titles: Clean, no markdown.
           - URLs: Must be the original URL from input.
        
        OUTPUT FORMAT:
        Return valid JSON only. No markdown formatting in the response.
        
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
        # Could return None or try to generate plain text if needed
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
        'parse_mode': 'MarkdownV2', # Strict MarkdownV2
        'disable_web_page_preview': True
    }
    
    try:
        response = requests.post(url, json=payload, timeout=20)
        start_time = datetime.now()
        
        if response.status_code == 200:
            print(f"✅ Message sent at {start_time}")
            return True
        else:
            print(f"❌ Telegram Send Failed (MarkdownV2): {response.text}")
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

    # Load seen URLs
    seen_urls = load_seen_urls()
    
    digest = generate_digest(all_news, seen_urls)
    
    if digest:
        success = send_telegram_message(digest)
        if success:
             # Extract and save new URLs
             new_urls = extract_urls_from_post(digest)
             save_seen_urls(seen_urls, new_urls)
             print(f"📝 Saved {len(new_urls)} new URLs to history.")
    else:
        print("⚠️ Failed to generate digest.")

if __name__ == "__main__":
    if not GEMINI_API_KEY:
        print("🚨 WARNING: GEMINI_API_KEY is missing. Get a FREE key at https://aistudio.google.com/")
    if not BOT_TOKEN:
         print("🚨 WARNING: TELEGRAM_BOT_TOKEN is missing.")

    # CI/CD: Run once and exit
    if os.getenv('GITHUB_ACTIONS'):
        print("🚀 Running in GitHub Actions mode (Single execution)")
        job()
        sys.exit(0)

    # Local: Run loop
    print(f"🤖 GM Bot Online. Monitoring... (Press Ctrl+C to stop)")
    
    try:
        while True:
            schedule.run_pending()
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n🛑 Bot stopped by user.")
