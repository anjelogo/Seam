import sys
from pathlib import Path

DRAPE = Path(__file__).resolve().parent.parent
GEN3D = DRAPE.parent
ROOT = GEN3D.parent
VENDOR = DRAPE / "vendor"
GC = VENDOR / "GarmentCode"
RUNS = DRAPE / "runs"


def bootstrap() -> None:
    """Make gen3d's app, seam_shared and the vendored GarmentCode importable, load root .env."""
    if sys.platform == "darwin":
        import os

        # brew's libcairo is off dyld's default search path
        os.environ.setdefault("DYLD_FALLBACK_LIBRARY_PATH", "/opt/homebrew/lib:/usr/local/lib")
    for p in (GEN3D, ROOT / "shared", GC):
        s = str(p)
        if s not in sys.path:
            sys.path.insert(0, s)
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
