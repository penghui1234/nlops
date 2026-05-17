"""Pytest config: make src/ importable both as `src` package and bare top-level."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))                  # `from src.xxx import ...`
sys.path.insert(0, str(ROOT / "src"))          # `from xxx import ...`  (Lambda style)
