"""Generate dashboard.html from Joe's logs + live account. Run anytime:

    .venv\\Scripts\\python.exe scripts\\build_dashboard.py

Then open dashboard.html in any browser.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.dashboard_page import build_dashboard

if __name__ == "__main__":
    path = build_dashboard()
    print(f"Open: {path}")
