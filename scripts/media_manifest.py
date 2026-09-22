"""Write media/manifest.json describing source media (videos themselves are not in Git).

Usage: uv run scripts/media_manifest.py [--check]
  (default)  scan media/raw + media/generated (+ any file referenced by projects/*.mlt) and rewrite the manifest
  --check    compare manifest with disk; exit 1 on missing/changed media
Entries are keyed by relative path (posix). sha256 is included so replaced media is detectable.
"""
import hashlib
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from inspect_media import summarize  # noqa: E402

LAB = Path(os.environ.get("VIDEO_LAB", Path.cwd()))  # project root = where you run this from
MANIFEST = LAB / "media" / "manifest.json"
EXT = {".mp4", ".mts", ".m2ts", ".mov", ".mkv", ".avi", ".webm", ".wav", ".mp3", ".m4a", ".aac", ".flac", ".png", ".jpg", ".jpeg"}


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def referenced() -> set[Path]:
    """Media files referenced from projects/*.mlt that live outside media/ (best effort)."""
    out = set()
    for mlt in (LAB / "projects").glob("*.mlt"):
        for m in re.finditer(r'name="resource">([^<]+)<', mlt.read_text(encoding="utf-8")):
            p = Path(m.group(1))
            if p.suffix.lower() in EXT and p.is_absolute():
                out.add(p)
    return out


def rel(p: Path) -> str:
    try:
        return p.resolve().relative_to(LAB).as_posix()
    except ValueError:
        return p.as_posix()  # external absolute path


def scan() -> dict:
    files = {p for d in ("raw", "generated") for p in (LAB / "media" / d).rglob("*")
             if p.is_file() and p.suffix.lower() in EXT and "preview" not in p.parts}
    files |= {p for p in referenced() if p.exists()}
    entries = {}
    for p in sorted(files):
        info = summarize(str(p))
        v = info["video"] or {}
        entries[rel(p)] = {
            "name": p.stem, "filename": p.name, "size_bytes": p.stat().st_size,
            "duration_s": info["duration_s"],
            "video": f"{v['width']}x{v['height']}@{v['fps']:.3f} {v['codec']}" if v else None,
            "sha256": sha256(p),
        }
    return entries


def check() -> int:
    old = json.loads(MANIFEST.read_text())["media"] if MANIFEST.exists() else {}
    bad = 0
    for key, e in old.items():
        p = Path(key) if Path(key).is_absolute() else LAB / key
        if not p.exists():
            print(f"MISSING  {key}")
            bad += 1
        elif p.stat().st_size != e["size_bytes"] or sha256(p) != e["sha256"]:
            print(f"CHANGED  {key}")
            bad += 1
    print("media OK" if not bad else f"{bad} problem(s)")
    return 1 if bad else 0


if __name__ == "__main__":
    if "--check" in sys.argv:
        raise SystemExit(check())
    MANIFEST.write_text(json.dumps({"media": scan()}, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(f"wrote {MANIFEST.relative_to(LAB)}")
