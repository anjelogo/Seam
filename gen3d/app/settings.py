import os
from pathlib import Path

from dotenv import load_dotenv

GEN3D_DIR = Path(__file__).resolve().parents[1]
load_dotenv(GEN3D_DIR.parent / ".env")


def _dir(name: str, default: str) -> Path:
    return (GEN3D_DIR / (os.getenv(name) or default)).resolve()


DATA_DIR = _dir("DATA_DIR", "../data")
ASSETS_DIR = _dir("ASSETS_DIR", "../assets")
GEN3D_BACKEND = os.getenv("GEN3D_BACKEND") or "mock"
FAL_KEY = os.getenv("FAL_KEY") or None
