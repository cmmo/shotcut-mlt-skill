---
name: shotcut-mlt
description: Edit video by writing Shotcut .mlt project files (MLT XML) that the person can then open and refine in the Shotcut GUI, with FFmpeg/ffprobe for media work and melt for headless rendering. Use this whenever Shotcut, .mlt, or MLT XML comes up, and whenever someone wants to cut, trim, subtitle, caption, title, grade, or build a highlight reel from a video, add text or emoji overlays, or set up an agent-assisted video editing workflow — including a plain "edit this video for me" when they will keep editing it themselves afterwards. Reach for it too when an edit has to survive the person's own manual changes instead of being re-rendered from scratch.
---

# Shotcut .mlt editing

## The idea

Most agent video editing renders a finished file: the person can watch it, but they cannot change it, and the next request re-renders everything from scratch. This skill treats the **`.mlt` project file as the shared artifact** instead.

```
person describes an edit
  → you inspect media (ffprobe) and edit the .mlt
  → validate, render a frame, Git checkpoint
  → they open it in Shotcut, refine by hand, Ctrl+S, close
  → Git checkpoint
  → you read their diff and continue from their version
```

`.mlt` is MLT XML: plain text, diffable, and the native format Shotcut saves. FFmpeg does media work (transcode, deinterlace, extract). The timeline stays editable.

## Before editing anything

Check the tools once per session; they are separate installs and a stale PATH is the usual failure:

```powershell
ffmpeg -version; ffprobe -version; uv --version; git --version
Get-Item "$env:LOCALAPPDATA\Programs\Shotcut\shotcut.exe"   # melt.exe sits beside it
```

Missing pieces on Windows: `winget install --id Gyan.FFmpeg -e -s winget`, `Meltytech.Shotcut`, `Git.Git`, plus `uv`. After any install, PATH in an already-open shell is stale — refresh it:

```powershell
$env:Path = [Environment]::GetEnvironmentVariable('Path','Machine')+';'+[Environment]::GetEnvironmentVariable('Path','User')
```

The scripts here are stdlib-only Python run with `uv run`; nothing to pip install. Set `MELT_PATH` if melt lives somewhere unusual.

## Project layout

A project directory works best as a Git repo shaped like this — Git is the editing history, not the backups:

```
project\
  media\raw\         originals, never modified
  media\generated\   FFmpeg output and renders
  projects\          the .mlt files
  projects\backups\  automatic pre-edit copies (git-ignored; crash protection only)
  projects\.state\   record of what the agent last wrote (git-ignored)
```

Set it up once, before the first checkpoint:

```powershell
git init -b main
git config user.name "<name>"; git config user.email "<email>"   # commits fail without this
Copy-Item SKILL\assets\project-gitignore .gitignore
```

**Point `create` straight at `media\raw\` when ffprobe shows progressive, square pixels (`sample_aspect_ratio 1:1`) and a common codec** — most phone and screen-recorded footage qualifies, and a needless transcode costs minutes and quality. Make a working copy in `media\generated\` only when something needs fixing first: interlacing, non-square pixels, a variable frame rate, or a codec that stutters in Shotcut's preview.

Copy `assets/project-gitignore` to the project root as `.gitignore`: it keeps video, audio, images, `backups/` and `.state/` out of Git. `media_manifest.py` records sizes, durations and hashes so an old checkpoint is still understandable without the video in Git.

## The rules that matter

**Shotcut must be closed before you modify a `.mlt`.** Shotcut holds the project in memory and writes the whole file on save, so any edit you make while it is open is silently lost at their next Ctrl+S. Check with `Get-Process shotcut`.

**Never regenerate a project that already exists.** Rebuilding from your own spec throws away every hand adjustment they made — the exact thing this workflow exists to prevent. `mlt_tools.py create` refuses to overwrite. Make surgical edits (add or change specific elements), or derive a *new* file with `mlt_cut.py`.

**Read the timeline before you change it.** `mlt_tools.py summary` shows what is actually there. Producer ids are not stable — Shotcut renumbers `chain0`, `chain1`… on save — so identify clips by position, resource and in/out points, never by an id you remember from earlier.

**After they say they saved, read the diff yourself.** `git diff -- <file>` tells you what changed; asking them to describe it wastes their time and they often forget details. Filter the noise: Shotcut rewrites `meta.*` properties and renumbers ids on every save, so `git diff -- x.mlt | Select-String 'meta\.' -NotMatch` shows the real edits. Then write the `human:` checkpoint message from what you found and tell them what you saw, so they can correct you.

**Checkpoint at every handoff**, with `agent:`, `human:` or `chore:` prefixes — one commit per change of control. Prefer branching from an old checkpoint (`git switch -c alternate-cut <commit>`) over rewriting history, and use `git branch -d`, never `-D`.

**Check the docs before writing a structure you have not verified.** See `references/mlt-xml.md` for what is confirmed and what is not. Valid XML that melt loads can still be wrong — the failure mode is a black screen or a silently dropped filter, not a parse error.

## Scripts

Run from the project root. `SKILL` below is this skill's directory.

```powershell
# inspect
uv run SKILL\scripts\inspect_media.py media\raw\clip.mp4          # compact JSON summary
uv run SKILL\scripts\mlt_tools.py summary projects\x.mlt          # what is on the timeline
uv run SKILL\scripts\mlt_tools.py status  projects\x.mlt          # human-modified since your last write?

# edit
uv run SKILL\scripts\mlt_tools.py create  projects\x.mlt media\generated\a.mp4   # new project (refuses overwrite)
uv run SKILL\scripts\mlt_tools.py append-clip projects\x.mlt media\generated\b.mp4
uv run SKILL\scripts\mlt_text.py  title   projects\x.mlt 5 "Title" "Subtitle"    # title card at start of V1
uv run SKILL\scripts\mlt_text.py  add-text projects\x.mlt items.json             # subtitles / popups / stickers
uv run SKILL\scripts\mlt_polish.py projects\x.mlt --sat 1.4 --contrast 0.58 --zoom 0.12
uv run SKILL\scripts\mlt_cut.py   projects\full.mlt projects\short.mlt spec.json # derive a shorter cut

# verify
uv run SKILL\scripts\mlt_tools.py validate projects\x.mlt --melt   # XML + structure + headless render test
uv run SKILL\scripts\render_frame.py projects\x.mlt 12.5 44 --out DIR   # one or more TIMELINE SECONDS
uv run SKILL\scripts\media_manifest.py            # no args, from the project root; --check to compare with disk
```

Every editing script backs up first, validates, then writes atomically, so a failed edit leaves the original intact. They also stretch the hidden `background` track and the tractor to match the timeline length — worth mentioning when you report back, because it changes the project's total duration even though no visible clip moved.

`add-text` takes a JSON list. `start` is timeline seconds; put overlapping items on different tracks:

```json
[{"start": 7, "dur": 8, "track": "V2", "style": "subtitle", "text": "line one\nline two"},
 {"start": 43, "dur": 3, "track": "V3", "style": "popup",   "pos": "right", "text": "Nice!"},
 {"start": 44, "dur": 2, "track": "V4", "style": "sticker", "color": "#ffff7a00", "text": "🔥"}]
```

`mlt_cut.py` takes `{"title_s": 3, "segments": [[41.5, 48.5], [107.5, 113.5]]}`. Overlays are carried across with their current text and filters, trimmed to each segment, and dropped when less than 2 s would show.

### Order matters: title → cut → text

The scripts constrain the order, and getting it wrong wastes a rebuild:

1. **`create`** the project from the clip.
2. **`title`** next — it refuses once any overlay track has content, because inserting a card at the front would shift every overlay out of sync.
3. **`mlt_cut`** next if the length needs changing — it carries a title through only when one already exists on V1, and it **drops any overlay with less than 2 s visible inside a segment**. Cutting after adding text quietly eats short captions.
4. **`add-text`** last, positioned against the final timeline.

### Hitting a target length

There is no `trim` command; `mlt_cut.py` is the trim tool, and a single segment is a plain trim. For "a 10 second opener" from a 40 s clip with a 3 s title:

```powershell
uv run SKILL\scripts\mlt_tools.py create projects\opener.mlt media\raw\clip.mp4
uv run SKILL\scripts\mlt_text.py  title  projects\opener.mlt 3 "Summer 2026"
'{"title_s": 3, "segments": [[3, 10]]}' | Set-Content spec.json -Encoding utf8
uv run SKILL\scripts\mlt_cut.py   projects\opener.mlt projects\opener-10s.mlt spec.json
uv run SKILL\scripts\mlt_text.py  add-text projects\opener-10s.mlt captions.json
```

Segment times are source-timeline seconds and include the title card, so `[[3, 10]]` means "from the end of the 3 s title to the 10 s mark" — 7 s of footage, 10 s total. Keep the intermediate project: re-deriving a different length from it beats rebuilding.

**Three different clocks, easy to confuse.** `add-text` and `mlt_cut` both count seconds along the **source project's timeline**, which includes the title card. A clip's `in`/`out` count from the **start of the media file**. And when someone says "at 8 seconds", they usually mean 8 seconds into the *footage*, which is not the same as 8 seconds into the timeline once a title card sits in front of it. Say which you used ("8 s into the footage, which is 0:11 on the timeline") rather than picking one silently — it is a one-line note that saves them re-cutting.

## Always look at the result

Valid XML proves nothing about the picture. After any visual change, render a frame with `render_frame.py` and actually view the PNG. Two of the worst bugs in this workflow's history — a whole video rendering black, and a filter silently disappearing — both passed validation. A preview frame catches them in seconds.

To render the finished video headlessly:

```powershell
& "$env:LOCALAPPDATA\Programs\Shotcut\melt.exe" projects\x.mlt -consumer avformat:out.mp4 `
  vcodec=libx264 crf=20 preset=fast acodec=aac ab=192k terminate_on_pause=1
```

`terminate_on_pause=1` matters: without it melt never exits, and the MP4 is left unfinalized.

## FFmpeg or the timeline?

| FFmpeg, into `media\generated\` | The `.mlt` timeline |
|---|---|
| Transcode, deinterlace, resize, fps/pixel-aspect fixes | Cut order, trims, in/out points |
| Proxies, audio extraction, loudness | Track layout, transitions, overlays |
| Analysis: silence, scene detection, thumbnails | Anything they will refine by eye |
| Generating test media | Anything that should stay editable |

Camera footage is often interlaced with non-square pixels (AVCHD `.MTS` at 1440x1080, 4:3 pixels). Convert to a square-pixel progressive working copy first, or Shotcut shows the wrong aspect:

```powershell
ffmpeg -y -v error -i media\raw\in.MTS -vf "yadif=0:-1:0,scale=1920:1080:flags=lanczos,setsar=1" `
  -r 30000/1001 -c:v libx264 -crf 18 -preset fast -pix_fmt yuv420p -c:a aac -b:a 192k `
  -movflags +faststart media\generated\work.mp4
```

This takes minutes for a few minutes of footage. Run it in the foreground with a long timeout — a detached background encode that gets killed leaves a file with no `moov` atom, which ffprobe then rejects.

## References

- `references/mlt-xml.md` — the XML structures: what is verified, with real snippets. **Read this before writing any structure you have not used before**, especially filters, transitions, tracks and keyframes.
- `references/troubleshooting.md` — symptoms and causes: black video, vanished filters, melt hanging, emoji, PowerShell 5.1 quirks.
