#!/usr/bin/env python3
"""Freeze a verified GT scene into the golden set.

Usage (from anywhere):
    python tests/fixtures/golden_scenes/freeze_golden.py push_02 [push_06 ...]
    python tests/fixtures/golden_scenes/freeze_golden.py --force push_02

Per scene:
  1. Requires the verified GT at exports/ground_truth/verified/<scene>*.gt.json
     (i.e. the scene must be human-verified in the UI first).
  2. Copies the verified GT and its image into this directory.
  3. Records the GT's sha256 in MANIFEST.json.

Re-freezing an already-frozen scene requires --force — golden updates must be
deliberate, never accidental.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parents[2]
VERIFIED = PROJECT / "exports" / "ground_truth" / "verified"
CANDIDATES = PROJECT / "exports" / "ground_truth" / "candidates" / "push_test"
MANIFEST = HERE / "MANIFEST.json"

IMAGE_EXTS = (".jpg", ".jpeg", ".png")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def find_one(folder: Path, prefix: str, suffix: str) -> Path | None:
    hits = sorted(folder.glob(f"{prefix}*{suffix}"))
    return hits[0] if hits else None


def freeze(scene: str, force: bool) -> bool:
    manifest = json.loads(MANIFEST.read_text())
    gt_src = find_one(VERIFIED, scene, ".gt.json")
    if gt_src is None:
        print(f"✗ {scene}: no verified GT under {VERIFIED} — verify it in the UI first.")
        return False
    key = gt_src.name
    if key in manifest and not force:
        print(f"✗ {scene}: already frozen ({key}). Use --force to deliberately re-freeze.")
        return False

    image_src = None
    image_name = json.loads(gt_src.read_text()).get("image_filename", "")
    if image_name:
        for folder in (CANDIDATES, VERIFIED):
            p = folder / image_name
            if p.exists():
                image_src = p
                break
    if image_src is None:
        for ext in IMAGE_EXTS:
            image_src = find_one(CANDIDATES, scene, ext)
            if image_src:
                break
    if image_src is None:
        print(f"✗ {scene}: image not found in {CANDIDATES} — aborting this scene.")
        return False

    shutil.copy2(gt_src, HERE / gt_src.name)
    shutil.copy2(image_src, HERE / image_src.name)
    manifest[key] = {
        "gt_sha256": sha256(HERE / gt_src.name),
        "image": image_src.name,
        "frozen_from": str(gt_src.relative_to(PROJECT)),
    }
    MANIFEST.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(f"✓ {scene}: frozen ({key}, sha256={manifest[key]['gt_sha256'][:12]}…)")
    return True


def main() -> int:
    args = [a for a in sys.argv[1:] if a != "--force"]
    force = "--force" in sys.argv[1:]
    if not args:
        print(__doc__)
        return 1
    ok = all(freeze(scene, force) for scene in args)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
