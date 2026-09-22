# shotcut-mlt

An agent skill for editing video by writing **Shotcut `.mlt` project files** instead of rendering finished videos — so you can open the result in Shotcut, change it by hand, and have the agent carry on from *your* version.

Works with Claude Code, Codex, Cursor and anything else that reads a Markdown instruction file — see [Install](#install). Developed and tested on Windows. No cloud APIs, no MCP server, no WSL. FFmpeg does the media work, Shotcut is the GUI timeline, `.mlt` is the shared artifact, Git is the history.

```
you describe an edit
  → agent inspects media (ffprobe) and edits the .mlt
  → validates, renders a preview frame, Git checkpoint
  → you open it in Shotcut, refine by hand, Ctrl+S, close
  → Git checkpoint
  → agent reads your diff and continues from your version
```

## Why

Most agent video tooling renders an MP4. You can watch it, but you cannot change it, and the next request re-renders from scratch — your adjustments are gone. Keeping the project file as the artifact means the timeline stays editable, your manual work survives, and every handoff between you and the agent is a Git commit you can return to.

## Install

The instructions live in two equivalent entry points — [`SKILL.md`](SKILL.md) (Claude's convention, with
triggering frontmatter) and [`AGENTS.md`](AGENTS.md) (the cross-agent convention Codex and others look for).
Both point at the same `references/` and `scripts/`, so any agent that can read a Markdown file and run a
shell command can use this.

**Claude Code / Claude Desktop** — clone into the skills directory, keeping the folder name `shotcut-mlt` so
it matches the `name:` in the frontmatter:

```bash
git clone https://github.com/cmmo/shotcut-mlt-skill ~/.claude/skills/shotcut-mlt
```

On Windows that is `C:\Users\<your-username>\.claude\skills\shotcut-mlt`.

**Codex** — clone anywhere and point your `AGENTS.md` at it, or clone into the project you are editing:

```bash
git clone https://github.com/cmmo/shotcut-mlt-skill ~/tools/shotcut-mlt
echo "For video/Shotcut .mlt work, follow ~/tools/shotcut-mlt/AGENTS.md" >> ~/.codex/AGENTS.md
```

**Cursor, Windsurf and similar** — clone it and reference `AGENTS.md` from your rules file, or drop the folder
into the project so the agent finds `AGENTS.md` at the root.

**Anything else** — clone it and tell the agent to read `AGENTS.md` first. There is nothing vendor-specific in
the scripts.

## Requirements

| Tool | Why | Windows install |
|---|---|---|
| [FFmpeg](https://ffmpeg.org) (+ ffprobe) | media inspection and transcoding | `winget install --id Gyan.FFmpeg -e` |
| [Shotcut](https://shotcut.org) | the GUI timeline; bundles `melt.exe` for headless rendering | `winget install --id Meltytech.Shotcut -e` |
| [uv](https://docs.astral.sh/uv/) | runs the bundled Python scripts | `winget install --id astral-sh.uv -e` |
| Git | checkpoints at every handoff | `winget install --id Git.Git -e` |

The scripts are standard-library Python only — nothing to `pip install`. Set `MELT_PATH` if melt is somewhere unusual. Linux and macOS are untested; the Python scripts are portable, the PowerShell helper is not.

## What's in it

- **`SKILL.md`** — the workflow, the rules, and the script reference.
- **`references/mlt-xml.md`** — the MLT XML structures Shotcut actually reads and writes, each marked *documented*, *observed* (seen in a file Shotcut saved) or *empirical* (found by testing). This is the part that took the longest to get right.
- **`references/troubleshooting.md`** — symptoms and causes: black renders, vanishing filters, melt hanging, emoji, PowerShell quirks.
- **`assets/project-gitignore`** — a starting `.gitignore` for a project, keeping media and backups out of Git.
- **`scripts/`** — small, inspectable helpers:

| Script | Does |
|---|---|
| `inspect_media.py` | ffprobe → compact JSON summary |
| `mlt_tools.py` | create / append / validate / summarise a project; detect human edits; backup |
| `mlt_text.py` | title cards, subtitles, pop-up words, emoji stickers |
| `mlt_cut.py` | derive a shorter cut, carrying overlays across |
| `mlt_polish.py` | colour grade + slow zoom per clip |
| `render_frame.py` | preview frames via melt |
| `media_manifest.py` | text record of source media (size, duration, hash) |
| `checkpoint.ps1` | validated Git checkpoint at a handoff |

Every editing script backs up first, validates, then writes atomically, and refuses to overwrite a project wholesale.

## Scope, honestly

Verified: text overlays, track compositing, cuts and trims, colour grade and zoom, headless rendering, the human↔agent round trip.

Not yet verified: audio fades and crossfades, transitions between clips, speed changes, markers, proxies, still images, chroma key. `references/mlt-xml.md` says which is which, and how to verify a new structure before trusting it. Checked against Shotcut 26.8.1 / MLT 7.41.0.

Two known limits: emoji render monochrome (melt draws the outline layer, not the colour layers), and Shotcut must be closed while the agent writes to a project, because Shotcut rewrites the whole file on save.

## Contributing

`SKILL.md` is the canonical text and `AGENTS.md` is a deliberately short summary of the same rules — if you change a rule, change both, and keep the depth in `SKILL.md` and `references/` so the two cannot drift far.

The most useful contribution is moving a row in `references/mlt-xml.md` from *empirical* or *not yet verified* to *observed* — make the change in the Shotcut GUI, save, diff the XML, and send what Shotcut actually wrote. Renders that come out black or filters that vanish on save are usually track-wiring or filter-placement problems; both are documented in the troubleshooting file.

## License

MIT — see [LICENSE](LICENSE).
