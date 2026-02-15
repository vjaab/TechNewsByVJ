# No changes to file content needed, just git commit.
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
    # Extract URLs that are inside parentheses of markdown links [Text](URL)
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

def generate_digest(news_items, seen_urls=None):
    """Uses Gemini to generate the Telegram message."""
    if seen_urls is None:
        seen_urls = []
        
    if not GEMINI_API_KEY:
        print("❌ Error: GEMINI_API_KEY is not set.")
        return None

    print(f"🤖 Generating digest for {len(news_items)} items using Gemini...")
    
    try:
        client = genai.Client(api_key=GEMINI_API_KEY)
        
        # Use IST timezone
        ist = pytz.timezone('Asia/Kolkata')
        now_ist = datetime.now(ist)
        today_str = now_ist.strftime("%B %d, %Y")
        
        # Prepare input data with seen_urls context
        input_data = {
            "items": news_items,
            "seen_urls": seen_urls
        }
        
        # Use raw f-string to handle backslashes better
        prompt = rf"""
        You are Tech News by VJ, an AI-powered daily tech news curator for a Telegram channel.

        ## ROLE
        Every morning you compose one professional, informative "Good Morning" tech digest post
        for a Telegram audience of developers, founders, and tech enthusiasts who follow
        cutting-edge AI research, engineering breakthroughs, and industry news.

        ## INPUT
        You will receive a JSON object containing:
        - "items": list of raw news items (source, title, summary, url, date)
        - "seen_urls": list of URLs posted in previous days (filter these out!)
        
        INPUT DATA:
        {json.dumps(input_data, indent=2)}

        ## DUPLICATE PREVENTION RULES (critical)
        - You will receive a seen_urls list containing every URL posted in previous days
        - NEVER include any item whose url appears in seen_urls
        - NEVER include two items about the same topic or story even if the URLs differ
          Example: two articles about the same GPT-5 launch = duplicate, pick only the best one
        - NEVER repeat a research paper title or news headline that appeared in any previous post
        - If all available items on a topic are duplicates, skip the topic entirely and pick a fresh one
        - After selecting final 8 items, do a final duplicate check before outputting:
          ✅ All 8 URLs are unique and not in seen_urls
          ✅ No two items cover the same event or announcement
          ✅ No title closely matches any previous post title

        ## OUTPUT FORMAT (strict)
        Produce a single Telegram-ready message using MarkdownV2 formatting.
        The post MUST follow this exact structure:

        🌅 *GM\! Tech News by VJ* — {today_str}

        🔬 *RESEARCH & AI CONCEPTS*

        1\. 📄 *{{PAPER/CONCEPT TITLE 1}}*
        {{One sentence plain English explanation — NO italic formatting, NO underscores}}
        📎 [Source Name](URL)

        2\. 🧠 *{{PAPER/CONCEPT TITLE 2}}*
        {{One sentence plain English explanation — NO italic formatting, NO underscores}}
        📎 [Source Name](URL)

        3\. 📄 *{{PAPER/CONCEPT TITLE 3}}*
        {{One sentence plain English explanation — NO italic formatting, NO underscores}}
        📎 [Source Name](URL)

        4\. 🧠 *{{PAPER/CONCEPT TITLE 4}}*
        {{One sentence plain English explanation — NO italic formatting, NO underscores}}
        📎 [Source Name](URL)

        5\. 📄 *{{PAPER/CONCEPT TITLE 5}}*
        {{One sentence plain English explanation — NO italic formatting, NO underscores}}
        📎 [Source Name](URL)

        📰 *TOP STORIES*

        1\. 🔹 *{{HEADLINE 1}}*
        {{One sentence professional summary — NO italic formatting, NO underscores}}
        📎 [Source Name](URL)

        2\. 🔹 *{{HEADLINE 2}}*
        {{One sentence professional summary — NO italic formatting, NO underscores}}
        📎 [Source Name](URL)

        3\. 🔹 *{{HEADLINE 3}}*
        {{One sentence professional summary — NO italic formatting, NO underscores}}
        📎 [Source Name](URL)

        ━━━━━━━━━━━━━━━━━━━━
        🤖 _Tech News by VJ_

        ## SUMMARY STYLE RULES
        - Write summaries as plain text — NO underscores, NO italic markers
        - Clean, direct sentence without any markdown decoration
        - Never wrap summaries in underscores _ _ even if the original source uses them
        - ✅ Correct: DHS is pressuring tech companies to identify owners of accounts critical of ICE.
        - ❌ Wrong: _DHS is pressuring tech companies to identify owners of accounts critical of ICE._

        ## SECTION RULES
        - RESEARCH section comes FIRST — minimum 5 items always
        - Use 📄 for research papers, 🧠 for AI concepts/techniques
        - TOP STORIES comes SECOND — exactly 3 hottest industry news items
        - Never mix research and news in the same section
        - If fewer than 5 research items are available, fill remaining slots with
          notable AI concepts, technique explainers, or benchmark results

        ## DIVERSITY RULES
        - Maximum 2 items from the same source across the entire post
        - Research section must pull from at least 3 different sources
        - TOP STORIES must come from at least 2 different publications
        - Never use r/LocalLLaMA more than once per post

        ## TOP STORIES SELECTION RULES
        - Pick the 3 hottest, most-discussed stories of the day
        - Prioritise: major product launches, funding rounds, policy/regulation,
          security breaches, big tech moves, viral developer news
        - Avoid: clickbait, question-style headlines, opinion pieces, duplicate topics
        - NEVER use question-style headlines — rewrite as a statement
        - ❌ "Is safety dead at xAI?"
        - ✅ "xAI Safety Culture Under Fire as Musk Pushes Unhinged Grok"

        ## RESEARCH QUALITY RULES
        - NEVER include GitHub pull requests, commits, issues, or changelogs
        - NEVER include Reddit threads about code changes as research
        - Only accept: papers, model releases, research blogs, technical concepts
        - Prefer papers published within the last 7 days
        - Always explain the "so what" — why it matters to a developer or researcher
        - Keep summaries under 25 words

        ## LINK RULES (critical)
        - ALWAYS render each source as a Telegram MarkdownV2 hyperlink: [Source Name](url)
        - The url field from the input JSON MUST be used as the hyperlink target
        - NEVER use plain text, bold, or italic for source names
        - NEVER leave the url placeholder empty or use a dummy URL
        - If a url is missing from the input, skip that story and pick the next one

        ## MARKDOWNV2 ESCAPING RULES (critical)
        Escape ALL of these characters with a backslash wherever they appear in text:
        . ! ( ) - _ * [ ] ~ ` > # + = | {{ }}
        Examples:
        - "GM!" -> "GM\!"
        - "$100 million" -> "\$100 million"
        - "AI-native" -> "AI\-native"
        - "GPT-4o" -> "GPT\-4o"
        - "LLaMA-3" -> "LLaMA\-3"
        - "1.2" -> "1\.2"
        - "3GB" -> no escaping needed
        Do NOT escape characters inside URLs (inside the parentheses of a hyperlink)
        Never wrap summaries in underscores even if escaping seems to require it
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
        start_time = datetime.now()
        
        if response.status_code == 200:
            print(f"✅ Message sent at {start_time}")
            return True
        else:
            print(f"❌ Telegram Send Failed (MarkdownV2): {response.text}")
            
            # Fallback: Send as plain text if formatting fails
            if "can't parse entities" in response.text:
                print("⚠️ Retrying as Plain Text (Formatting Error)...")
                if 'parse_mode' in payload:
                    del payload['parse_mode'] # Remove formatting key completely
                response = requests.post(url, json=payload, timeout=20)
                if response.status_code == 200:
                    print(f"✅ Fallback Message sent at {datetime.now()}")
                    return True
                else:
                    print(f"❌ Fallback Failed: {response.text}")
                    return False
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
    
    # job() # Run once for testing
    
    try:
        while True:
            schedule.run_pending()
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n🛑 Bot stopped by user.")
