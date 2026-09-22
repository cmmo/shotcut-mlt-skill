"""Text overlays for Shotcut projects, built the way Shotcut itself saves them
(transparent `color` clip + `dynamictext` filter, on an overlay video track).

Commands (all: read -> backup -> surgical edit -> validate -> atomic write):
  title    <proj.mlt> <dur_s> "<line1>" ["<line2>"]   insert a title card at the START of V1 (refuses if overlays exist)
  add-text <proj.mlt> <items.json>                    add overlay clips to track V2 (created if missing)

items.json: [{"start": 12.0, "dur": 5.0, "text": "...", "style": "subtitle|popup", "pos": "left|center|right"}]
`start` is TIMELINE seconds. Existing V2 content (e.g. human edits) is kept untouched; overlapping items are refused.
"""
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import mlt_tools as M  # noqa: E402

FONT = "Noto Sans JP"
OVERLAY = "V2"


def dyn_filter(fid, fps, dur, text, geometry, size, fg, *, weight=700, outline=4, olcolour="#ff000000",
               halign="center", valign="middle", opacity="1.0"):
    f = ET.Element("filter", id=fid, out=M.tc(dur - 1, fps))
    for k, v in [("argument", text), ("geometry", geometry), ("family", FONT), ("size", size), ("weight", weight),
                 ("style", "normal"), ("fgcolour", fg), ("bgcolour", "#00000000"), ("olcolour", olcolour),
                 ("pad", 0), ("halign", halign), ("valign", valign), ("outline", outline), ("underline", 0),
                 ("strikethrough", 0), ("opacity", opacity), ("mlt_service", "dynamictext"),
                 ("shotcut:filter", "dynamicText"), ("shotcut:usePointSize", 1),
                 ("shotcut:pointSize", round(size * 0.75))]:
        M.prop(f, k, v)
    return f


def text_producer(pid, fps, dur, caption, filters, color="#00000000"):
    p = ET.Element("producer", id=pid, **{"in": "00:00:00.000"}, out=M.tc(dur - 1, fps))
    for k, v in [("length", M.tc(dur, fps)), ("eof", "pause"), ("resource", color), ("aspect_ratio", 1),
                 ("mlt_service", "color"), ("mlt_image_format", "rgba"), ("shotcut:caption", caption),
                 ("shotcut:detail", caption), ("seekable", 1)]:
        M.prop(p, k, v)
    for f in filters:
        p.append(f)
    return p


def insert_producer(root, elem):
    idx = max((i for i, e in enumerate(root) if e.tag in ("chain", "producer")), default=0) + 1
    root.insert(idx, elem)


def fit_timeline(root):
    fps = M.profile_fps(root)
    end = M.tc(M.timeline_end(root) - 1, fps)
    tractors = root.findall("tractor")
    tr = next((t for t in tractors if t.find("./property[@name='shotcut']") is not None), tractors[-1])
    tr.set("out", end)
    bg = root.find("producer[@id='black']")
    if bg is not None:
        bg.set("out", end)
    for e in root.findall("playlist[@id='background']/entry"):
        e.set("out", end)


def find_track(root, name):
    for pl in root.findall("playlist"):
        n = pl.find("./property[@name='shotcut:name']")
        if n is not None and n.text == name and pl.find("./property[@name='shotcut:video']") is not None:
            return pl
    return None


def ensure_overlay_track(root, name=OVERLAY):
    pl = find_track(root, name)
    if pl is not None:
        return pl
    pid = M.next_id(root, "playlist")
    pl = ET.Element("playlist", id=pid)
    M.prop(pl, "shotcut:video", 1)
    M.prop(pl, "shotcut:name", name)
    tr = next(t for t in root.findall("tractor") if t.find("./property[@name='shotcut']") is not None)
    root.insert(list(root).index(tr), pl)
    n = len(tr.findall("track"))
    # Shotcut writes every <track> before any <transition>; matching that keeps its next save from
    # reordering the file, which would bury the human's real edits in a large cosmetic diff.
    kids = list(tr)
    after_last_track = max(i for i, c in enumerate(kids) if c.tag == "track") + 1
    tr.insert(after_last_track, ET.Element("track", producer=pid))
    t_mix = ET.SubElement(tr, "transition", id=M.next_id(root, "transition"))
    for k, v in [("a_track", 0), ("b_track", n), ("mlt_service", "mix"), ("always_active", 1), ("sum", 1)]:
        M.prop(t_mix, k, v)
    t_bl = ET.SubElement(tr, "transition", id=M.next_id(root, "transition"))
    # a_track=1 (lowest video track) for every overlay, as Shotcut writes it; a_track=n-1 blacks out the video
    for k, v in [("a_track", 1), ("b_track", n), ("version", "0.1"), ("mlt_service", "frei0r.cairoblend"),
                 ("threads", 0), ("disable", 0)]:
        M.prop(t_bl, k, v)
    return pl


def layout(pl, fps):
    """[(start, length, element)] for entries of a playlist; blanks are implicit gaps."""
    out, pos = [], 0
    for e in pl:
        if e.tag == "blank":
            pos += M.frames_of(e.get("length"), fps)
        elif e.tag == "entry":
            n = M.frames_of(e.get("out"), fps) - M.frames_of(e.get("in"), fps) + 1
            out.append((pos, n, e))
            pos += n
    return out


def relayout(pl, items, fps):
    for e in [e for e in pl if e.tag in ("entry", "blank")]:
        pl.remove(e)
    pos = 0
    for start, n, e in sorted(items, key=lambda x: x[0]):
        if start < pos:
            raise SystemExit(f"overlap on {OVERLAY} at {M.tc(start, fps)}")
        if start > pos:
            ET.SubElement(pl, "blank", length=M.tc(start - pos, fps))
        pl.append(e)
        pos = start + n


def style_filters(root, fps, dur, text, style, pos, color=None):
    p = root.find("profile")
    w, h = int(p.get("width")), int(p.get("height"))
    if style == "subtitle":
        y, hh = int(h * 0.80), int(h * 0.17)
        anim = f"0=0;10=1;{max(dur - 12, 11)}=1;{dur - 1}=0"
        return [dyn_filter(M.next_id(root, "filter"), fps, dur, text, f"0 {y} {w} {hh} 1", int(h * 0.055),
                           "#ffffffff", outline=4, olcolour="#dd000000", opacity=anim)]
    if style == "popup":
        dx = {"left": -int(w * 0.22), "center": 0, "right": int(w * 0.22)}[pos]
        y0, hh = int(h * 0.05), int(h * 0.26)
        geo = f"0={dx} {y0 + 50} {w} {hh} 1;10={dx} {y0} {w} {hh} 1;{dur - 1}={dx} {y0 - 30} {w} {hh} 1"
        anim = f"0=0;5=1;{max(dur - 14, 6)}=1;{dur - 1}=0"
        return [dyn_filter(M.next_id(root, "filter"), fps, dur, text, geo, int(h * 0.15), "#fffff000",
                           weight=900, outline=9, olcolour="#ffe0002a", opacity=anim)]
    if style == "sticker":  # big emoji that pops in, bobs up and fades out
        dx = {"left": -int(w * 0.36), "center": 0, "right": int(w * 0.36)}[pos]
        y0, hh = int(h * 0.18), int(h * 0.30)
        geo = f"0={dx} {y0 + 70} {w} {hh} 1;12={dx} {y0} {w} {hh} 1;{dur - 1}={dx} {y0 - 60} {w} {hh} 1"
        anim = f"0=0;4=1;{max(dur - 12, 5)}=1;{dur - 1}=0"
        return [dyn_filter(M.next_id(root, "filter"), fps, dur, text, geo, int(h * 0.22), color or "#ffffffff",
                           outline=0, opacity=anim)]
    raise SystemExit(f"unknown style {style!r}")


def prepare(proj: Path):
    if not proj.exists():
        raise SystemExit(f"{proj} does not exist")
    print({True: "note: project modified by a human since last agent write (preserved)",
           False: "note: unchanged since last agent write",
           None: "note: no agent-write record; treating file as human-owned"}[M.human_modified(proj)])
    root = M.validate_text(proj.read_text(encoding="utf-8-sig"))
    print(f"backup: {M.backup(proj)}")
    return root, M.profile_fps(root)


def cmd_title(proj: Path, dur_s: float, lines: list[str]):
    root, fps = prepare(proj)
    v1 = M.video_playlist(root)
    for pl in root.findall("playlist"):
        if pl is not v1 and pl.find("./property[@name='shotcut:video']") is not None and pl.find("entry") is not None:
            raise SystemExit("overlay tracks already have content; title must be inserted before overlays")
    p = root.find("profile")
    w, h = int(p.get("width")), int(p.get("height"))
    dur = round(dur_s * float(fps))
    fade = f"0=0;15=1;{dur - 12}=1;{dur - 1}=0"
    fid = int(M.next_id(root, "filter")[6:])
    filters = [dyn_filter(f"filter{fid}", fps, dur, lines[0], f"0 {int(h*0.30)} {w} {int(h*0.25)} 1",
                          int(h * 0.11), "#ffffffff", weight=900, outline=0, opacity=fade)]
    if len(lines) > 1:
        filters.append(dyn_filter(f"filter{fid + 1}", fps, dur, lines[1], f"0 {int(h*0.58)} {w} {int(h*0.14)} 1",
                                  int(h * 0.05), "#ffffe8a0", weight=500, outline=0,
                                  opacity=f"0=0;30=1;{dur - 12}=1;{dur - 1}=0"))
    pid = M.next_id(root, "producer")
    prod = text_producer(pid, fps, dur, lines[0], filters, color="#0f2a4a")
    insert_producer(root, prod)
    entry = ET.Element("entry", producer=pid, **{"in": "00:00:00.000"}, out=M.tc(dur - 1, fps))
    idx = next(i for i, e in enumerate(v1) if e.tag in ("entry", "blank"))
    v1.insert(idx, entry)
    fit_timeline(root)
    M.write_project(proj, root)
    print(f"title card inserted ({dur_s}s); timeline now {M.tc(M.timeline_end(root), fps)}")


def cmd_add_text(proj: Path, items_file: Path):
    # utf-8-sig: PowerShell's Set-Content -Encoding utf8 writes a BOM, which plain utf-8 rejects
    items = json.loads(items_file.read_text(encoding="utf-8-sig"))
    root, fps = prepare(proj)
    tracks = {}  # track name -> (playlist, [(start, len, entry)])
    for it in items:
        name = it.get("track", OVERLAY)
        if name not in tracks:
            pl = ensure_overlay_track(root, name)
            tracks[name] = (pl, layout(pl, fps))
        dur = round(it["dur"] * float(fps))
        start = round(it["start"] * float(fps))
        pid = M.next_id(root, "producer")
        fl = style_filters(root, fps, dur, it["text"], it.get("style", "subtitle"), it.get("pos", "center"),
                           it.get("color"))
        prod = text_producer(pid, fps, dur, it["text"].replace("\n", " "), fl)
        insert_producer(root, prod)
        entry = ET.Element("entry", producer=pid, **{"in": "00:00:00.000"}, out=M.tc(dur - 1, fps))
        tracks[name][1].append((start, dur, entry))
    for pl, existing in tracks.values():
        relayout(pl, existing, fps)
    fit_timeline(root)
    M.write_project(proj, root)
    print(f"added {len(items)} overlay clip(s) to {', '.join(tracks)}")


if __name__ == "__main__":
    a = sys.argv
    if len(a) >= 5 and a[1] == "title":
        cmd_title(Path(a[2]), float(a[3]), a[4:6])
    elif len(a) == 4 and a[1] == "add-text":
        cmd_add_text(Path(a[2]), Path(a[3]))
    else:
        raise SystemExit(__doc__)
