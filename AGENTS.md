# Agent instructions: editing Shotcut `.mlt` projects

**Full instructions are in [`SKILL.md`](SKILL.md). Read it before editing any project**, plus
[`references/mlt-xml.md`](references/mlt-xml.md) before writing an XML structure you have not used before.
This file exists so any agent that looks for `AGENTS.md` finds the entry point; it is a summary, not a replacement.

## What this is

Video editing where the artifact is the **`.mlt` project file**, not a rendered video. FFmpeg does media work,
Shotcut is the human's GUI timeline, Git records every handoff. The person opens what you produce, changes it
by hand, saves, and you continue from *their* version.

## Rules worth not breaking

These exist because each one, when broken, destroys work the person cannot easily recover:

1. **Shotcut must be closed before you write to a `.mlt`.** Shotcut holds the project in memory and rewrites
   the whole file on save, so your edit vanishes at their next Ctrl+S. Check `Get-Process shotcut` (Windows)
   or `pgrep -x shotcut`.
2. **Never regenerate an existing project from your own spec.** That silently reverts every manual adjustment.
   Edit surgically, or derive a new file with `scripts/mlt_cut.py`.
3. **Read the timeline before changing it** (`scripts/mlt_tools.py summary`). Producer ids are renumbered by
   Shotcut on save, so identify clips by position, resource and in/out — never by a remembered id.
4. **After they say they saved, read `git diff` yourself** rather than asking what changed. Filter Shotcut's
   noise (`meta.*` properties, renumbered ids) to find the real edits, then say what you found so they can
   correct you.
5. **Checkpoint at every handoff** with an `agent:`, `human:` or `chore:` prefix. Branch from an old checkpoint
   rather than rewriting history.
6. **Look at a rendered frame after any visual change.** Valid XML that loads in melt can still render black or
   drop a filter — both have happened. `scripts/render_frame.py` takes seconds.

## Scripts

Standard-library Python plus one PowerShell helper; run from the project root. `scripts/checkpoint.ps1` is
Windows-only — elsewhere run the equivalent `git` commands directly. See `SKILL.md` for the full table and
argument formats.

```
inspect_media.py   ffprobe -> compact JSON
mlt_tools.py       create / append-clip / summary / status / validate / backup
mlt_text.py        title cards, subtitles, pop-ups, emoji stickers
mlt_cut.py         derive a shorter cut, carrying overlays across
mlt_polish.py      colour grade + slow zoom
render_frame.py    preview frames via melt
media_manifest.py  text record of source media
checkpoint.ps1     validated Git checkpoint
```

## Requirements

FFmpeg (+ ffprobe), Shotcut (bundles `melt`), `uv`, Git. Set `MELT_PATH` if melt is not on `PATH` and not in a
standard Shotcut install location.
