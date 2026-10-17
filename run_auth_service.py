"""
Run the Production Authentication & Gateway Service on port 8080.
Replaces the Rust BFF (cargo run) with pure Python.
"""

import uvicorn
from auth_service.config import AUTH_SERVICE_HOST, AUTH_SERVICE_PORT

if __name__ == "__main__":
    print(f"Starting Authentication & Gateway Service on http://{AUTH_SERVICE_HOST}:{AUTH_SERVICE_PORT}")
    uvicorn.run("auth_service.main:app", host=AUTH_SERVICE_HOST, port=AUTH_SERVICE_PORT, reload=True)
