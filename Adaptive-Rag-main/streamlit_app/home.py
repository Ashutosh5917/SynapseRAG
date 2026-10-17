"""
Home page for Streamlit authentication interface with modern Linear-style design.
"""

import logging
import streamlit as st
from utils.api_client import create_user, login_user, get_api_token

# Configure page settings FIRST
st.set_page_config(
    page_title="SynapseRAG - Authentication",
    page_icon="🧠",
    layout="centered",
    initial_sidebar_state="collapsed",
)

# Custom Design Tokens & Dark-Tech Styling
custom_theme_style = """
    <style>
        [data-testid="stSidebarNav"] { display: none; }
        .stApp {
            background-color: #0B0D13;
            color: #E2E8F0;
            font-family: 'Inter', -apple-system, sans-serif;
        }
        .stTextInput > div > div > input {
            background-color: #10131B !important;
            border: 1px solid rgba(255, 255, 255, 0.1) !important;
            color: #F8FAFC !important;
            border-radius: 8px !important;
        }
        .stTextInput > div > div > input:focus {
            border-color: #3B82F6 !important;
            box-shadow: 0 0 0 1px #3B82F6 !important;
        }
        .stButton > button {
            background-color: #2563EB !important;
            color: #FFFFFF !important;
            border: none !important;
            border-radius: 8px !important;
            font-weight: 500 !important;
            transition: all 0.15s ease !important;
        }
        .stButton > button:hover {
            background-color: #1D4ED8 !important;
            transform: translateY(-1px);
        }
        .stButton > button:active {
            transform: scale(0.98);
        }
    </style>
"""
st.markdown(custom_theme_style, unsafe_allow_html=True)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    filename="app.log",
    filemode="a",
)
logger = logging.getLogger(__name__)

st.markdown("""
<div style="text-align: center; margin-bottom: 24px;">
    <div style="display: inline-block; padding: 6px 12px; background: rgba(59, 130, 246, 0.1); border: 1px solid rgba(59, 130, 246, 0.2); border-radius: 9999px; font-size: 11px; font-family: monospace; color: #60A5FA; margin-bottom: 12px;">
        SYNAPSERAG GATEWAY &bull; ARGON2ID &bull; JWT
    </div>
    <h1 style="font-size: 26px; font-weight: 700; color: #F8FAFC; margin: 0 0 6px 0;">Welcome to SynapseRAG</h1>
    <p style="font-size: 13px; color: #94A3B8; margin: 0;">Autonomous Self-Correcting Multi-Route Agentic Knowledge Engine</p>
</div>
""", unsafe_allow_html=True)

# Auto-bootloader for single-click / cloud deployment
def ensure_backend_services():
    """Auto-spawns background microservices if not running (e.g. on Streamlit Cloud)."""
    import socket
    import subprocess
    import sys
    import time

    def is_port_open(port: int) -> bool:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(0.6)
                return s.connect_ex(("127.0.0.1", port)) == 0
        except Exception:
            return False

    started = False
    if not is_port_open(8000):
        try:
            subprocess.Popen([sys.executable, "-m", "uvicorn", "src.main:app", "--port", "8000", "--host", "0.0.0.0"])
            started = True
        except Exception:
            pass

    if not is_port_open(8080):
        try:
            subprocess.Popen([sys.executable, "run_auth_service.py"])
            started = True
        except Exception:
            pass

    if started:
        time.sleep(2.0)

# Step 1: Fetch API token with auto-bootloader retry
if "session_id" not in st.session_state:
    token = get_api_token()
    if not token:
        ensure_backend_services()
        token = get_api_token()

    if token:
        st.session_state["session_id"] = token
    else:
        st.error("Failed to connect to Gateway (:8080). Ensure `python run_all.py` or `python run_auth_service.py` is running.")
        st.stop()

# 1-Click Instant Guest Demo Button
col_demo, _ = st.columns([1, 0.01])
with col_demo:
    if st.button("⚡ Instant Guest Demo (1-Click Access)", use_container_width=True):
        demo_user = "demo_guest"
        create_user(demo_user, "DemoPass123!", st.session_state["session_id"])
        resp = login_user(demo_user, "DemoPass123!", st.session_state["session_id"])
        if resp and resp.get("jwt"):
            st.session_state["jwt_token"] = resp["jwt"]
            st.session_state["username"] = "Guest Demo"
            st.switch_page("pages/chat.py")

st.markdown("<div style='text-align: center; margin: 12px 0; font-size: 11px; color: #64748B;'>— OR AUTHENTICATE WITH ACCOUNT —</div>", unsafe_allow_html=True)

# Step 2: Render standard login/signup form
with st.form("auth_form"):
    username = st.text_input("Username", placeholder="e.g. alice")
    password = st.text_input("Password", type="password", placeholder="••••••••")
    mode = st.radio("Choose action:", ["Login", "Create Account"], horizontal=True)
    submit = st.form_submit_button("Proceed", use_container_width=True)

# Step 3: Handle login/account creation
if submit:
    if not username or not password:
        st.error("Username and password required.")
    else:
        if mode == "Create Account":
            success = create_user(username, password, st.session_state["session_id"])
            if success:
                st.success("User created successfully. You can now log in.")
            else:
                st.error("User creation failed. Username may already exist.")
        else:
            response = login_user(username, password, st.session_state["session_id"])
            if response and response.get("jwt"):
                st.session_state["jwt_token"] = response["jwt"]
                st.session_state["username"] = username
                st.switch_page("pages/chat.py")
            else:
                st.error("Login failed: Invalid credentials or gateway unreachable.")

# Debug logs section
with st.expander("📜 Gateway Logs & Session Status"):
    st.caption(f"Session API Token: {st.session_state.get('session_id', 'None')}")
    try:
        with open("app.log", "r") as log_file:
            st.text(log_file.read()[-1000:])
    except FileNotFoundError:
        st.info("Log file not created yet.")
