from pathlib import Path
import sys


APP_DIR = Path(__file__).resolve().parent / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from beeline_issue_tracker.app import main


if __name__ == "__main__":
    raise SystemExit(main())
