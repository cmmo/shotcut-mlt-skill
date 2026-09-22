"""Derive a shorter project (highlight cut) from an existing Shotcut project. The source is never modified.

Usage: uv run scripts/mlt_cut.py <src.mlt> <dst.mlt> <spec.json>
spec:  {"title_s": 3, "segments": [[41.5, 48.5], [107.5, 113.5]]}   # segment times = SOURCE project timeline seconds

- V1: everything before the main clip (title card) is kept, trimmed to title_s; the main clip is cut into the segments.
- Overlay tracks (V2, V3, ...): every overlay clip is copied (with its human-edited text/filters) if >= 2s of it falls
  inside a segment; it is trimmed to the segment and moved to its new position. Others are dropped.
- A trimmed text clip gets its own retimed copy of its producer, so its fade still lands on its new last frame
  instead of being cut off mid-hold.
- Refuses to overwrite dst. Output is validated before writing.
"""
import copy
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import mlt_tools as M  # noqa: E402
import mlt_text as T  # noqa: E402

MIN_OVERLAY_S = 2.0
ANIMATED = ("opacity", "geometry", "transition.rect")


def retime_anim(text: str, old_n: int, new_n: int) -> str:
    """Pull an animation's tail keyframes back so the move/fade still finishes on the new last frame.

    Our own filters write plain frame numbers (`0=0;10=1;138=1;149=0`). Shotcut rewrites them as
    timecodes once a human edits the filter; those are left untouched rather than guessed at, since
    a wrong keyframe is worse than an unchanged one.
    """
    keys = []
    for part in text.strip(";").split(";"):
        if "=" not in part:
            return text
        pos, val = part.split("=", 1)
        if not re.fullmatch(r"\d+", pos.strip()):
            return text
        keys.append([int(pos.strip()), val])
    if len(keys) < 2 or max(k[0] for k in keys) <= new_n - 1:
        return text  # already fits inside the shorter clip

    tail = keys[-1][0] - keys[-2][0]          # how long the closing fade/move takes
    keys[-1][0] = new_n - 1
    keys[-2][0] = max(keys[-2][0], 0) if keys[-2][0] < new_n - 1 - tail else new_n - 1 - tail
    for i in range(1, len(keys)):             # keep positions strictly increasing
        if keys[i][0] <= keys[i - 1][0]:
            keys[i][0] = keys[i - 1][0] + 1
    keys = [k for k in keys if k[0] <= new_n - 1]
    if len(keys) < 2:                         # clip too short for the animation: hold the end value
        keys = [[0, text.split("=", 1)[1].split(";")[0]], [new_n - 1, text.strip(";").rsplit("=", 1)[1]]]
    return ";".join(f"{p}={v}" for p, v in keys)


def retime_producer(root, prod, new_n, fps):
    """A copy of a text/colour producer shortened to new_n frames, with its filter animations retimed."""
    old_n = M.frames_of(prod.get("out"), fps) + 1
    c = copy.deepcopy(prod)
    c.set("id", M.next_id(root, "producer"))
    c.set("out", M.tc(new_n - 1, fps))
    length = c.find("./property[@name='length']")
    if length is not None:
        length.text = M.tc(new_n, fps)
    for f in c.findall("filter"):
        if f.get("out") is not None:
            f.set("out", M.tc(new_n - 1, fps))
        for name in ANIMATED:
            p = f.find(f"./property[@name='{name}']")
            if p is not None and p.text:
                p.text = retime_anim(p.text, old_n, new_n)
    return c


def main(src: Path, dst: Path, spec: dict):
    if dst.exists():
        raise SystemExit(f"REFUSING: {dst} exists")
    root = M.validate_text(src.read_text(encoding="utf-8-sig"))
    fps = M.profile_fps(root)
    v1 = M.video_playlist(root)
    entries = [e for e in v1 if e.tag == "entry"]
    lens = [M.frames_of(e.get("out"), fps) - M.frames_of(e.get("in"), fps) + 1 for e in entries]
    main_i = lens.index(max(lens))
    head, main_e = entries[:main_i], entries[main_i]
    main_start = sum(lens[:main_i])  # source-timeline frame where the main clip starts
    main_in = M.frames_of(main_e.get("in"), fps)

    # --- new V1: shortened title card, then one entry per segment ---
    title_n = round(spec.get("title_s", 3) * float(fps))
    if head:
        h = head[0]
        prod = root.find(f"producer[@id='{h.get('producer')}']")
        if prod is not None and title_n < lens[0]:
            new_prod = retime_producer(root, prod, title_n, fps)
            root.insert(list(root).index(prod), new_prod)
            h.set("producer", new_prod.get("id"))
        h.set("in", "00:00:00.000")
        h.set("out", M.tc(title_n - 1, fps))
        new_head_len = title_n
        for extra in head[1:]:
            v1.remove(extra)
    else:
        new_head_len = 0
    v1.remove(main_e)
    seg_map = []  # (src_start, src_end, new_start) in source-timeline frames
    cur = new_head_len
    for a, b in spec["segments"]:
        fa, fb = round(a * float(fps)), round(b * float(fps))
        ET.SubElement(v1, "entry", producer=main_e.get("producer"),
                      **{"in": M.tc(main_in + fa - main_start, fps)},
                      out=M.tc(main_in + fb - main_start - 1, fps))
        seg_map.append((fa, fb, cur))
        cur += fb - fa

    # --- overlays: keep what is still visible, trimmed to its segment ---
    used = {main_e.get("producer")} | {h.get("producer") for h in v1 if h.tag == "entry"}
    dropped = kept = 0
    for pl in root.findall("playlist"):
        if pl is v1 or pl.find("./property[@name='shotcut:video']") is None:
            continue
        new_items = []
        for start, n, e in T.layout(pl, fps):
            e_in = M.frames_of(e.get("in"), fps)
            ok = False
            for fa, fb, ns in seg_map:
                s, t = max(start, fa), min(start + n, fb)
                if t - s < MIN_OVERLAY_S * float(fps):
                    continue
                ne = copy.deepcopy(e)
                visible = t - s
                prod = root.find(f"producer[@id='{e.get('producer')}']")
                if visible < n and prod is not None:
                    # trimmed: give it its own producer so the fade lands on the new last frame
                    new_prod = retime_producer(root, prod, visible, fps)
                    root.insert(list(root).index(prod), new_prod)
                    ne.set("producer", new_prod.get("id"))
                    ne.set("in", "00:00:00.000")
                    ne.set("out", M.tc(visible - 1, fps))
                else:
                    ne.set("in", M.tc(e_in + s - start, fps))
                    ne.set("out", M.tc(e_in + t - start - 1, fps))
                used.add(ne.get("producer"))
                new_items.append((ns + s - fa, visible, ne))
                ok = True
            kept += ok
            dropped += not ok
        T.relayout(pl, new_items, fps)

    for el in list(root):  # drop producers nothing references any more
        if el.tag in ("producer", "chain") and el.get("id") not in used and el.get("id") != "black":
            root.remove(el)
    T.fit_timeline(root)
    M.write_project(dst, root)
    print(f"wrote {dst}: {M.tc(M.timeline_end(root), fps)} long; overlays kept={kept} dropped={dropped}")


if __name__ == "__main__":
    if len(sys.argv) != 4:
        raise SystemExit(__doc__)
    main(Path(sys.argv[1]), Path(sys.argv[2]), json.loads(Path(sys.argv[3]).read_text(encoding="utf-8-sig")))
