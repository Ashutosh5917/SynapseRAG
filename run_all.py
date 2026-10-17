"""
SynapseRAG Unified 1-Command Microservice Launcher.
Orchestrates Core RAG (Port 8000), Auth Gateway (Port 8080), and Streamlit UI (Port 8501).
Handles graceful shutdown of all background processes on Ctrl+C.
"""

from __future__ import annotations
import os
import signal
import socket
import subprocess
import sys
import time
import webbrowser
from typing import List

# Ensure UTF-8 output encoding on Windows consoles
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

processes: List[subprocess.Popen] = []


def is_port_in_use(port: int) -> bool:
    """Checks if a network port is already actively listening."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def shutdown_services(signum=None, frame=None):
    """Gracefully terminates all child processes on exit."""
    print("\n[!] Shutting down SynapseRAG microservices...")
    for p in processes:
        try:
            if sys.platform == "win32":
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(p.pid)], capture_output=True)
            else:
                p.terminate()
        except Exception:
            pass
    print("[+] All services safely stopped. Goodbye!")
    sys.exit(0)


def main():
    signal.signal(signal.SIGINT, shutdown_services)
    signal.signal(signal.SIGTERM, shutdown_services)

    # Determine project root directory
    base_dir = os.path.dirname(os.path.abspath(__file__))
    if not os.path.exists(os.path.join(base_dir, "src", "main.py")) and os.path.exists(os.path.join(base_dir, "Adaptive-Rag-main", "src", "main.py")):
        base_dir = os.path.join(base_dir, "Adaptive-Rag-main")
    os.chdir(base_dir)

    print("\n" + "=" * 65)
    print("      [+] SynapseRAG Unified Launcher (Production Stack)")
    print("=" * 65)

    py_exec = sys.executable
    # Intelligent environment discovery if current python lacks modern dependencies
    try:
        import langchain_core  # type: ignore
        import langgraph       # type: ignore
    except ImportError:
        candidate_pythons = [
            r"C:\Users\Lenovo\anaconda3\envs\phidata\python.exe",
            os.path.expanduser(r"~\anaconda3\envs\phidata\python.exe"),
            os.path.expanduser(r"~\miniconda3\envs\phidata\python.exe"),
        ]
        for candidate in candidate_pythons:
            if os.path.exists(candidate):
                py_exec = candidate
                print(f"  [i] Auto-selected compatible Python environment: {py_exec}")
                break

    # 1. Start Core RAG Engine (Port 8000)
    if is_port_in_use(8000):
        print("  * [Port 8000] Core RAG Engine is ALREADY running.")
    else:
        print("  * [Port 8000] Starting Core RAG Engine (:8000)...")
        p_rag = subprocess.Popen(
            [py_exec, "-m", "uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"],
            cwd=base_dir,
        )
        processes.append(p_rag)

    # 2. Start Auth Gateway (Port 8080)
    time.sleep(1.0)
    if is_port_in_use(8080):
        print("  * [Port 8080] Auth Gateway is ALREADY running.")
    else:
        print("  * [Port 8080] Starting Python Auth Gateway (:8080)...")
        auth_script = os.path.join(base_dir, "run_auth_service.py")
        p_auth = subprocess.Popen([py_exec, auth_script], cwd=base_dir)
        processes.append(p_auth)

    # 3. Start Streamlit Frontend (Port 8501)
    time.sleep(1.5)
    home_script = os.path.join(base_dir, "streamlit_app", "home.py")
    if not os.path.exists(home_script):
        home_script = os.path.join(base_dir, "Adaptive-Rag-main", "streamlit_app", "home.py")

    print("  * [Port 8501] Starting Streamlit UI Workspace (:8501)...")
    p_ui = subprocess.Popen(
        [py_exec, "-m", "streamlit", "run", home_script, "--server.port", "8501", "--server.headless", "true"],
        cwd=base_dir,
    )
    processes.append(p_ui)

    print("=" * 65)
    print("  [+] SynapseRAG Stack is LIVE!")
    print("  [+] Web Interface:   http://localhost:8501")
    print("  [+] Core API Docs:   http://localhost:8000/docs")
    print("  [+] Gateway Health:  http://localhost:8080/health")
    print("=" * 65)
    print("  Press Ctrl+C to terminate all services.\n")

    # Automatically open browser
    time.sleep(2.0)
    try:
        webbrowser.open("http://localhost:8501")
    except Exception:
        pass

    # Keep master runner process alive
    try:
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        shutdown_services()


if __name__ == "__main__":
    main()
