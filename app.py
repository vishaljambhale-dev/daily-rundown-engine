import streamlit as st
import asyncio
import datetime
import urllib.parse
import requests
import bs4
import pyshorteners
import google.generativeai as genai
from telethon import TelegramClient

st.set_page_config(page_title="Daily Rundown Engine", layout="wide")
st.title("📰 Daily Rundown Engine")

# --- USE STREAMLIT SECRETS (NO HARDCODED KEYS) ---
API_ID = st.secrets["TELEGRAM_API_ID"]
API_HASH = st.secrets["TELEGRAM_API_HASH"]
CHANNEL = st.secrets["CHANNEL_NAME"]
genai.configure(api_key=st.secrets["GEMINI_API_KEY"])

shortener = pyshorteners.Shortener()
CATEGORIES = ["Economy & Current Affairs", "International", "Company & Industry Specific", "Quarterly Results"]

# ... [Keep your fetch_telegram_posts and extract_and_categorize functions exactly the same] ...

tab1, tab2 = st.tabs(["Phase 1: Fetch & Search", "Phase 2: Process & Export"])

# === TAB 1: CLOUD-READY TAB LAUNCHER ===
with tab1:
    st.header("Step 1: Fetch Telegram Posts")
    # ... [Keep the fetch button logic the same] ...
                
    if "posts" in st.session_state and st.session_state.posts:
        st.write("### Select relevant posts:")
        selected_queries = []
        for i, post in enumerate(st.session_state.posts):
            if st.checkbox(post[:150] + "...", key=f"post_{i}"):
                selected_queries.append(post)
                
        if st.button("Generate Search Links"):
            if not selected_queries:
                st.warning("Please check at least one post.")
            else:
                st.write("### Click to open searches in new tabs:")
                for q in selected_queries:
                    search_url = f"https://www.google.com/search?q={urllib.parse.quote(q[:120])}"
                    st.markdown(f"- [Search: {q[:60]}...]({search_url})", unsafe_allow_html=True)

# === TAB 2: CLOUD-READY DOWNLOAD BUTTONS ===
# === TAB 2: CLOUD-READY DOWNLOAD BUTTONS ===
with tab2:
    st.header("Step 2: Paste Links & Export")
    
    raw_urls = st.text_area("Paste TabCopy URLs here (one per line):", height=150)
    
    if st.button("Process URLs", type="primary"):
        if not raw_urls.strip():
            st.warning("Please paste some URLs first.")
        else:
            urls = [u.strip() for u in raw_urls.split("\n") if u.strip()]
            with st.spinner(f"Processing {len(urls)} URLs (Extracting, Shortening, Categorizing)..."):
                processed = [extract_and_categorize(u) for u in urls]
                st.session_state.processed_items = processed
                
    if "processed_items" in st.session_state and st.session_state.processed_items:
        st.write("### Review, Edit & Categorize Dashboard")
        
        final_items = []
        # Create an interactive row for each item
        for i, item in enumerate(st.session_state.processed_items):
            col1, col2, col3 = st.columns([1, 5, 3])
            keep = col1.checkbox("Keep", value=True, key=f"keep_{i}")
            headline = col2.text_input("Headline", value=item["headline"], key=f"head_{i}")
            category = col3.selectbox("Category", options=CATEGORIES, index=CATEGORIES.index(item["cat"]), key=f"cat_{i}")
            
            if keep:
                final_items.append({
                    "headline": headline,
                    "category": category,
                    "tiny_url": item["tiny"],
                    "full_url": item["url"]
                })
                
        # st.divider() is now perfectly aligned with the 'for' loop above it
        st.divider()
        st.write("### Download Final Files")
        
        if st.button("Generate Final Files", type="primary"):
            date_str = datetime.date.today().strftime("%Y-%m-%d")
            
            f1_content = f"--- DAILY RUNDOWN ({date_str}) ---\n\n"
            f2_content = f"--- REFERENCE FILE ({date_str}) ---\n\n"
            
            for c in CATEGORIES:
                group = [x for x in final_items if x["category"] == c]
                if group:
                    f1_content += f"=== {c.upper()} ===\n" + "".join([f"• {x['headline']} - {x['tiny_url']}\n" for x in group]) + "\n"
                    f2_content += f"=== {c.upper()} ===\n" + "".join([f"• {x['headline']}\n  TinyURL: {x['tiny_url']}\n  Full: {x['full_url']}\n\n" for x in group])
            
            col1, col2 = st.columns(2)
            col1.download_button(label="📥 Download Clean Rundown", data=f1_content, file_name=f"Daily_Rundown_{date_str}.txt", mime="text/plain")
            col2.download_button(label="📥 Download Reference File", data=f2_content, file_name=f"Daily_Rundown_Ref_{date_str}.txt", mime="text/plain")
