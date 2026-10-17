"""
Chat page for the Streamlit application with real-time word-by-word streaming,
document catalog viewer, and grounded source citations.
"""

import json
import os
import streamlit as st
from streamlit_app.utils.api_client import (
    stream_chat_backend,
    document_upload_rag,
    get_model_status,
    switch_model_provider,
)

# Configure page settings
st.set_page_config(
    page_title="SynapseRAG - Intelligence Workspace",
    page_icon="🧠",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom Design Tokens & Dark-Tech Styling
custom_theme_style = """
    <style>
        .stApp {
            background-color: #0B0D13;
            color: #E2E8F0;
            font-family: 'Inter', -apple-system, sans-serif;
        }
        [data-testid="stSidebar"] {
            background-color: #10131B;
            border-right: 1px solid rgba(255, 255, 255, 0.08);
        }
        .stChatMessage {
            background-color: #161A24 !important;
            border: 1px solid rgba(255, 255, 255, 0.07) !important;
            border-radius: 12px !important;
            margin-bottom: 12px !important;
        }
        .stChatInputContainer {
            background-color: #10131B !important;
            border: 1px solid rgba(255, 255, 255, 0.12) !important;
            border-radius: 12px !important;
        }
        .stButton > button {
            background-color: #2563EB !important;
            color: #FFFFFF !important;
            border: none !important;
            border-radius: 8px !important;
            font-weight: 500 !important;
        }
        .stButton > button:hover {
            background-color: #1D4ED8 !important;
        }
    </style>
"""
st.markdown(custom_theme_style, unsafe_allow_html=True)

# Initialize logout confirmation state
if "show_logout_confirm" not in st.session_state:
    st.session_state.show_logout_confirm = False

# Header with logout button
col1, col2 = st.columns([10, 2])
with col1:
    st.markdown("""
        <div style="display: flex; align-items: center; gap: 10px;">
            <h2 style="margin: 0; font-size: 22px; font-weight: 700; color: #F8FAFC;">SynapseRAG Workspace</h2>
            <span style="font-size: 11px; font-family: monospace; background: rgba(59, 130, 246, 0.1); border: 1px solid rgba(59, 130, 246, 0.2); color: #60A5FA; padding: 2px 8px; border-radius: 9999px;">
                LANGGRAPH v0.5 &bull; HYBRID AGENTIC &bull; SSE STREAMING
            </span>
        </div>
    """, unsafe_allow_html=True)

with col2:
    if st.button("🔒 Logout", use_container_width=True):
        st.session_state.show_logout_confirm = True

# Logout confirmation dialog
if st.session_state.show_logout_confirm:
    st.warning("Are you sure you want to logout?")
    col_confirm, col_cancel = st.columns(2)
    with col_confirm:
        if st.button("✅ Yes, logout"):
            for key in list(st.session_state.keys()):
                del st.session_state[key]
            st.switch_page("Home.py")
    with col_cancel:
        if st.button("❌ Cancel"):
            st.session_state.show_logout_confirm = False

# Sidebar controls: Local AI Engine & Document Upload
with st.sidebar:
    st.markdown("### 🤖 AI Model Engine")
    model_status = get_model_status()
    is_local = model_status.get("is_local", False)
    active_prov = str(model_status.get("active_provider", "auto"))
    active_mod = str(model_status.get("active_model", "Auto"))
    discovered = model_status.get("discovered_local_providers", [])

    if is_local:
        st.success(f"🟢 **Local AI Active**\n\n• Provider: `{active_prov.upper()}`\n\n• Model: `{active_mod}`\n\n*(100% offline & private)*")
    elif active_prov in ["openai", "cloud"]:
        st.info(f"🌐 **Cloud AI Active**\n\n• Provider: `OpenAI`\n\n• Model: `{active_mod}`")
    else:
        st.warning("⚠️ **No Active LLM Found**\n\nStart local Ollama or set `OPENAI_API_KEY`.")

    with st.expander("⚙️ Engine & Local Discovery", expanded=False):
        if discovered:
            st.markdown(f"**Found {len(discovered)} Local Server(s):**")
            for prov in discovered:
                st.caption(f"• **{prov.get('name')}** (`{prov.get('host')}`) - {len(prov.get('models', []))} models found")
        else:
            st.caption("No running local server found at `localhost:11434` (Ollama) or `localhost:1234` (LM Studio).")
            st.markdown("""
            > **Free Local AI Setup:**
            > 1. Install [Ollama](https://ollama.com/)
            > 2. Run: `ollama run llama3.2`
            > 3. Click **Scan Local Models** below
            """)

        col_scan, _ = st.columns([1, 1])
        with col_scan:
            if st.button("🔄 Scan Local", use_container_width=True):
                st.rerun()

        provider_options = ["auto"]
        if any(p.get("provider") == "ollama" for p in discovered):
            provider_options.append("ollama")
        if any(p.get("provider") == "lm_studio" for p in discovered):
            provider_options.append("lm_studio")
        provider_options.append("openai")

        selected_prov = st.selectbox(
            "Select AI Provider",
            options=provider_options,
            index=0 if active_prov not in provider_options else provider_options.index(active_prov),
            format_func=lambda x: {
                "auto": "⚡ Auto-Detect (Prefers Local)",
                "ollama": "🦙 Ollama (Local)",
                "lm_studio": "🧪 LM Studio (Local)",
                "openai": "🌐 OpenAI Cloud (GPT-4o)",
            }.get(x, x),
        )

        if st.button("Apply Engine", use_container_width=True):
            switch_model_provider(selected_prov)
            st.success(f"Switched engine to {selected_prov}")
            st.rerun()

    st.markdown("---")
    st.markdown("### 📂 Ingest Documents")
    st.caption("Upload company policies, technical guides, or notes.")

    uploaded_file = st.file_uploader("Upload PDF or TXT", type=["pdf", "txt"])

    if uploaded_file:
        file_description = st.text_input(
            "📄 Document Description (Required)",
            max_chars=300,
            placeholder="E.g. Employee Handbook covering 2026 PTO policy",
        )

        if "uploaded_files" not in st.session_state:
            st.session_state.uploaded_files = {}

        file_key = f"{uploaded_file.name}_{file_description}"

        if file_description:
            if file_key not in st.session_state.uploaded_files:
                with st.spinner("Processing & indexing into vector store..."):
                    success = document_upload_rag(uploaded_file, file_description)
                if success:
                    st.success(f"✓ Indexed: {uploaded_file.name}")
                    st.session_state.uploaded_files[file_key] = True
                else:
                    st.error(f"Upload failed: {uploaded_file.name}")
            else:
                st.info(f"Already indexed: {uploaded_file.name}")
        else:
            st.warning("Please provide a brief description.")

    # Show Persistent Library Catalog
    catalog_file = "documents_catalog.json"
    if os.path.exists(catalog_file):
        try:
            with open(catalog_file, "r", encoding="utf-8") as f:
                catalog = json.load(f)
            if catalog:
                st.markdown(f"#### 📚 Indexed Library ({len(catalog)})")
                for doc_name, doc_info in catalog.items():
                    with st.expander(f"📄 {doc_name} ({doc_info.get('chunks', 0)} chunks)"):
                        st.caption(f"**Description:** {doc_info.get('description', '')}")
                        if "uploaded_at" in doc_info:
                            st.caption(f"**Uploaded:** {doc_info['uploaded_at'][:19]}")
        except Exception:
            pass

    st.markdown("---")
    st.markdown("### ⚡ Test Scenarios")
    st.caption("Try these prompt types to test agent routing:")
    st.markdown("""
    - **Document Query:** *"What is the annual leave rollover policy?"*
    - **Self-Correction:** *"How do I take sick days without trouble?"*
    - **General Intelligence:** *"Explain quicksort in Python"*
    - **Live Web Search:** *"What is the latest NASA Artemis news?"*
    """)

# Check authentication
if "session_id" not in st.session_state or "jwt_token" not in st.session_state:
    st.warning("Please authenticate via the Home page first.")
    st.stop()

# Initialize chat history
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []

# 1. Render all past conversation turns
for role, text in st.session_state.chat_history:
    with st.chat_message(role):
        st.markdown(text)

# 2. Accept new user query
user_input = st.chat_input("Ask a question about your documents, code, or real-time topics...")

if user_input:
    # Append and render user message immediately
    st.session_state.chat_history.append(("user", user_input))
    with st.chat_message("user"):
        st.markdown(user_input)

    # Render assistant response with live word-by-word streaming
    with st.chat_message("assistant"):
        status_placeholder = st.empty()

        def on_status_update(status_text: str):
            status_placeholder.info(f"🤖 *{status_text}*")

        # Smooth real-time token stream
        token_stream = stream_chat_backend(
            user_input,
            st.session_state["jwt_token"],
            on_status=on_status_update,
        )
        full_response = st.write_stream(token_stream)
        status_placeholder.empty()

    # Save complete assistant response to history
    st.session_state.chat_history.append(("assistant", full_response))
