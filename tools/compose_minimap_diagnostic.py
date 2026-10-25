"""Reconstruct the AP OnPaint atlas over the newest native minimap capture."""

from __future__ import annotations

import re
import sys
from pathlib import Path

from PIL import Image


PAINT_SURFACE_SIZE = 2048.0


def main() -> int:
    if len(sys.argv) != 3:
        raise SystemExit("usage: compose_minimap_diagnostic.py DIAGNOSTIC_DIR OUTPUT.png")
    diagnostic_dir = Path(sys.argv[1])
    output_path = Path(sys.argv[2])
    for state_path in sorted(
        diagnostic_dir.glob("state_*.txt"), key=lambda path: path.stat().st_mtime_ns, reverse=True
    ):
        stem = state_path.stem.removeprefix("state_")
        minimap_path = diagnostic_dir / f"minimap_{stem}.bmp"
        atlas_path = diagnostic_dir / f"atlas_{stem}.png"
        if minimap_path.exists() and atlas_path.exists():
            break
    else:
        raise RuntimeError(f"no complete minimap diagnostic set in {diagnostic_dir}")
    state = state_path.read_text(encoding="utf-8")
    match = re.search(
        r"^atlas_paint_bounds=([-+\d.eE]+),([-+\d.eE]+),([-+\d.eE]+),([-+\d.eE]+)$",
        state,
        re.MULTILINE,
    )
    if not match:
        raise RuntimeError(f"atlas_paint_bounds missing from {state_path}")
    left, top, right, bottom = map(float, match.groups())

    base = Image.open(minimap_path).convert("RGBA")
    atlas = Image.open(atlas_path).convert("RGBA")
    x_scale = base.width / PAINT_SURFACE_SIZE
    y_scale = base.height / PAINT_SURFACE_SIZE
    destination = (round(left * x_scale), round(top * y_scale))
    size = (max(1, round((right - left) * x_scale)), max(1, round((bottom - top) * y_scale)))
    atlas = atlas.resize(size, Image.Resampling.NEAREST)
    base.alpha_composite(atlas, destination)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    base.save(output_path)
    print(f"state={state_path}")
    print(f"paint_bounds={left},{top},{right},{bottom}")
    print(f"capture_size={base.width}x{base.height} atlas_size={size[0]}x{size[1]} destination={destination}")
    print(f"output={output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
