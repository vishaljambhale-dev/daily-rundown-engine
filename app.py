import streamlit as st
import asyncio
import datetime
import urllib.parse
import requests
import bs4
import pyshorteners
import google.generativeai as genai
from telethon import TelegramClient

# --- PAGE CONFIGURATION ---
st.set_page_config(page_title="Daily Rundown Engine", layout="wide")

# --- CUSTOM CSS FOR MODERN UI ---
st.markdown("""
    <style>
    /* Clean up top padding */
    .block-container { padding-top: 2rem; }
    
    /* Round the corners of input fields and buttons */
    .stTextInput input, .stSelectbox div[data-baseweb="select"], .stTextArea textarea {
        border-radius: 8px !important;
    }
    .stButton button {
        border-radius: 8px !important;
        font-weight: 600 !important;
    }
    
    /* Style the review table headers */
    div[data-testid="column"] { 
        border-bottom: 1px solid #333333; 
        padding-bottom: 5px; 
        margin-bottom: 10px;
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
genai.configure(api_key=st.secrets["GEMINI_API_KEY"])

shortener = pyshorteners.Shortener()
CATEGORIES = ["Economy & Current Affairs", "International", "Company & Industry Specific", "Quarterly Results"]

# --- HELPER FUNCTIONS ---
async def fetch_telegram_posts():
    client = TelegramClient("cloud_session", API_ID, API_HASH)
    await client.start()
    
    today = datetime.datetime.now(datetime.timezone.utc).date()
    start_time = datetime.datetime.combine(today, datetime.time(6, 30), tzinfo=datetime.timezone.utc)
    end_time = datetime.datetime.combine(today, datetime.time(16, 30), tzinfo=datetime.timezone.utc)
    
    posts = []
    async for m in client.iter_messages(CHANNEL, limit=100):
        if m.date and start_time <= m.date <= end_time and m.text and len(m.text.strip()) > 10:
            posts.append(m.text.replace("\n", " ").strip())
    
    await client.disconnect()
    return posts

def extract_and_categorize(url):
    try:
        resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=5)
        soup = bs4.BeautifulSoup(resp.text, "html.parser")
        og = soup.find("meta", property="og:title")
        if og and og.get("content"):
            headline = og["content"].strip()
        elif soup.title:
            headline = soup.title.string.strip()
        else:
            headline = "Manual Headline Needed"
    except Exception:
        headline = "Manual Headline Needed"
    
    try:
        tiny = shortener.tinyurl.short(url)
    except Exception:
        tiny = url
        
    try:
        model = genai.GenerativeModel("gemini-2.5-flash")
        prompt = f"Categorize into ONE of: Economy & Current Affairs, International, Company & Industry Specific, Quarterly Results. Headline: '{headline}'. Return ONLY category name."
        cat = model.generate_content(prompt).text.strip()
        if cat not in CATEGORIES:
            cat = CATEGORIES[0]
    except Exception:
        cat = CATEGORIES[0]
        
    return {"url": url, "tiny": tiny, "headline": headline, "cat": cat}

# --- SIDEBAR NAVIGATION ---
st.sidebar.title("Daily Rundown")
st.sidebar.write("") # Spacer

# Navigation Radio Buttons
app_mode = st.sidebar.radio(
    "Navigation",
    ["Step 1: Fetch Posts", "Step 2: Process Data"],
    label_visibility="collapsed"
)

st.sidebar.divider()
st.sidebar.subheader("Actions")

# Dynamically change sidebar actions based on the active view
fetch_clicked = False
if app_mode == "Step 1: Fetch Posts":
    st.sidebar.write("Click below to fetch today's data.")
    fetch_clicked = st.sidebar.button("Fetch Telegram Data", type="primary", use_container_width=True)
elif app_mode == "Step 2: Process Data":
    st.sidebar.write("Paste your links in the main window to begin data processing.")
    # Fetch button is removed here to keep the UI clean

# --- MAIN AREA: STEP 1 ---
if app_mode == "Step 1: Fetch Posts":
    st.header("Step 1: Fetch Telegram Posts")
    st.write("Extract recent updates from the designated source channel.")
    
    if fetch_clicked:
        with st.spinner("Connecting to Telegram..."):
            try:
                posts = asyncio.run(fetch_telegram_posts())
                st.session_state.posts = posts
                st.success(f"Successfully fetched {len(posts)} posts.")
            except Exception as e:
                st.error(f"Error fetching posts: {e}")
                
    if "posts" in st.session_state and st.session_state.posts:
        st.write("Select relevant posts to generate search queries:")
        
        selected_queries = []
        for i, post in enumerate(st.session_state.posts):
            if st.checkbox(post[:150] + "...", key=f"post_{i}"):
                selected_queries.append(post)
                
        if st.button("Generate Search Links", type="primary"):
            if not selected_queries:
                st.warning("Please check at least one post.")
            else:
                st.write("Click to open searches in new tabs:")
                for q in selected_queries:
                    search_url = f"https://www.google.com/search?q={urllib.parse.quote(q[:120])}"
                    st.markdown(f"- [Search: {q[:60]}...]({search_url})", unsafe_allow_html=True)

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
            with st.spinner(f"Processing {len(urls)} URLs..."):
                processed = [extract_and_categorize(u) for u in urls]
                st.session_state.processed_items = processed
                
    if "processed_items" in st.session_state and st.session_state.processed_items:
        st.write("")
        st.subheader("Review & Edit Dashboard")
        st.write("Ensure all headlines are formatted correctly and categories align with your newsletter layout.")
        
        # Table Headers aligned using columns
        h_col1, h_col2, h_col3 = st.columns([1, 6, 4])
        h_col1.write("**Keep**")
        h_col2.write("**Extracted Headline**")
        h_col3.write("**AI Assigned Category**")
        
        final_items = []
        
        # Interactive Table Rows
        for i, item in enumerate(st.session_state.processed_items):
            col1, col2, col3 = st.columns([1, 6, 4])
            keep = col1.checkbox("Keep", value=True, key=f"keep_{i}", label_visibility="collapsed")
            headline = col2.text_input("Headline", value=item["headline"], key=f"head_{i}", label_visibility="collapsed")
            category = col3.selectbox("Category", options=CATEGORIES, index=CATEGORIES.index(item["cat"]), key=f"cat_{i}", label_visibility="collapsed")
            
            if keep:
                final_items.append({
                    "headline": headline,
                    "category": category,
                    "tiny_url": item["tiny"],
                    "full_url": item["url"]
                })
                
        # Export Container
        st.write("")
        with st.container():
            st.markdown("### Generate Final Files")
            date_str = datetime.date.today().strftime("%Y-%m-%d")
            
            f1_content = f"--- DAILY RUNDOWN ({date_str}) ---\n\n"
            f2_content = f"--- REFERENCE FILE ({date_str}) ---\n\n"
            
            for c in CATEGORIES:
                group = [x for x in final_items if x["category"] == c]
                if group:
                    f1_content += f"=== {c.upper()} ===\n" + "".join([f"• {x['headline']} - {x['tiny_url']}\n" for x in group]) + "\n"
                    f2_content += f"=== {c.upper()} ===\n" + "".join([f"• {x['headline']}\n  TinyURL: {x['tiny_url']}\n  Full: {x['full_url']}\n\n" for x in group])
            
            dl_col1, dl_col2, _ = st.columns([3, 3, 4])
            dl_col1.download_button(label="Download Clean Rundown (.txt)", data=f1_content, file_name=f"Daily_Rundown_{date_str}.txt", mime="text/plain", type="primary")
            dl_col2.download_button(label="Download Reference File (.txt)", data=f2_content, file_name=f"Daily_Rundown_Ref_{date_str}.txt", mime="text/plain")
