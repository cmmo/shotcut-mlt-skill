"""Small, safe helpers for Shotcut .mlt projects (stdlib only).

Commands:
  validate <proj.mlt>                   well-formed XML + structural checks (+ melt load test if --melt)
  summary  <proj.mlt>                   what is on the timeline (READ THIS before any edit)
  status   <proj.mlt>                   has a human changed the file since the agent last wrote it?
  backup   <proj.mlt>                   timestamped copy into projects/backups/
  create   <proj.mlt> <clip> [<clip>..] NEW project (refuses to overwrite an existing file)
  append-clip <proj.mlt> <clip>         add a clip to the END of the first video track (minimal edit)

Rules baked in: every modification backs up first, edits are surgical (only the
elements we add/change), output is validated before it replaces the original,
and the write is atomic. Human edits are never regenerated away.
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from datetime import datetime
from fractions import Fraction
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from inspect_media import summarize  # noqa: E402

SHOTCUT_VERSION = "26.8.1"  # version whose XML conventions these scripts follow; see references/mlt-xml.md


def _find_melt() -> Path:
    """melt.exe ships inside Shotcut. Honour MELT_PATH, then PATH, then the usual install spots."""
    env = os.environ.get("MELT_PATH")
    if env:
        return Path(env)
    found = shutil.which("melt")
    if found:
        return Path(found)
    for c in (Path.home() / "AppData/Local/Programs/Shotcut/melt.exe",
              Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Shotcut/melt.exe",
              Path("/usr/bin/melt"), Path("/usr/local/bin/melt")):
        if c.exists():
            return c
    return Path("melt")  # last resort: let the OS resolve it and report a clear error


MELT = _find_melt()


# ---------- time helpers ----------
def tc(frames: int, fps: Fraction) -> str:
    ms = round(frames * 1000 / fps)
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"


def frames_of(t: str, fps: Fraction) -> int:
    if re.fullmatch(r"\d+", t):
        return int(t)
    h, m, s = t.split(":")
    return round((int(h) * 3600 + int(m) * 60 + float(s)) * float(fps))


def profile_fps(root) -> Fraction:
    p = root.find("profile")
    return Fraction(int(p.get("frame_rate_num")), int(p.get("frame_rate_den")))


# ---------- file safety ----------
def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def state_file(proj: Path) -> Path:
    return proj.parent / ".state" / (proj.name + ".json")


def record_agent_write(proj: Path) -> None:
    sf = state_file(proj)
    sf.parent.mkdir(exist_ok=True)
    sf.write_text(json.dumps({"sha256": sha(proj), "at": datetime.now().isoformat()}))


def human_modified(proj: Path) -> bool | None:
    """True if file differs from what the agent last wrote; None if unknown."""
    sf = state_file(proj)
    if not sf.exists():
        return None
    return json.loads(sf.read_text())["sha256"] != sha(proj)


def backup(proj: Path) -> Path:
    d = proj.parent / "backups"
    d.mkdir(exist_ok=True)
    dest = d / f"{proj.stem}.{datetime.now():%Y%m%d-%H%M%S-%f}.mlt"
    shutil.copy2(proj, dest)
    return dest


def validate_text(text: str) -> ET.Element:
    root = ET.fromstring(text)  # raises ParseError if not well-formed
    if root.tag != "mlt":
        raise ValueError("root element is not <mlt>")
    if root.find("profile") is None:
        raise ValueError("missing <profile>")
    ids = [e.get("id") for e in root.iter() if e.get("id")]
    dupes = {i for i in ids if ids.count(i) > 1}
    if dupes:
        raise ValueError(f"duplicate ids: {dupes}")
    known = set(ids)
    for e in root.iter():
        if e.tag in ("entry", "track") and e.get("producer") not in known:
            raise ValueError(f"<{e.tag}> references unknown producer {e.get('producer')!r}")
    return root


def melt_check(proj: Path) -> None:
    if not MELT.exists() and shutil.which(str(MELT)) is None:
        print("  (melt not found — set MELT_PATH or add Shotcut to PATH; skipped load test)")
        return
    # melt does not exit on its own when run non-interactively, so poll its
    # progress output for the last frame, then kill it.
    import tempfile
    import time
    with tempfile.TemporaryDirectory() as td:
        errf = Path(td) / "err.txt"
        with open(errf, "w") as ef:
            p = subprocess.Popen([str(MELT), str(proj), "-consumer", f"avformat:{td}/t.mp4",
                                  "vcodec=libx264", "acodec=aac", "out=9"],
                                 stdout=subprocess.DEVNULL, stderr=ef, stdin=subprocess.DEVNULL)
            ok, deadline = False, time.time() + 60
            while time.time() < deadline and p.poll() is None:
                if re.search(r"Current Position:\s+9\b", errf.read_text(errors="ignore")):
                    ok = True
                    break
                time.sleep(0.5)
            ok = ok or (p.poll() == 0)
            if p.poll() is None:
                p.kill()
                p.wait()
        if not ok:
            raise SystemExit(f"melt failed to render project:\n{errf.read_text(errors='ignore')[-800:]}")
    print("  melt load+render test: OK")


def write_project(proj: Path, root: ET.Element) -> None:
    """Serialize -> validate -> atomic replace -> record hash."""
    ET.indent(root, space="  ")
    body = ET.tostring(root, encoding="unicode")
    # match Shotcut's serialization so Git diffs show only real edits, not `/>` vs ` />` churn
    body = body.replace(" />", "/>")
    body = re.sub(r'<property name="([^"]*)"/>', r'<property name="\1"></property>', body)
    text = '<?xml version="1.0" standalone="no"?>\n' + body + "\n"
    validate_text(text)
    tmp = proj.with_suffix(".mlt.tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    tmp.replace(proj)
    record_agent_write(proj)


# ---------- MLT building blocks ----------
def prop(parent, name, value):
    ET.SubElement(parent, "property", name=name).text = str(value)


def make_chain(cid: str, clip: Path, info: dict, fps: Fraction) -> ET.Element:
    n = round(info["duration_s"] * float(fps))
    c = ET.Element("chain", id=cid, out=tc(n - 1, fps))
    prop(c, "length", n)
    prop(c, "eof", "pause")
    prop(c, "resource", clip.resolve().as_posix())
    prop(c, "mlt_service", "avformat-novalidate")
    prop(c, "seekable", 1)
    prop(c, "audio_index", info["audio"]["index"] if info["audio"] else -1)
    prop(c, "video_index", info["video"]["index"] if info["video"] else -1)
    prop(c, "mute_on_pause", 0)
    prop(c, "shotcut:caption", clip.name)
    return c


def next_id(root, prefix: str) -> str:
    used = {e.get("id") for e in root.iter() if e.get("id")}
    i = 0
    while f"{prefix}{i}" in used:
        i += 1
    return f"{prefix}{i}"


def timeline_end(root) -> int:
    fps = profile_fps(root)
    best = 0
    for pl in root.findall("playlist"):
        if pl.find("./property[@name='shotcut:video']") is None and pl.find("./property[@name='shotcut:audio']") is None:
            continue
        total = 0
        for e in pl:
            if e.tag == "entry":
                total += frames_of(e.get("out"), fps) - frames_of(e.get("in"), fps) + 1
            elif e.tag == "blank":
                total += frames_of(e.get("length"), fps)
        best = max(best, total)
    return best


def video_playlist(root) -> ET.Element:
    for pl in root.findall("playlist"):
        if pl.find("./property[@name='shotcut:video']") is not None:
            return pl
    raise SystemExit("no Shotcut video track found in project")


# ---------- commands ----------
def cmd_create(proj: Path, clips: list[Path]) -> None:
    if proj.exists():
        raise SystemExit(f"REFUSING: {proj} already exists. Use append-clip / targeted edits (backups are automatic).")
    infos = [summarize(str(c)) for c in clips]
    v = infos[0]["video"]
    fps = Fraction(v["fps_rational"])
    w, h = v["width"], v["height"]
    from math import gcd
    g = gcd(w, h)
    root = ET.Element("mlt", {"LC_NUMERIC": "C", "version": "7.41.0",
                              "title": f"Shotcut version {SHOTCUT_VERSION}", "producer": "main_bin"})
    ET.SubElement(root, "profile", description=f"{w}x{h} {float(fps):.2f} fps", width=str(w), height=str(h),
                  progressive="1", sample_aspect_num="1", sample_aspect_den="1",
                  display_aspect_num=str(w // g), display_aspect_den=str(h // g),
                  frame_rate_num=str(fps.numerator), frame_rate_den=str(fps.denominator), colorspace="709")
    mb = ET.SubElement(root, "playlist", id="main_bin")
    prop(mb, "xml_retain", 1)

    total = sum(round(i["duration_s"] * float(fps)) for i in infos)
    end = tc(total - 1, fps)
    black = ET.SubElement(root, "producer", id="black", **{"in": "00:00:00.000"}, out=end)
    for k, val in [("length", 2147483647), ("eof", "continue"), ("resource", 0), ("aspect_ratio", 1),
                   ("mlt_service", "color"), ("mlt_image_format", "yuv422"), ("set.test_audio", 0)]:
        prop(black, k, val)
    bg = ET.SubElement(root, "playlist", id="background")
    ET.SubElement(bg, "entry", producer="black", **{"in": "00:00:00.000"}, out=end)

    chains, entries = [], []
    for i, (clip, info) in enumerate(zip(clips, infos)):
        c = make_chain(f"chain{i}", clip, info, fps)
        chains.append(c)
        entries.append((f"chain{i}", c.get("out")))
    root.extend(chains)
    pl = ET.SubElement(root, "playlist", id="playlist0")
    prop(pl, "shotcut:video", 1)
    prop(pl, "shotcut:name", "V1")
    for cid, out in entries:
        ET.SubElement(pl, "entry", producer=cid, **{"in": "00:00:00.000"}, out=out)

    tr = ET.SubElement(root, "tractor", id="tractor0", title=f"Shotcut version {SHOTCUT_VERSION}",
                       **{"in": "00:00:00.000"}, out=end)
    prop(tr, "shotcut", 1)
    prop(tr, "shotcut:projectAudioChannels", 2)
    prop(tr, "shotcut:projectFolder", 0)
    ET.SubElement(tr, "track", producer="background")
    ET.SubElement(tr, "track", producer="playlist0")
    t0 = ET.SubElement(tr, "transition", id="transition0")
    for k, val in [("a_track", 0), ("b_track", 1), ("mlt_service", "mix"), ("always_active", 1), ("sum", 1)]:
        prop(t0, k, val)
    t1 = ET.SubElement(tr, "transition", id="transition1")
    for k, val in [("a_track", 0), ("b_track", 1), ("version", "0.1"), ("mlt_service", "frei0r.cairoblend"),
                   ("threads", 0), ("disable", 1)]:  # bottom video track: Shotcut disables its blend (else overlays black out V1)
        prop(t1, k, val)
    write_project(proj, root)
    print(f"created {proj}")


def cmd_append(proj: Path, clip: Path) -> None:
    if not proj.exists():
        raise SystemExit(f"{proj} does not exist; use create")
    hm = human_modified(proj)
    print({True: "note: project was modified by a human since last agent write (preserved)",
           False: "note: project unchanged since last agent write",
           None: "note: no agent-write record; treating file as human-owned"}[hm])
    root = validate_text(proj.read_text(encoding="utf-8"))  # never edit a broken file
    b = backup(proj)
    print(f"backup: {b}")
    fps = profile_fps(root)
    info = summarize(str(clip))
    chain = make_chain(next_id(root, "chain"), clip, info, fps)
    # insert new chain just before the first playlist/tractor that follows existing chains
    idx = max((i for i, e in enumerate(root) if e.tag in ("chain", "producer")), default=0) + 1
    root.insert(idx, chain)
    pl = video_playlist(root)
    ET.SubElement(pl, "entry", producer=chain.get("id"), **{"in": "00:00:00.000"}, out=chain.get("out"))
    tractors = root.findall("tractor")
    tr = next((t for t in tractors if t.find("./property[@name='shotcut']") is not None), tractors[-1])
    end = tc(timeline_end(root) - 1, fps)
    tr.set("out", end)
    bg = root.find("producer[@id='black']")
    if bg is not None:
        bg.set("out", end)
    for e in root.findall("playlist[@id='background']/entry"):
        e.set("out", end)
    write_project(proj, root)
    print(f"appended {clip.name} -> {chain.get('id')}; timeline out={end}")


def cmd_summary(proj: Path) -> None:
    root = validate_text(proj.read_text(encoding="utf-8"))
    fps = profile_fps(root)
    p = root.find("profile")
    print(f"project: {proj.name}  {p.get('width')}x{p.get('height')} @ {float(fps):.3f}fps  "
          f"human_modified={human_modified(proj)}")
    res = {}
    for e in root:
        if e.tag in ("chain", "producer") and e.get("id"):
            r = e.find("./property[@name='resource']")
            res[e.get("id")] = (r.text if r is not None else "")
    for pl in root.findall("playlist"):
        kind = "video" if pl.find("./property[@name='shotcut:video']") is not None else \
               "audio" if pl.find("./property[@name='shotcut:audio']") is not None else None
        if not kind:
            continue
        nm = pl.find("./property[@name='shotcut:name']")
        print(f"track {pl.get('id')} [{kind}] name={nm.text if nm is not None else ''}")
        pos = 0
        for e in pl:
            if e.tag == "blank":
                pos += frames_of(e.get("length"), fps)
                print(f"   blank {e.get('length')}")
            elif e.tag == "entry":
                n = frames_of(e.get("out"), fps) - frames_of(e.get("in"), fps) + 1
                filt = [f.find("./property[@name='mlt_service']").text for f in e.findall("filter")
                        if f.find("./property[@name='mlt_service']") is not None]
                print(f"   @{tc(pos, fps)}  {e.get('producer')}  in={e.get('in')} out={e.get('out')}  "
                      f"{Path(res.get(e.get('producer'), '')).name}  filters={filt}")
                pos += n
    print(f"timeline length: {tc(timeline_end(root), fps)}")


def main(argv):
    if len(argv) < 3:
        raise SystemExit(__doc__)
    cmd, proj = argv[1], Path(argv[2])
    if cmd == "validate":
        validate_text(proj.read_text(encoding="utf-8"))
        print("well-formed + structure OK")
        if "--melt" in argv:
            melt_check(proj)
    elif cmd == "summary":
        cmd_summary(proj)
    elif cmd == "status":
        print({True: "HUMAN-MODIFIED since last agent write: run summary, edit surgically",
               False: "unchanged since last agent write", None: "no agent record"}[human_modified(proj)])
    elif cmd == "backup":
        print(backup(proj))
    elif cmd == "create":
        cmd_create(proj, [Path(c) for c in argv[3:]])
    elif cmd == "append-clip":
        cmd_append(proj, Path(argv[3]))
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main(sys.argv)
