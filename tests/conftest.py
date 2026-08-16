import sys
from pathlib import Path

# The app is a flat set of modules at the repo root, not an installed package.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
