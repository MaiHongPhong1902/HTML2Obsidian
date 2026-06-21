import sys
from pathlib import Path

# Ensure the repository root is importable so `import tools` works
# regardless of how pytest is invoked.
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
