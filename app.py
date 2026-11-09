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

# --- CUSTOM CSS ---
st.markdown("""
    <style>
    .block-container { padding-top: 2rem; }
    .stTextInput input, .stTextArea textarea {
        border-radius: 6px !important;
        background-color: #1e1e1e !important;
        border: 1px solid #333 !important;
    }
    div[data-testid="column"] { display: flex; flex-direction: column; justify-content: center; }
    div[data-testid="stCheckbox"] { padding-top: 4px; }
    div[data-testid="stToggle"] { padding-top: 4px; }
    .table-header {
        font-weight: 600; color: #9aa0a6; font-size: 12px;
        text-transform: uppercase; letter-spacing: 0.5px;
        border-bottom: 1px solid #333333; padding-bottom: 12px; margin-bottom: 8px;
    }
    .success-text { font-size: 14px; color: #e0e0e0; margin-bottom: 2px; transition: opacity 0.2s; }
    .dimmed-text { font-size: 14px; color: #e0e0e0; margin-bottom: 2px; opacity: 0.3; transition: opacity 0.2s; }
    input[placeholder*="Fix Error"] {
        border: 1px solid #ef4444 !important;
        box-shadow: 0 0 0 1px #ef4444 !important;
    }
    .export-panel-container {
        background-color: #1a1a1a; padding: 24px; border-radius: 8px;
        border: 1px solid #333333; margin-top: 20px;
    }
    .cat-header {
        font-size: 16px; font-weight: 700; color: #06b6d4;
        margin-top: 25px; margin-bottom: 10px; border-bottom: 1px solid #333; padding-bottom: 5px;
    }
    /* Make up/down shuffle buttons compact */
    .shuffle-btn button { padding: 0px 8px !important; border-radius: 4px !important; }
    </style>
""", unsafe_allow_html=True)

# --- SECRETS & MAPPINGS ---
API_ID = st.secrets.get("TELEGRAM_API_ID", "")
API_HASH = st.secrets.get("TELEGRAM_API_HASH", "")
CHANNEL = st.secrets.get("CHANNEL_NAME", "")
if "GEMINI_API_KEY" in st.secrets and st.secrets["GEMINI_API_KEY"] != "pending":
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])

shortener = pyshorteners.Shortener()

# Category Acronym Mappings
CAT_MAP = {
    "ECO": "ECONOMY & CURRENT AFFAIRS",
    "INT": "INTERNATIONAL",
    "IND": "INDUSTRY & COMPANY SPECIFIC",
    "QUA": "QUARTERLY RESULTS"
}
ACRONYMS = list(CAT_MAP.keys())

headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Accept-Language': 'en-US,en;q=0.9',
}

blocked_flags = ["bloomberg", "reuters.com", "are you a robot", "attention required", "403 forbidden", "access denied", "just a moment", "cloudflare", "nytimes", "subscribe to read", "log in", "security check", "verify you are human", "404 not found"]
suffixes_to_remove = [" - moneycontrol.com", " | moneycontrol.com", " - cnbctv18", " | cnbctv18", " - the economic times", " | the economic times", " - livemint", " | livemint", " - business standard"]

# --- HELPER FUNCTIONS ---
async def fetch_telegram_posts(start_time, end_time):
    session_str = st.secrets["TELEGRAM_STRING_SESSION"]
    client = TelegramClient(StringSession(session_str), API_ID, API_HASH)
    
    await client.connect()
    if not await client.is_user_authorized():
        await client.disconnect()
        raise Exception("🚨 Telegram Session Expired! Please generate a new one via iPhone a-Shell and update your secrets.")
    
    posts = []
    try:
        async for m in client.iter_messages(CHANNEL, limit=250):
            if m.date and start_time <= m.date <= end_time and m.text and len(m.text.strip()) > 10:
                posts.append({"text": m.text.replace("\n", " ").strip(), "date": m.date.astimezone(datetime.timezone(datetime.timedelta(hours=5, minutes=30)))})
    finally:
        await client.disconnect()
    return posts

def extract_and_categorize(url):
    headline = ""
    tinyurl = ""
    try:
        response = requests.get(url, headers=headers, timeout=10)
        soup = bs4.BeautifulSoup(response.content, 'html.parser')
        og_title = soup.find("meta", property="og:title")
        if og_title and og_title.get("content"): headline = og_title["content"].strip()
        elif soup.h1: headline = soup.h1.get_text(strip=True)
        elif soup.title: headline = soup.title.get_text(strip=True)

        if headline:
            headline = headline.replace('\xa0', ' ').strip()
            headline_lower = headline.lower()
            for suffix in suffixes_to_remove:
                if headline_lower.endswith(suffix):
                    headline = headline[:-len(suffix)].strip()
                    headline_lower = headline.lower()
            if " | " in headline or " - " in headline:
                delim = " | " if " | " in headline else " - "
                parts = headline.rsplit(delim, 1)
                if len(parts[1].split()) <= 3: headline = parts[0].strip()

        is_blocked = not headline or len(headline.split()) < 4 or any(f in headline.lower() for f in blocked_flags)
        if is_blocked: headline = "[ACTION REQUIRED] Manual Headline Needed"
    except Exception:
        headline = "[ACTION REQUIRED] Manual Headline Needed"

    for attempt in range(3):
        try:
            if attempt > 0: time.sleep(2 ** attempt)
            tinyurl = shortener.tinyurl.short(url)
            if tinyurl: break
        except Exception: pass
    if not tinyurl: tinyurl = "[ACTION REQUIRED] Manual Shortlink Needed"

    cat = "ECO"
    gemini_key = st.secrets.get("GEMINI_API_KEY", "")
    if gemini_key and gemini_key != "pending":
        try:
            model = genai.GenerativeModel("gemini-2.5-flash")
            prompt = f"Categorize this headline into exactly ONE of these 3-letter codes: ECO (Economy/Current Affairs), INT (International), IND (Industry/Company Specific), QUA (Quarterly Results). Headline: '{headline}'. Return ONLY the 3-letter code, nothing else."
            cat_response = model.generate_content(prompt).text.strip().upper()
            if cat_response in ACRONYMS: cat = cat_response
        except Exception: pass
            
    return {"url": url, "tiny": tinyurl, "headline": headline, "cat": cat, "keep": True}

def update_field(index, field, widget_key):
    st.session_state.processed_items[index][field] = st.session_state[widget_key]

def move_item(cat, idx, direction):
    # direction: -1 for Up, 1 for Down
    target = idx + direction
    if 0 <= target < len(st.session_state.final_groups[cat]):
        items = st.session_state.final_groups[cat]
        items[idx], items[target] = items[target], items[idx]
        st.rerun()

# --- SIDEBAR NAVIGATION ---
st.sidebar.markdown("""
    <div style="margin-bottom: 25px; padding-top: 10px;">
        <h1 style="font-size: 1.9rem; font-weight: 800; margin: 0; color: #e0e0e0; line-height: 1.2;">
            Daily Rundown<br><span style="color: #06b6d4;">Engine</span>
        </h1>
    </div>
""", unsafe_allow_html=True)

app_mode = st.sidebar.radio("Navigation", ["Step 1: Fetch Posts", "Step 2: Process Data"], label_visibility="collapsed")
st.sidebar.divider()

# --- STATE INITIALIZATION ---
if "step2_phase" not in st.session_state:
    st.session_state.step2_phase = "clean"
if "final_groups" not in st.session_state:
    st.session_state.final_groups = {cat: [] for cat in ACRONYMS}

# --- MAIN AREA: STEP 1 (FETCH) ---
if app_mode == "Step 1: Fetch Posts":
    st.header("Step 1: Fetch Telegram Posts")
    st.write("Extract recent updates from the designated source channel.")
    
    fetch_type = st.radio("Duration", ["One Day", "Multi Day"], horizontal=True, label_visibility="collapsed")
    now_ist = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=5, minutes=30)
    today_date = now_ist.date()
    
    if fetch_type == "One Day":
        c1, c2, c3 = st.columns([2,1,1])
        selected_date = c1.date_input("Date", value=today_date)
        start_t = c2.time_input("Start (IST)", value=datetime.time(12, 0))
        end_t = c3.time_input("End (IST)", value=datetime.time(22, 0))
        start_dt_ist = datetime.datetime.combine(selected_date, start_t)
        end_dt_ist = datetime.datetime.combine(selected_date, end_t)
    else:
        c1, c2, c3, c4 = st.columns(4)
        start_d = c1.date_input("Start Date", value=today_date - datetime.timedelta(days=2))
        end_d = c2.date_input("End Date", value=today_date)
        start_t = c3.time_input("Start Time", value=datetime.time(22, 0))
        end_t = c4.time_input("End Time", value=datetime.time(12, 0))
        start_dt_ist = datetime.datetime.combine(start_d, start_t)
        end_dt_ist = datetime.datetime.combine(end_d, end_t)

    ist_offset = datetime.timedelta(hours=5, minutes=30)
    start_time_utc = start_dt_ist.replace(tzinfo=datetime.timezone.utc) - ist_offset
    end_time_utc = end_dt_ist.replace(tzinfo=datetime.timezone.utc) - ist_offset

    if st.button("Fetch Telegram Data", type="primary"):
        with st.spinner("Fetching..."):
            try:
                posts_data = asyncio.run(fetch_telegram_posts(start_time_utc, end_time_utc))
                st.session_state.posts = posts_data
                st.success(f"Fetched {len(posts_data)} posts.")
            except Exception as e:
                st.error(str(e))
                
    if "posts" in st.session_state and st.session_state.posts:
        st.write("### Select Posts:")
        selected_queries = []
        for i, post_obj in enumerate(st.session_state.posts):
            lbl = f"**[{post_obj['date'].strftime('%b %d, %I:%M %p')}]** {post_obj['text']}"
            if st.checkbox(lbl, key=f"post_{i}"): selected_queries.append(post_obj['text'])
                
        if st.button("Generate Search Links", type="primary") and selected_queries:
            st.divider()
            search_urls = [f"https://www.google.com/search?q={urllib.parse.quote(q[:120])}" for q in selected_queries]
            st.code("\n".join(search_urls), language="text")

# --- MAIN AREA: STEP 2 (PROCESS) ---
elif app_mode == "Step 2: Process Data":
    st.header("Step 2: Process & Export Data")
    
    # PHASE 1: CLEAN & TAG
    if st.session_state.step2_phase == "clean":
        st.write("Paste your URLs below. The engine will extract, shorten, and assign an acronym.")
        raw_urls = st.text_area("URLs Input", height=150, label_visibility="collapsed", placeholder="Paste URLs here...")
        
        if st.button("Process URLs", type="primary") and raw_urls.strip():
            urls = [u.strip() for u in raw_urls.split("\n") if u.strip()]
            with st.spinner(f"Processing {len(urls)} URLs..."):
                with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
                    st.session_state.processed_items = list(executor.map(extract_and_categorize, urls))
                    
        if "processed_items" in st.session_state and st.session_state.processed_items:
            st.markdown("### Stage 1: Clean & Tag Dashboard")
            st.write("Uncheck junk, fix red errors, and quickly verify the 3-letter category tags.")
            
            # Header
            h1, h2, h3, h4 = st.columns([0.6, 0.6, 7.8, 3], vertical_alignment="bottom")
            h1.markdown("<div class='table-header'>Keep</div>", unsafe_allow_html=True)
            h2.markdown("<div class='table-header'>Edit</div>", unsafe_allow_html=True)
            h3.markdown("<div class='table-header'>Extracted News & Links</div>", unsafe_allow_html=True)
            h4.markdown("<div class='table-header'>Cat (Acronym)</div>", unsafe_allow_html=True)
            
            for i, item in enumerate(st.session_state.processed_items):
                c1, c2, c3, c4 = st.columns([0.6, 0.6, 7.8, 3], vertical_alignment="center")
                
                # Keep State handled via callback to persist visually immediately
                keep = c1.checkbox("Keep", value=item.get("keep", True), key=f"keep_{i}", label_visibility="collapsed", on_change=update_field, args=(i, "keep", f"keep_{i}"))
                edit_mode = c2.toggle("Edit", key=f"edit_{i}", label_visibility="collapsed")
                
                needs_head = "[ACTION REQUIRED]" in item["headline"]
                needs_tiny = "[ACTION REQUIRED]" in item["tiny"]
                
                # DIMMING EFFECT LOGIC
                text_class = "success-text" if keep else "dimmed-text"
                
                with c3:
                    if needs_head or needs_tiny or edit_mode:
                        st.caption(f"Source: [{item['url'][:80]}...]({item['url']})")
                        s1, s2 = st.columns(2, vertical_alignment="center")
                        s1.text_input("Headline", value=item["headline"] if not needs_head else "", key=f"head_{i}", placeholder="Fix Error: Paste Headline..." if needs_head else "Headline", label_visibility="collapsed", on_change=update_field, args=(i, "headline", f"head_{i}"))
                        s2.text_input("Shortlink", value=item["tiny"] if not needs_tiny else "", key=f"tiny_{i}", placeholder="Fix Error: Paste TinyURL..." if needs_tiny else "TinyURL", label_visibility="collapsed", on_change=update_field, args=(i, "tiny", f"tiny_{i}"))
                    else:
                        st.markdown(f"<div class='{text_class}'><b>{item['headline']}</b></div>", unsafe_allow_html=True)
                        if keep:
                            st.caption(f"Source: [{item['url'][:55]}...]({item['url']}) &nbsp;|&nbsp; Shortlink: [{item['tiny']}]({item['tiny']})")
                        else:
                            st.markdown(f"<div class='{text_class}' style='font-size:12px;'><i>Excluded from Rundown</i></div>", unsafe_allow_html=True)

                with c4:
                    st.radio("Cat", ACRONYMS, index=ACRONYMS.index(item["cat"]), horizontal=True, key=f"cat_{i}", label_visibility="collapsed", on_change=update_field, args=(i, "cat", f"cat_{i}"))
                
                st.divider()
                
            if st.button("Next: Rank & Review ➔", type="primary", use_container_width=True):
                # Build finalized lists, filtering out skipped items
                st.session_state.final_groups = {cat: [] for cat in ACRONYMS}
                for item in st.session_state.processed_items:
                    if item.get("keep", True):
                        st.session_state.final_groups[item["cat"]].append(item)
                st.session_state.step2_phase = "rank"
                st.rerun()

    # PHASE 2: RANK & EXPORT
    elif st.session_state.step2_phase == "rank":
        st.markdown("### Stage 2: Rank & Export")
        st.write("Use the arrows to order your headlines exactly as they should appear in the final file.")
        
        if st.button("⬅ Back to Clean & Tag"):
            st.session_state.step2_phase = "clean"
            st.rerun()
            
        st.write("")
        
        # Display Categorized Blocks
        for cat in ACRONYMS:
            group_items = st.session_state.final_groups[cat]
            if not group_items: continue
            
            st.markdown(f"<div class='cat-header'>📂 {CAT_MAP[cat]} ({len(group_items)})</div>", unsafe_allow_html=True)
            
            for i, item in enumerate(group_items):
                rc1, rc2, rc3 = st.columns([0.4, 0.4, 11], vertical_alignment="center")
                
                with rc1:
                    st.markdown("<div class='shuffle-btn'>", unsafe_allow_html=True)
                    st.button("▲", key=f"up_{cat}_{i}", disabled=(i==0), on_click=move_item, args=(cat, i, -1))
                    st.markdown("</div>", unsafe_allow_html=True)
                with rc2:
                    st.markdown("<div class='shuffle-btn'>", unsafe_allow_html=True)
                    st.button("▼", key=f"down_{cat}_{i}", disabled=(i==len(group_items)-1), on_click=move_item, args=(cat, i, 1))
                    st.markdown("</div>", unsafe_allow_html=True)
                with rc3:
                    st.markdown(f"<div class='success-text'><b>{item['headline']}</b></div>", unsafe_allow_html=True)
                st.write("")
                
        # Export Container
        st.markdown("<div class='export-panel-container'>", unsafe_allow_html=True)
        st.markdown("### Finalize & Export")
        
        ex_col1, ex_col2, ex_col3 = st.columns([2, 2.5, 2.5], vertical_alignment="bottom")
        
        tomorrow_date = datetime.date.today() + datetime.timedelta(days=1)
        selected_file_date = ex_col1.date_input("Rundown Header Date", value=tomorrow_date)
        date_str = selected_file_date.strftime("%B %d, %Y")
        
        f1_content = f"Daily Rundown: {date_str}\n\n"
        f2_content = f"Daily Rundown: {date_str}\n\n"
        
        for cat in ACRONYMS:
            group = st.session_state.final_groups[cat]
            if group:
                f1_content += f"{CAT_MAP[cat]}\n" + "".join([f"{x['headline']}\n{x['tiny']}\n" for x in group]) + "\n"
                f2_content += f"{CAT_MAP[cat]}\n" + "".join([f"{x['headline']}\n{x['tiny']}\n{x['url']}\n" for x in group]) + "\n"
                
        ex_col2.download_button("Download Clean Rundown (.txt)", data=f1_content.strip(), file_name=f"Daily Rundown {date_str}.txt", mime="text/plain", type="primary", use_container_width=True)
        ex_col3.download_button("Download Reference File (.txt)", data=f2_content.strip(), file_name=f"Daily Rundown {date_str} - Full.txt", mime="text/plain", use_container_width=True)
        st.markdown("</div>", unsafe_allow_html=True)

        # 1-Click Clipboard Area
        st.write("")
        st.markdown("##### 📋 Copy Final Rundown to Clipboard")
        st.write("Hover over the box below and click the copy icon in the top right corner to instantly copy your perfectly ordered rundown.")
        st.code(f1_content.strip(), language="text")
