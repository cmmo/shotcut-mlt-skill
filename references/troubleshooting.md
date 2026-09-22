# Troubleshooting

Symptoms first — these are the failures that actually happen, with what causes them.

## The rendered video is black, but the XML validates

Overlay track wiring. Two separate causes, both in the tractor's `frei0r.cairoblend` transitions:

- The **bottom** video track's blend must have `disable=1`. With `disable=0`, adding any overlay track blacks out the whole picture.
- **Every** overlay blend needs `a_track=1`, regardless of its track index. Chaining (`a_track = n-1`) renders black; `a_track=0` composites against the background and drops the layer beneath.

See `mlt-xml.md` for the full tractor block. Confirm the fix by rendering a frame, not by re-validating.

## A filter I added disappeared after they saved in Shotcut

The filter was inside an `<entry>`. Filters attach to the producer, so they belong inside `<chain>` or `<producer>`. Shotcut ignores entry-level filters and drops them on its next save. To grade one timeline segment, give that entry its own copy of the chain and put the filter there.

## melt never exits / the MP4 is corrupt

melt does not terminate on its own when driven non-interactively. Add `terminate_on_pause=1` to the consumer:

```powershell
melt projects\x.mlt -consumer avformat:out.mp4 vcodec=libx264 crf=20 acodec=aac ab=192k terminate_on_pause=1
```

Without it the process runs forever and the container is never finalized. For a single preview frame, `render_frame.py` polls until the PNG stops growing and then kills melt.

If melt appears to hang even on `-query consumers`, check for a stuck `melt.exe` from an earlier run: `Get-Process melt | Stop-Process -Force`.

## ffprobe: "moov atom not found"

The encode was interrupted, so the MP4 has no index. This happens when a long FFmpeg run is launched detached and the shell that owns it goes away. Re-run it in the foreground with a generous timeout. A 4-minute 1080p deinterlaced encode takes roughly 12 minutes.

## Shotcut shows the video squashed or stretched

Non-square pixels. AVCHD `.MTS` is commonly 1440x1080 with a 4:3 pixel aspect displaying as 16:9. Convert to a square-pixel progressive working copy before building the project:

```powershell
ffmpeg -y -v error -i in.MTS -vf "yadif=0:-1:0,scale=1920:1080:flags=lanczos,setsar=1" `
  -r 30000/1001 -c:v libx264 -crf 18 -preset fast -pix_fmt yuv420p -c:a aac -b:a 192k `
  -movflags +faststart media\generated\work.mp4
```

## I copied the project folder and it still uses the old media

`resource` paths are absolute, so copying or moving a project directory leaves every clip pointing at the original media. It keeps working as long as the old files exist, which is why this goes unnoticed until they are deleted or the folder moves to another machine.

Repointing is a deliberate act — do it when asked, or when the old path no longer exists, and say so rather than rewriting their paths silently. Back up, replace the path prefix in the `resource` properties (forward slashes), validate, then checkpoint it as its own `chore:` commit so it is easy to identify later. On a second machine, keep it on a separate branch: the paths are machine-specific and do not belong on `main`.

## An exported video has a black tail

The visible tracks are shorter than the hidden `background` track and the tractor `out`. This happens when a clip is trimmed in the GUI, since Shotcut does not always shrink the background to match. The scripts here call `fit_timeline`, which recomputes both.

It is worth a word of warning either way: fixing it changes the project's total duration, which someone who trimmed deliberately may not expect. Re-saving in Shotcut also recomputes it.

## A caption pops off instead of fading after a cut

Its animation keyframes still describe the old, longer duration, so the fade-out sits past the clip's new last frame and never plays. Trimming an `<entry>` does not retime the filters on its producer.

`mlt_cut.py` handles this by giving a trimmed text clip its own copy of the producer with the animation pulled back to the new length. If you trim a text clip by hand, retime its `opacity` (and `geometry`, if it moves) the same way, and set the filter's `out`. Verify by rendering frames across the fade window, not just one in the middle — a frame sampled during the hold looks identical either way.

## Text renders as boxes, or not at all

The font lacks the glyphs, or is not installed. Check first:

```powershell
Add-Type -AssemblyName System.Drawing
(New-Object System.Drawing.Text.InstalledFontCollection).Families | ? Name -match 'Noto Sans JP|Yu Gothic|BIZ UD'
```

Report a missing font rather than silently substituting one — the person may care which typeface their titles use.

## Emoji are monochrome outlines

Expected. melt, FFmpeg drawtext and WPF all render the outline layer of Segoe UI Emoji rather than its colour layers. Tint each with `fgcolour` and keep one emoji per clip; mixing emoji into a sentence garbles neighbouring glyphs. Full colour requires compositing PNG emoji images.

## `git` / `ffmpeg` not recognised, right after installing

The shell's PATH is a snapshot from when it opened. Either open a new shell or refresh in place:

```powershell
$env:Path = [Environment]::GetEnvironmentVariable('Path','Machine')+';'+[Environment]::GetEnvironmentVariable('Path','User')
```

In a restricted agent runner, a directory can appear on `PATH` while the process is denied permission to
traverse it. `Get-Command uv` or `Get-Command ffmpeg` then reports that the command does not exist even though
it works in the person's interactive terminal. Check the package directory with `Test-Path` and
`Get-ChildItem`; if traversal is denied, request access and invoke the executable by its absolute path. Do not
reinstall the tool merely because the restricted process cannot resolve it.

## `uv run` downloads Python or fails creating a Python version link

`uv run` may try to install a managed Python when the runner's existing interpreter is not discoverable. In a
restricted or cross-user process, that install can fail under `%APPDATA%\uv` even though a usable Python is
already available. Pin that interpreter for the session and prevent an unnecessary download:

```powershell
$env:UV_PYTHON = (Get-Command python).Source   # or an absolute python.exe path
$env:UV_NO_MANAGED_PYTHON = '1'
uv run scripts\mlt_tools.py summary projects\x.mlt
```

For one command, `uv run --python C:\path\to\python.exe ...` is equivalent. The scripts are stdlib-only, so
using an existing compatible Python does not skip dependency installation.

## Git rejects the checkpoint repo as dubious ownership in an agent runner

Some agent harnesses run approved external commands under a service account. Git then sees a repository owned
by another account and rejects it as a dubious ownership case, even though `user.email` exists in the repo.
`checkpoint.ps1` passes `safe.directory` only for the explicitly selected `-Lab` and only for each Git command;
it does not modify global Git configuration. It also reports the original Git error separately from a genuinely
missing identity. If invoking Git manually in the same runner, use `git -c safe.directory=C:\exact\lab ...`
rather than adding a broad or global wildcard.

## status says HUMAN-MODIFIED when nobody touched it

`.state` records a hash of what the agent last wrote. Switching Git branches changes the file without going through the scripts, so the hash no longer matches. Harmless — run `summary` and carry on.

## PowerShell 5.1 gotchas

- `&&` and `||` do not exist. Use `;` or `if ($?) { … }`.
- Double quotes inside a here-string passed to `git commit -m` break argument parsing. Keep commit messages free of `"`.
- `R` is an alias for `Invoke-History`; never name a helper function `R`.
- Redirecting a native command's stderr with `2>&1` wraps lines in error records and can make a successful command look failed.
- `Set-Content` defaults to ANSI; pass `-Encoding utf8` for anything another tool will read. For XML written without a BOM, use `[IO.File]::WriteAllText($p, $text, (New-Object Text.UTF8Encoding $false))`.
- Sleep-polling loops are blocked in some agent harnesses; poll with a check command instead.

## Shotcut is open and I need to edit

Do not. Shotcut writes the entire project on save, so your edit vanishes at their next Ctrl+S. Ask them to save and close. Reading and committing the file while Shotcut is open is safe — only writing is not.

