"""Independent entry point: reuse the existing Python with private SDK dependencies."""
import sys
from pathlib import Path

FOLDER = Path(__file__).resolve().parent
PROJECT = FOLDER.parent
sys.path.insert(0, str(PROJECT))
sys.path.insert(0, str(FOLDER / ".packages"))

if __name__ == "__main__":
    from kb_observability.runner import main
    raise SystemExit(main())
