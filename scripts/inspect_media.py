"""Inspect a media file with ffprobe and print a compact JSON summary.

Usage: uv run scripts/inspect_media.py <file> [--raw]
  --raw  print the full ffprobe JSON instead of the summary
"""
import json
import shutil
import subprocess
import sys
from fractions import Fraction


def probe(path: str) -> dict:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        raise SystemExit("ffprobe not found on PATH")
    out = subprocess.run(
        [ffprobe, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", path],
        capture_output=True, text=True, encoding="utf-8",
    )
    if out.returncode != 0:
        raise SystemExit(f"ffprobe failed: {out.stderr.strip()}")
    return json.loads(out.stdout)


def _fps(s: str) -> Fraction:
    try:
        return Fraction(s)
    except (ValueError, ZeroDivisionError):
        return Fraction(0)


def summarize(path: str) -> dict:
    raw = probe(path)
    fmt = raw.get("format", {})
    info = {
        "path": path,
        "format": fmt.get("format_name"),
        "duration_s": float(fmt["duration"]) if "duration" in fmt else None,
        "size_bytes": int(fmt.get("size", 0)),
        "video": None,
        "audio": None,
    }
    for s in raw.get("streams", []):
        if s["codec_type"] == "video" and info["video"] is None:
            fps = _fps(s.get("avg_frame_rate", "0/1")) or _fps(s.get("r_frame_rate", "0/1"))
            info["video"] = {
                "codec": s["codec_name"], "width": s["width"], "height": s["height"],
                "fps": float(fps), "fps_rational": f"{fps.numerator}/{fps.denominator}",
                "pix_fmt": s.get("pix_fmt"), "index": s["index"],
            }
        elif s["codec_type"] == "audio" and info["audio"] is None:
            info["audio"] = {
                "codec": s["codec_name"], "sample_rate": int(s.get("sample_rate", 0)),
                "channels": s.get("channels"), "index": s["index"],
            }
    return info


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(args) != 1:
        raise SystemExit(__doc__)
    print(json.dumps(probe(args[0]) if "--raw" in sys.argv else summarize(args[0]), indent=2))
