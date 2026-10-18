import argparse
import asyncio
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.pipeline.local_trellis import LocalTrellisBackend  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="One cutout to GLB via local TRELLIS.2. Run it through run_gpu.sh.")
    parser.add_argument("image", type=Path)
    parser.add_argument("--out", type=Path, help="default: <tmpdir>/<image stem>.glb")
    parser.add_argument("--resolution", type=int, choices=(512, 1024, 1536), default=1024)
    args = parser.parse_args()
    out = args.out or Path(tempfile.gettempdir()) / f"{args.image.stem}.glb"
    start = time.perf_counter()
    asyncio.run(LocalTrellisBackend().image_to_3d(args.image, out, args.resolution))
    print(f"{out}: {out.stat().st_size / 1e6:.1f} MB in {time.perf_counter() - start:.1f}s (includes model load)")


if __name__ == "__main__":
    main()
