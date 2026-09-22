"""Render single preview frames of a Shotcut project with melt (read-only on the project).

Usage: uv run scripts/render_frame.py <proj.mlt> <timeline_seconds> [<seconds> ...] [--out DIR]
Writes DIR/frame_<sec>.png (default DIR = media/generated/preview). melt does not exit by itself,
so each render is polled and killed once the PNG is complete.
"""
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import mlt_tools as M  # noqa: E402


def render(proj: Path, sec: float, out: Path) -> Path:
    root = M.validate_text(proj.read_text(encoding="utf-8-sig"))
    fps = M.profile_fps(root)
    f = round(sec * float(fps))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.unlink(missing_ok=True)
    log = out.with_suffix(".log")
    with open(log, "w") as lf:
        p = subprocess.Popen([str(M.MELT), str(proj), f"in={f}", f"out={f}", "-consumer", f"avformat:{out}",
                              "vcodec=png", "frames=1"], stdout=subprocess.DEVNULL, stderr=lf, stdin=subprocess.DEVNULL)
        deadline, last = time.time() + 90, -1
        while time.time() < deadline:
            time.sleep(1)
            size = out.stat().st_size if out.exists() else -1
            if size > 0 and size == last:
                break
            last = size
        if p.poll() is None:
            p.kill()
            p.wait()
    log.unlink(missing_ok=True)
    if not out.exists() or out.stat().st_size == 0:
        raise SystemExit(f"no frame rendered for {sec}s")
    return out


if __name__ == "__main__":
    a = sys.argv[1:]
    outdir = Path("media/generated/preview")
    if "--out" in a:
        i = a.index("--out")
        outdir = Path(a[i + 1])
        del a[i:i + 2]
    if len(a) < 2:
        raise SystemExit(__doc__)
    for s in a[1:]:
        print(render(Path(a[0]), float(s), outdir / f"frame_{float(s):g}.png"))
