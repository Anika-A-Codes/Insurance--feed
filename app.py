import streamlit as st
import feedparser
import google.generativeai as genai
from datetime import datetime, timedelta
import time
import re

st.set_page_config(
    page_title="Insurance Intelligence Feed",
    page_icon="shield",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ---------- RSS FEEDS (all free, no API key) ----------
FEEDS = [
    ("Reinsurance News",        "https://www.reinsurancene.ws/feed/"),
    ("Coverager",               "https://coverager.com/feed/"),
    ("Fintech Global",          "https://fintech.global/feed/"),
    ("Insurance Journal",       "https://www.insurancejournal.com/feed/"),
    ("Insurance Business Mag",  "https://www.insurancebusinessmag.com/feed/"),
    ("IBS Intelligence",        "https://ibsintelligence.com/feed/"),
    ("Tech.eu",                 "https://tech.eu/feed/"),
]

# Add your Google Alerts RSS URLs here (optional, instructions in README)
GOOGLE_ALERT_FEEDS = [
    # ("Alert: parametric insurance", "https://www.google.com/alerts/feeds/YOUR_ID/YOUR_FEED"),
]

ALL_FEEDS = FEEDS + GOOGLE_ALERT_FEEDS

THEMES = [
    "AI / Model Risk", "Cyber", "Parametric", "Embedded Insurance",
    "Marine / Logistics", "Health / Life", "Climate / ESG", "Anti-Fraud",
    "Claims", "Underwriting / Pricing", "Mobility", "M&A / Expansion",
    "Political Violence", "Carbon Insurance", "Space"
]

ACTIVITY_TYPES = [
    "Funding", "Product Launch", "Partnership",
    "Market Expansion", "Insurer Move", "Other Strategic Move"
]

# ---------- PROMPT ----------
PROMPT = """You are a senior insurance strategy analyst writing for an investment-grade insurance intelligence feed.

Analyse the article below. If it is NOT relevant to insurance, insurtech, reinsurance, or insurance-adjacent financial services strategy, respond with exactly: SKIP

If relevant, write a formatted intelligence entry using this exact structure:

**[Company Name]**
Date: [YYYY-MM-DD]

[2-3 sentences. Match the format to the activity type:
- Funding: State company name and what it does, amount raised, lead investor, what the capital funds, and the strategic signal for the broader market.
- Product Launch: What launched, the key features or coverage terms, and why it matters competitively.
- Partnership: Who partnered, what was agreed, and the structural implication for the market.
- M&A or Expansion: Who, what, deal terms if known, and strategic rationale.]

[Media](EXACT_URL_FROM_ARTICLE)

Tags: [Line of Business], [Theme], [Activity Type], [Geography]

STRICT RULES:
- No em dashes anywhere. Use hyphens or rewrite the sentence.
- Date must be YYYY-MM-DD. Use the article publication date.
- Theme must be exactly one of: AI / Model Risk, Cyber, Parametric, Embedded Insurance, Marine / Logistics, Health / Life, Climate / ESG, Anti-Fraud, Claims, Underwriting / Pricing, Mobility, M&A / Expansion, Political Violence, Carbon Insurance, Space
- Activity Type must be exactly one of: Funding, Product Launch, Partnership, Market Expansion, Insurer Move, Other Strategic Move
- Only include genuinely strategic stories: funding rounds, product launches, major partnerships, M&A, market entry. Skip awards, speaking engagements, opinion pieces, minor hires, and regulatory routine.
- The [Media](URL) link must use the actual article URL provided below, not a placeholder.
"""

# ---------- HELPERS ----------
def fetch_raw_articles(days: int) -> list[dict]:
    articles = []
    cutoff = datetime.now() - timedelta(days=days)
    seen_urls = set()

    for name, url in ALL_FEEDS:
        try:
            feed = feedparser.parse(url, request_headers={"User-Agent": "Mozilla/5.0"})
            for entry in feed.entries[:20]:
                link = entry.get("link", "")
                if link in seen_urls:
                    continue
                seen_urls.add(link)

                pub = entry.get("published_parsed")
                pub_dt = datetime(*pub[:6]) if pub else datetime.now()
                if pub_dt < cutoff:
                    continue

                summary = re.sub(r"<[^>]+>", "", entry.get("summary", ""))[:600]
                articles.append({
                    "title":   entry.get("title", ""),
                    "url":     link,
                    "summary": summary,
                    "source":  name,
                    "date":    pub_dt.strftime("%Y-%m-%d"),
                })
        except Exception:
            pass

    return articles


def extract_date(story: str) -> str:
    for line in story.splitlines():
        if line.strip().startswith("Date:"):
            return line.replace("Date:", "").strip()
    return "0000-00-00"


def extract_tags(story: str) -> dict:
    for line in story.splitlines():
        if line.strip().startswith("Tags:"):
            parts = [p.strip().strip("[]") for p in line.replace("Tags:", "").split(",")]
            return {
                "lob":      parts[0] if len(parts) > 0 else "",
                "theme":    parts[1] if len(parts) > 1 else "",
                "activity": parts[2] if len(parts) > 2 else "",
                "geo":      parts[3] if len(parts) > 3 else "",
            }
    return {"lob": "", "theme": "", "activity": "", "geo": ""}


@st.cache_data(ttl=21600, show_spinner=False)
def build_feed(days: int) -> list[str]:
    api_key = st.secrets["GEMINI_API_KEY"]
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel("gemini-1.5-flash")

    articles = fetch_raw_articles(days)
    if not articles:
        return []

    results = []
    bar = st.progress(0, text="Building intelligence feed...")

    for i, article in enumerate(articles):
        bar.progress((i + 1) / len(articles),
                     text=f"Analysing {i + 1} of {len(articles)}: {article['title'][:55]}...")
        try:
            response = model.generate_content(
                f"{PROMPT}\n\n"
                f"Title: {article['title']}\n"
                f"URL: {article['url']}\n"
                f"Date: {article['date']}\n"
                f"Source: {article['source']}\n"
                f"Summary: {article['summary']}"
            )
            text = response.text.strip()
            if text and text != "SKIP" and len(text) > 80:
                results.append(text)
        except Exception:
            pass
        time.sleep(2)  # stay within Gemini free tier (15 req/min)

    bar.empty()
    results.sort(key=extract_date, reverse=True)
    return results


# ---------- UI ----------
st.title("Insurance Intelligence Feed")

with st.sidebar:
    st.header("Filters")

    days = st.select_slider(
        "Time window",
        options=[7, 14, 30, 60, 90],
        value=30,
        format_func=lambda x: f"Last {x} days"
    )

    theme_filter = st.multiselect("Theme", THEMES)
    activity_filter = st.multiselect("Activity type", ACTIVITY_TYPES)
    geo_search = st.text_input("Geography contains", placeholder="e.g. Europe")

    st.divider()
    if st.button("Refresh feed", type="primary", use_container_width=True):
        st.cache_data.clear()
        st.rerun()
    st.caption("Auto-refreshes every 6 hours. Use button to force update.")

# Load
with st.spinner("Loading feed..."):
    all_stories = build_feed(days)

if not all_stories:
    st.info("No stories loaded yet. Check your GEMINI_API_KEY secret and click Refresh.")
    st.stop()

# Apply filters
filtered = []
for story in all_stories:
    tags = extract_tags(story)
    if theme_filter and not any(t.lower() in tags["theme"].lower() for t in theme_filter):
        continue
    if activity_filter and not any(a.lower() in tags["activity"].lower() for a in activity_filter):
        continue
    if geo_search and geo_search.lower() not in tags["geo"].lower():
        continue
    filtered.append(story)

# Header metrics
col1, col2, col3 = st.columns(3)
col1.metric("Stories", len(filtered))
col2.metric("Sources", len(ALL_FEEDS))
col3.metric("Updated", datetime.now().strftime("%Y-%m-%d %H:%M"))

st.divider()

# Render stories
if not filtered:
    st.warning("No stories match the current filters.")
else:
    for story in filtered:
        st.markdown(story, unsafe_allow_html=False)
        st.divider()

---

### File 4 of 4 - type filename: `README.md`

```
# Insurance Intelligence Feed

Automated insurance intelligence dashboard. Free to run.

## Setup
1. Get free Gemini API key at aistudio.google.com/app/apikey
2. Deploy this repo to share.streamlit.io
3. Add GEMINI_API_KEY in Streamlit secrets settings
```

---

## Order to add them on GitHub

1. Create repo (name: `insurance-feed`, Public)
2. Click **"creating a new file"**
3. Add `requirements.txt` first - paste content, commit
4. Click **"Add file" > "Create new file"** for each remaining one
5. Add `app.py` - paste content, commit
6. Add `.gitignore` - paste content, commit
7. Add `README.md` - paste content, commit

When all 4 files show in the repo, you are ready to go to Streamlit.
