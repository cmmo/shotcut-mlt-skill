"""Give video clips a livelier look: color grade + slow zoom (punch-in / pull-out) on every main V1 clip.

Usage: uv run scripts/mlt_polish.py <proj.mlt> [--sat 1.4] [--contrast 0.58] [--zoom 0.12]
Read -> backup -> surgical edit -> validate -> atomic write. Close Shotcut first.

Filter structures come from Shotcut's own QML definitions (share/shotcut/qml/filters/*/meta*.qml, ui*.qml):
- saturation: frei0r.saturat0r, property "0"; Shotcut UI percent = value * 800 (0.125 = 100%)
- contrast:   lift_gamma_gain (shotcut:filter=contrast); UI level v: gain_rgb = 2v, gamma_rgb = 2(1-v); v=0.5 neutral
- zoom:       affine (shotcut:filter=affineSizePosition), transition.rect keyframes 'pos=x%/y%:w%xh%'
Clip filters live INSIDE the <chain> (Shotcut drops filters placed inside <entry>), so every entry gets its own chain copy.
"""
import copy
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import mlt_tools as M  # noqa: E402
import mlt_text as T  # noqa: E402


def opt(name, default):
    a = sys.argv
    return float(a[a.index(name) + 1]) if name in a else default


def make_filter(root, fps, e_in, e_out, props):
    f = ET.Element("filter", id=M.next_id(root, "filter"), **{"in": e_in}, out=e_out)
    for k, v in props:
        M.prop(f, k, v)
    return f


def polish(proj: Path, sat: float, contrast: float, zoom: float):
    root, fps = T.prepare(proj)
    v1 = M.video_playlist(root)
    chains = {c.get("id"): c for c in root.findall("chain")}
    entries = [e for e in v1 if e.tag == "entry" and e.get("producer") in chains]
    used_orig = set()
    for i, e in enumerate(entries):
        orig = chains[e.get("producer")]
        used_orig.add(orig.get("id"))
        c = copy.deepcopy(orig)
        c.set("id", M.next_id(root, "chain"))
        for old in c.findall("filter"):  # start clean: replace any earlier grade on this copy
            c.remove(old)
        root.insert(list(root).index(orig) + 1, c)
        e.set("producer", c.get("id"))
        n = M.frames_of(e.get("out"), fps) - M.frames_of(e.get("in"), fps) + 1
        a, b = e.get("in"), e.get("out")
        # zoom: alternate push-in / pull-out, centered
        big = 1 + zoom
        off = -(big - 1) / 2 * 100
        small = "0%/0%:100%x100%"
        large = f"{off:.1f}%/{off:.1f}%:{big * 100:.1f}%x{big * 100:.1f}%"
        rect = f"0={small};{n - 1}={large}" if i % 2 == 0 else f"0={large};{n - 1}={small}"
        c.append(make_filter(root, fps, a, b, [
            ("0", sat * 0.125), ("mlt_service", "frei0r.saturat0r")]))
        c.append(make_filter(root, fps, a, b, [
            ("gamma_r", (1 - contrast) * 2), ("gamma_g", (1 - contrast) * 2), ("gamma_b", (1 - contrast) * 2),
            ("gain_r", contrast * 2), ("gain_g", contrast * 2), ("gain_b", contrast * 2),
            ("mlt_service", "lift_gamma_gain"), ("shotcut:filter", "contrast")]))
        c.append(make_filter(root, fps, a, b, [
            ("transition.rect", rect), ("transition.fill", 0), ("transition.distort", 0),
            ("transition.valign", "middle"), ("transition.halign", "center"), ("transition.threads", 0),
            ("transition.fix_rotate_x", 0), ("mlt_service", "affine"), ("shotcut:filter", "affineSizePosition")]))
    for cid in used_orig:  # remove chain copies' originals if no longer referenced
        if not any(x.get("producer") == cid for x in root.iter("entry")):
            root.remove(chains[cid])
    T.fit_timeline(root)
    M.write_project(proj, root)
    print(f"graded {len(entries)} clip(s): saturation x{sat}, contrast {contrast}, zoom {zoom:.0%}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    polish(Path(sys.argv[1]), opt("--sat", 1.4), opt("--contrast", 0.58), opt("--zoom", 0.12))
