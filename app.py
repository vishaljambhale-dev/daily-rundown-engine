import streamlit as st
import asyncio
import datetime
import urllib.parse
import requests
import bs4
import pyshorteners
import google.generativeai as genai
from telethon import TelegramClient
from telethon.sessions import StringSession
import concurrent.futures
import time

# --- PAGE CONFIGURATION ---
st.set_page_config(page_title="Daily Rundown Engine", layout="wide")

# --- CUSTOM CSS FOR MODERN UI ---
st.markdown("""
    <style>
    /* Clean up top padding */
    .block-container { padding-top: 2rem; }
    
    /* Round inputs and buttons */
    .stTextInput input, .stSelectbox div[data-baseweb="select"], .stTextArea textarea {
        border-radius: 8px !important;
    }
    .stButton button {
        border-radius: 8px !important;
        font-weight: 600 !important;
    }
    
    /* Fix Checkbox and Toggle Alignment in Table Row */
    div[data-testid="stCheckbox"] {
        padding-top: 8px;
    }
    div[data-testid="stToggle"] {
        padding-top: 4px;
    }
    
    /* Style Table Headers */
    .table-header {
        font-weight: 600;
        color: #9aa0a6;
        font-size: 13px;
        text-transform: uppercase;
        letter-spacing: 0.5px;
        border-bottom: 1px solid #333333;
        padding-bottom: 8px;
        margin-bottom: 12px;
    }
    
    /* Clean text display for successful fetches */
    .success-text {
        padding-top: 8px;
        font-size: 14px;
        color: #e0e0e0;
    }
    
    /* Subtly elevate the export section */
    div[data-testid="stVerticalBlock"] > div:last-child {
        background-color: #1a1a1a;
        padding: 20px;
        border-radius: 12px;
        border: 1px solid #333333;
    }
    </style>
""", unsafe_allow_html=True)

# --- SECRETS & SETUP ---
API_ID = st.secrets["TELEGRAM_API_ID"]
API_HASH = st.secrets["TELEGRAM_API_HASH"]
CHANNEL = st.secrets["CHANNEL_NAME"]
if "GEMINI_API_KEY" in st.secrets and st.secrets["GEMINI_API_KEY"] != "pending":
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])

shortener = pyshorteners.Shortener()
CATEGORIES = [
    "ECONOMY & CURRENT AFFAIRS",
    "INTERNATIONAL",
    "INDUSTRY & COMPANY SPECIFIC",
    "QUARTERLY RESULTS"
]

# --- COLAB SCRAPER CONFIGURATION ---
headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Accept-Language': 'en-US,en;q=0.9',
    'Referer': 'https://www.google.com/'
}

blocked_flags = [
    "bloomberg", "reuters.com", "reuters", "are you a robot",
    "attention required", "403 forbidden", "access denied",
    "just a moment", "cloudflare", "the new york times",
    "nytimes", "subscribe to read", "log in",
    "please check", "enable javascript", "security check",
    "unusual activity", "browser settings", "verify you are human",
    "page not found", "404 not found", "error 404"
]

suffixes_to_remove = [
    " - report: moneycontrol.com", " - moneycontrol.com", " | moneycontrol.com",
    " - moneycontrol", " | moneycontrol", " - cnbctv18", " | cnbctv18",
    " - cnbc tv18", " | cnbc tv18", " - the economic times", " | the economic times",
    " - ndtv profit", " | ndtv profit", " - livemint", " | livemint",
    " - business standard", " | business standard"
]

garbage_brands = [
    "moneycontrol", "cnbctv18", "economic times",
    "livemint", "ndtv", "business standard"
]

# --- HELPER FUNCTIONS ---
async def fetch_telegram_posts(start_time, end_time):
    session_str = st.secrets["TELEGRAM_STRING_SESSION"]
    client = TelegramClient(StringSession(session_str), API_ID, API_HASH)
    
    await client.start()
    
    posts = []
    async for m in client.iter_messages(CHANNEL, limit=250):
        if m.date and start_time <= m.date <= end_time and m.text and len(m.text.strip()) > 10:
            posts.append({
                "text": m.text.replace("\n", " ").strip(),
                "date": m.date.astimezone(datetime.timezone(datetime.timedelta(hours=5, minutes=30)))
            })
            
    await client.disconnect()
    return posts

def extract_and_categorize(url):
    headline = ""
    tinyurl = ""
    
    try:
        response = requests.get(url, headers=headers, timeout=10)
        soup = bs4.BeautifulSoup(response.content, 'html.parser')

        og_title = soup.find("meta", property="og:title")
        if og_title and og_title.get("content"):
            headline = og_title["content"].strip()
        elif soup.h1:
            headline = soup.h1.get_text(strip=True)
        elif soup.title:
            headline = soup.title.get_text(strip=True)

        if headline:
            headline = headline.replace('\xa0', ' ').strip()
            headline_lower = headline.lower()

            for suffix in suffixes_to_remove:
                if headline_lower.endswith(suffix):
                    headline = headline[:-len(suffix)].strip()
                    headline_lower = headline.lower()

            delimiters = [" | ", " - ", " — ", " – ", " :: ", " |"]
            for delim in delimiters:
                if delim in headline:
                    parts = headline.rsplit(delim, 1)
                    tail_text = parts[1].strip()
                    tail_lower = tail_text.lower()

                    is_garbage = (len(tail_text.split()) <= 3) or any(brand in tail_lower for brand in garbage_brands)
                    if is_garbage:
                        headline = parts[0].strip()

        is_blocked = False
        if not headline or len(headline.split()) < 4:
            is_blocked = True
        else:
            for flag in blocked_flags:
                if flag in headline.lower():
                    is_blocked = True
                    break
        
        if is_blocked:
            headline = "[ACTION REQUIRED] Manual Headline Needed"

    except Exception:
        headline = "[ACTION REQUIRED] Manual Headline Needed"

    max_retries = 3
    for attempt in range(max_retries):
        try:
            if attempt > 0:
                time.sleep(2 ** attempt)
            tinyurl = shortener.tinyurl.short(url)
            if tinyurl:
                break
        except Exception:
            pass
            
    if not tinyurl:
        tinyurl = "[ACTION REQUIRED] Manual Shortlink Needed"

    cat = CATEGORIES[0]
    gemini_key = st.secrets.get("GEMINI_API_KEY", "")
    
    if gemini_key and gemini_key != "pending":
        try:
            model = genai.GenerativeModel("gemini-2.5-flash")
            prompt = f"Categorize into ONE of: ECONOMY & CURRENT AFFAIRS, INTERNATIONAL, INDUSTRY & COMPANY SPECIFIC, QUARTERLY RESULTS. Headline: '{headline}'. Return ONLY category name."
            cat_response = model.generate_content(prompt).text.strip()
            if cat_response in CATEGORIES:
                cat = cat_response
        except Exception:
            pass
            
    return {"url": url, "tiny": tinyurl, "headline": headline, "cat": cat}

# --- SIDEBAR NAVIGATION ---
# Custom branded title for the sidebar
st.sidebar.markdown("""
    <div style="margin-bottom: 25px; padding-top: 10px;">
        <h1 style="font-size: 1.9rem; font-weight: 800; margin: 0; color: #e0e0e0; line-height: 1.2;">
            Daily Rundown<br>
            <span style="color: #06b6d4;">Engine</span>
        </h1>
    </div>
""", unsafe_allow_html=True)

app_mode = st.sidebar.radio(
    "Navigation",
    ["Step 1: Fetch Posts", "Step 2: Process Data"],
    label_visibility="collapsed"
)

st.sidebar.divider()
st.sidebar.subheader("Actions")

fetch_clicked = False
if app_mode == "Step 1: Fetch Posts":
    st.sidebar.write("Click below to fetch data based on your parameters.")
    fetch_clicked = st.sidebar.button("Fetch Telegram Data", type="primary", use_container_width=True)
elif app_mode == "Step 2: Process Data":
    st.sidebar.write("Paste your links in the main window to begin data processing.")

# --- MAIN AREA: STEP 1 ---
if app_mode == "Step 1: Fetch Posts":
    st.header("Step 1: Fetch Telegram Posts")
    st.write("Extract recent updates from the designated source channel.")
    
    st.subheader("Fetch Parameters")
    
    fetch_type = st.radio(
        "Select Fetch Duration", 
        ["One Day", "Multi Day"], 
        horizontal=True,
        label_visibility="collapsed"
    )
    
    now_ist = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=5, minutes=30)
    today_date = now_ist.date()
    
    st.write("")
    
    if fetch_type == "One Day":
        col_date, _ = st.columns([1, 1])
        selected_date = col_date.date_input("Select Date", value=today_date)
        
        col_st, col_et = st.columns(2)
        start_t = col_st.time_input("Start Time (IST)", value=datetime.time(12, 0))
        end_t = col_et.time_input("End Time (IST)", value=datetime.time(22, 0))
        
        start_dt_ist = datetime.datetime.combine(selected_date, start_t)
        end_dt_ist = datetime.datetime.combine(selected_date, end_t)
        
    else:
        col_sd, col_ed = st.columns(2)
        start_d = col_sd.date_input("Start Date", value=today_date - datetime.timedelta(days=2))
        end_d = col_ed.date_input("End Date", value=today_date)
        
        col_st, col_et = st.columns(2)
        start_t = col_st.time_input("Start Time on Start Date (IST)", value=datetime.time(22, 0))
        end_t = col_et.time_input("End Time on End Date (IST)", value=datetime.time(12, 0))
        
        start_dt_ist = datetime.datetime.combine(start_d, start_t)
        end_dt_ist = datetime.datetime.combine(end_d, end_t)

    ist_offset = datetime.timedelta(hours=5, minutes=30)
    start_time_utc = start_dt_ist.replace(tzinfo=datetime.timezone.utc) - ist_offset
    end_time_utc = end_dt_ist.replace(tzinfo=datetime.timezone.utc) - ist_offset

    st.divider()

    if fetch_clicked:
        if start_time_utc >= end_time_utc:
            st.error("Error: Start time must be strictly before End time.")
        else:
            with st.spinner("Connecting to Telegram & Fetching Messages..."):
                try:
                    posts_data = asyncio.run(fetch_telegram_posts(start_time_utc, end_time_utc))
                    st.session_state.posts = posts_data
                    st.success(f"Successfully fetched {len(posts_data)} posts for the selected window.")
                except Exception as e:
                    st.error(f"Error fetching posts: {e}")
                
    if "posts" in st.session_state and st.session_state.posts:
        st.write("### Select relevant posts to generate search queries:")
        
        selected_queries = []
        for i, post_obj in enumerate(st.session_state.posts):
            post_text = post_obj["text"]
            formatted_time = post_obj["date"].strftime("%b %d, %I:%M %p")
            
            label = f"**[{formatted_time}]** {post_text}"
            if st.checkbox(label, key=f"post_{i}"):
                selected_queries.append(post_text)
                
        if st.button("Generate Search Links", type="primary"):
            if not selected_queries:
                st.warning("Please check at least one post.")
            else:
                st.divider()
                st.write("### Batch Search URLs for Chrome Extension")
                st.write("Hover over the box below, click the **Copy icon** in the top right corner, paste into your **Open Multiple URLs** extension, and hit **Open URLs**:")
                
                search_urls = [f"https://www.google.com/search?q={urllib.parse.quote(q[:120])}" for q in selected_queries]
                urls_formatted = "\n".join(search_urls)
                
                st.code(urls_formatted, language="text")

# --- MAIN AREA: STEP 2 ---
elif app_mode == "Step 2: Process Data":
    st.header("Step 2: Process & Export Data")
    st.write("Paste the article URLs you copied using TabCopy. The engine will automatically extract headlines, shorten links, and categorize the news.")
    
    raw_urls = st.text_area("URLs Input", height=150, label_visibility="collapsed", placeholder="https://www.moneycontrol.com/news/...\nhttps://www.cnbctv18.com/market/...")
    
    if st.button("Process URLs", type="primary"):
        if not raw_urls.strip():
            st.warning("Please paste URLs before processing.")
        else:
            urls = [u.strip() for u in raw_urls.split("\n") if u.strip()]
            with st.spinner(f"Processing {len(urls)} URLs concurrently..."):
                with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
                    processed = list(executor.map(extract_and_categorize, urls))
                
                st.session_state.processed_items = processed
                
    if "processed_items" in st.session_state and st.session_state.processed_items:
        st.write("")
        st.subheader("Review & Edit Dashboard")
        st.write("Ensure all headlines are formatted correctly and categories align with your newsletter layout.")
        
        # Table Headers with Edit Column
        h_col1, h_col_edit, h_col2, h_col3, h_col4 = st.columns([0.7, 0.7, 4.3, 2.5, 3.5])
        h_col1.markdown("<div class='table-header'>Keep</div>", unsafe_allow_html=True)
        h_col_edit.markdown("<div class='table-header'>Edit</div>", unsafe_allow_html=True)
        h_col2.markdown("<div class='table-header'>Extracted Headline</div>", unsafe_allow_html=True)
        h_col3.markdown("<div class='table-header'>Shortlink</div>", unsafe_allow_html=True)
        h_col4.markdown("<div class='table-header'>AI Assigned Category</div>", unsafe_allow_html=True)
        
        final_items = []
        
        # Interactive Table Rows
        for i, item in enumerate(st.session_state.processed_items):
            col1, col_edit, col2, col3, col4 = st.columns([0.7, 0.7, 4.3, 2.5, 3.5])
            
            keep = col1.checkbox("Keep", value=True, key=f"keep_{i}", label_visibility="collapsed")
            edit_mode = col_edit.toggle("Edit", key=f"edit_toggle_{i}", label_visibility="collapsed")
            
            current_head = st.session_state.get(f"head_{i}", item["headline"])
            current_tiny = st.session_state.get(f"tiny_{i}", item["tiny"])
            
            # --- CONDITIONAL HEADLINE LOGIC ---
            if "[ACTION REQUIRED]" in current_head or edit_mode:
                if "[ACTION REQUIRED]" in current_head:
                    col2.markdown("<span style='color: #ef4444; font-size: 13px; font-weight: 600;'>Manual Headline Needed</span>", unsafe_allow_html=True)
                    val = ""
                else:
                    val = current_head
                    
                headline = col2.text_input("Paste Headline", value=val, key=f"head_{i}", label_visibility="collapsed", placeholder="Paste correct headline here...")
            else:
                col2.markdown(f"<div class='success-text'><b>{current_head}</b></div>", unsafe_allow_html=True)
                headline = current_head
            
            col2.caption(f"Source: [{item['url'][:65]}...]({item['url']})")
            
            # --- CONDITIONAL TINYURL LOGIC ---
            if "[ACTION REQUIRED]" in current_tiny or edit_mode:
                if "[ACTION REQUIRED]" in current_tiny:
                    col3.markdown("<span style='color: #ef4444; font-size: 13px; font-weight: 600;'>Manual Link Needed</span>", unsafe_allow_html=True)
                    val = ""
                else:
                    val = current_tiny
                    
                tiny = col3.text_input("Paste Shortlink", value=val, key=f"tiny_{i}", label_visibility="collapsed", placeholder="Paste TinyURL here...")
            else:
                col3.markdown(f"<div class='success-text'><a href='{current_tiny}' target='_blank' style='color: #06b6d4;'>{current_tiny}</a></div>", unsafe_allow_html=True)
                tiny = current_tiny
                
            category = col4.selectbox("Category", options=CATEGORIES, index=CATEGORIES.index(item["cat"]), key=f"cat_{i}", label_visibility="collapsed")
            
            if keep:
                final_items.append({
                    "headline": headline,
                    "category": category,
                    "tiny_url": tiny,
                    "full_url": item["url"]
                })
                
        st.write("")
        
        # Export Container
        with st.container():
            st.markdown("### Generate Final Files")
            
            tomorrow_date = datetime.date.today() + datetime.timedelta(days=1)
            selected_file_date = st.date_input("Rundown Header Date", value=tomorrow_date)
            date_str = selected_file_date.strftime("%B %d, %Y")
            
            f1_content = f"Daily Rundown: {date_str}\n\n"
            f2_content = f"Daily Rundown: {date_str}\n\n"
            
            active_categories = [cat for cat in CATEGORIES if any(x["category"] == cat for x in final_items)]
            
            for idx, c in enumerate(active_categories):
                group = [x for x in final_items if x["category"] == c]
                if group:
                    f1_content += f"{c}\n" + "".join([f"{x['headline']}\n{x['tiny_url']}\n" for x in group])
                    f2_content += f"{c}\n" + "".join([f"{x['headline']}\n{x['tiny_url']}\n{x['full_url']}\n" for x in group])
                    
                    if idx < len(active_categories) - 1:
                        f1_content += "\n"
                        f2_content += "\n"
            
            dl_col1, dl_col2, _ = st.columns([3, 3, 4])
            dl_col1.download_button(label="Download Clean Rundown (.txt)", data=f1_content, file_name=f"Daily Rundown {date_str}.txt", mime="text/plain", type="primary")
            dl_col2.download_button(label="Download Reference File (.txt)", data=f2_content, file_name=f"Daily Rundown {date_str} - Full.txt", mime="text/plain")
