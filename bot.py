import os
import sys
import time
import requests
import schedule
import feedparser
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
            # Increased limit to 5
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
                # Increased limit to 5
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

def generate_digest(news_items):
    """Uses Gemini to generate the Telegram message."""
    if not GEMINI_API_KEY:
        print("❌ Error: GEMINI_API_KEY is not set.")
        return None

    print(f"🤖 Generating digest for {len(news_items)} items using Gemini...")
    
    try:
        client = genai.Client(api_key=GEMINI_API_KEY)
        
        today_str = datetime.now().strftime("%B %d, %Y")
        time_str = datetime.now().strftime("%H:%M")
        
        # Use raw f-string to handle backslashes better
        prompt = rf"""
        You are Tech News by VJ, an AI-powered daily tech news curator.
        Today is {today_str}. Time is {time_str} IST.
        
        INPUT DATA:
        {str(news_items)}
        
        TASK:
        Create a "Good Morning" tech digest for a Telegram channel.
        Do NOT include any introductory text like "Here is the digest". Output ONLY the formatted message.
        
        STRICT OUTPUT FORMAT (MarkdownV2):
        🌅 *GM! Tech News by VJ* — {today_str}

        🔬 *RESEARCH & AI CONCEPTS*

        1\. 📄 *{{PAPER/CONCEPT TITLE 1}}*
        _{{One-sentence plain-English explanation of key finding or concept}}_
        📎 [Source Name](URL)

        2\. 🧠 *{{PAPER/CONCEPT TITLE 2}}*
        _{{One-sentence plain-English explanation}}_
        📎 [Source Name](URL)

        3\. 📄 *{{PAPER/CONCEPT TITLE 3}}*
        _{{One-sentence plain-English explanation}}_
        📎 [Source Name](URL)

        4\. 🧠 *{{PAPER/CONCEPT TITLE 4}}*
        _{{One-sentence plain-English explanation}}_
        📎 [Source Name](URL)

        5\. 📄 *{{PAPER/CONCEPT TITLE 5}}*
        _{{One-sentence plain-English explanation}}_
        📎 [Source Name](URL)

        📰 *TOP STORIES*

        1\. 🔹 *{{HEADLINE 1}}*
        _{{One-sentence professional summary under 20 words}}_
        📎 [Source Name](URL)

        2\. 🔹 *{{HEADLINE 2}}*
        _{{One-sentence professional summary under 20 words}}_
        📎 [Source Name](URL)

        3\. 🔹 *{{HEADLINE 3}}*
        _{{One-sentence professional summary under 20 words}}_
        📎 [Source Name](URL)

        ━━━━━━━━━━━━━━━━━━━━
        🤖 _Tech News by VJ \| {time_str} IST_
        
        RULES:
        - SECTION 1: RESEARCH (Items 1-5). Use 📄 for papers, 🧠 for concepts. First 5 items must be research/concepts.
        - SECTION 2: TOP STORIES (Items 1-3). Specifically the hottest industry news.
        - Prioritize AI research sources (arXiv, DeepMind, OpenAI) for the first section.
        - Summaries must be factual, neutral, <20 words.
        - NO clickbait.
        - CRITICAL ESCAPING RULES: 
          - You MUST backslash-escape ALL of these characters: . ! ( ) - _ * [ ] ~ ` > # + = | {{ }}
          - Example: "GM!" -> "GM\!"
          - Example: "GPT-4" -> "GPT\-4"
          - Example: "v1.0" -> "v1\.0"
          - Example: "1." -> "1\." (in lists)
        - NEVER escape characters inside the URL part of a link: [Title](https://example.com) is correct.
        """
        
        response = client.models.generate_content(
            model='gemini-2.0-flash',
            contents=prompt
        )
        return response.text
        
    except Exception as e:
        print(f"⚠️ Gemini Generation Error: {e}")
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
        if response.status_code == 200:
            print(f"✅ Message sent at {datetime.now()}")
        else:
            print(f"❌ Telegram Send Failed: {response.text}")
    except Exception as e:
        print(f"⚠️ Telegram Connection Error: {e}")

def job():
    print(f"⏰ Starting scheduled job at {datetime.now()}...")
    all_news = fetch_rss_news() + fetch_reddit_news()
    
    if not all_news:
        print("⚠️ No news found! Check connections.")
        return

    digest = generate_digest(all_news)
    
    if digest:
        send_telegram_message(digest)
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
    
    # job() # Run once for testing
    
    try:
        while True:
            schedule.run_pending()
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n🛑 Bot stopped by user.")
