"""
run.py — Backend launcher
─────────────────────────
Always starts uvicorn bound to 0.0.0.0 so the API is reachable from:
  • localhost (this machine)
  • LAN IP (other devices on the same network, e.g. phone, tablet)

Usage:
    python run.py

Equivalent manual command:
    uvicorn app.main:app --host 0.0.0.0 --port 8002 --reload
"""

import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8002,
        reload=True,
    )
