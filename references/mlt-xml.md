# Shotcut MLT XML structures

What is actually confirmed about the XML Shotcut reads and writes, and how confident each item is.

- [Confidence levels](#confidence-levels)
- [Document skeleton](#document-skeleton)
- [Verified structures](#verified-structures)
- [Video clips](#video-clips)
- [Tracks and the compositing transitions](#tracks-and-the-compositing-transitions)
- [Text and title clips](#text-and-title-clips)
- [Clip filters](#clip-filters)
- [Keyframes and time](#keyframes-and-time)
- [Not yet verified](#not-yet-verified)
- [How to verify a new structure](#how-to-verify-a-new-structure)

Checked against **Shotcut 26.8.1 / MLT 7.41.0** on Windows. A different Shotcut version may write things differently — re-check before trusting the table.

## Confidence levels

| Level | Means |
|---|---|
| **documented** | Stated in the [Shotcut MLT XML annotations](https://www.shotcut.org/notes/mltxml-annotations/), [MLT XML docs](https://www.mltframework.org/docs/mltxml/), [property animation](https://www.mltframework.org/docs/propertyanimation/), or Shotcut's own bundled QML filter definitions |
| **observed** | Seen in a file Shotcut itself saved — the strongest practical evidence, because it round-trips through the UI |
| **empirical** | Found only by testing and looking at rendered frames; the docs are silent |

Prefer moving items up this ladder over time. An empirical item is the one most likely to be wrong.

## Document skeleton

```xml
<?xml version="1.0" standalone="no"?>
<mlt LC_NUMERIC="C" version="7.41.0" title="Shotcut version 26.8.1" producer="main_bin">
  <profile description="1920x1080 30.00 fps" width="1920" height="1080" progressive="1"
           sample_aspect_num="1" sample_aspect_den="1" display_aspect_num="16" display_aspect_den="9"
           frame_rate_num="30000" frame_rate_den="1001" colorspace="709"/>
  <playlist id="main_bin"><property name="xml_retain">1</property></playlist>
  <producer id="black">…</producer>
  <playlist id="background"><entry producer="black" …/></playlist>
  <chain id="chain0">…</chain>            <!-- media clips -->
  <producer id="producer0">…</producer>   <!-- text/color clips -->
  <playlist id="playlist0">…</playlist>   <!-- V1 -->
  <playlist id="playlist1">…</playlist>   <!-- V2 … -->
  <tractor id="tractor0">…</tractor>      <!-- tracks + transitions, last element -->
</mlt>
```

Order matters: Shotcut expects `main_bin` before the final tractor, and `background` (a black `color` producer) as the tractor's **first** track.

## Verified structures

| Structure | Level |
|---|---|
| `main_bin` playlist before the last tractor; `background` playlist with black `color` producer as first track | documented |
| Tractor `shotcut=1`; track playlists carry `shotcut:video` / `shotcut:audio` and `shotcut:name` | documented |
| `<chain>` rather than `<producer>` for `avformat` media, since Shotcut 21.05 | documented |
| `shotcut:caption`, `shotcut:hash`, `shotcut:filter`, `shotcut:animIn` / `animOut` | documented |
| Keyframes `pos=value;…`; pos as frame number, clock or timecode; `=` linear, `~=` smooth, `\|=` discrete; negative pos counts from the end | documented |
| Saturation / contrast / size-position filter property names | documented (Shotcut's bundled QML) |
| `in` / `out` / `length` written as `HH:MM:SS.mmm` timecodes | observed |
| Text clip = transparent `color` producer + `dynamictext` filter | observed |
| Bottom video track's blend transition has `disable=1` | observed |
| Clip filters live **inside** `<chain>`/`<producer>`, not inside `<entry>` | observed |
| Root attribute `<mlt producer="main_bin">` | observed |
| Every overlay track's blend uses **`a_track=1`** | empirical |
| `dynamictext` `opacity` accepts frame-number keyframes and genuinely animates | observed + rendered |

## Video clips

```xml
<chain id="chain0" out="00:04:08.742">
  <property name="length">7456</property>
  <property name="eof">pause</property>
  <property name="resource">C:/Users/you/project/media/generated/work.mp4</property>
  <property name="mlt_service">avformat-novalidate</property>
  <property name="seekable">1</property>
  <property name="audio_index">1</property>
  <property name="video_index">0</property>
  <property name="mute_on_pause">0</property>
  <property name="shotcut:caption">work.mp4</property>
</chain>
```

`resource` is an absolute path with forward slashes. Moving media breaks the link, so keep paths stable or rewrite them deliberately. `audio_index` / `video_index` come from ffprobe's stream indices; use `-1` when a stream is absent. Shotcut adds `meta.*`, `shotcut:hash`, `vstream` and `astream` on its first save — you do not need to write them.

A clip appears on a track as an `<entry>` whose `in`/`out` trim it:

```xml
<playlist id="playlist0">
  <property name="shotcut:video">1</property>
  <property name="shotcut:name">V1</property>
  <entry producer="chain0" in="00:00:00.500" out="00:00:03.000"/>
  <blank length="00:00:01.001"/>
  <entry producer="chain1" in="00:00:00.000" out="00:00:04.967"/>
</playlist>
```

One producer can be referenced by many entries — that is how a single source becomes several timeline segments. `<blank>` is a gap.

## Tracks and the compositing transitions

This is the part that bites. Each video track above the background needs **two** transitions in the tractor: a `mix` for audio and a `frei0r.cairoblend` for video.

```xml
<tractor id="tractor0" title="Shotcut version 26.8.1" in="00:00:00.000" out="00:00:29.963">
  <property name="shotcut">1</property>
  <property name="shotcut:projectAudioChannels">2</property>
  <property name="shotcut:projectFolder">0</property>
  <track producer="background"/>
  <track producer="playlist0"/>   <!-- V1, track index 1 -->
  <track producer="playlist1"/>   <!-- V2, track index 2 -->

  <transition id="transition0">   <!-- audio mix for V1 -->
    <property name="a_track">0</property>
    <property name="b_track">1</property>
    <property name="mlt_service">mix</property>
    <property name="always_active">1</property>
    <property name="sum">1</property>
  </transition>
  <transition id="transition1">   <!-- video blend for V1: DISABLED -->
    <property name="a_track">0</property>
    <property name="b_track">1</property>
    <property name="version">0.1</property>
    <property name="mlt_service">frei0r.cairoblend</property>
    <property name="threads">0</property>
    <property name="disable">1</property>
  </transition>

  <transition id="transition2">   <!-- audio mix for V2 -->
    <property name="a_track">0</property>
    <property name="b_track">2</property>
    <property name="mlt_service">mix</property>
    <property name="always_active">1</property>
    <property name="sum">1</property>
  </transition>
  <transition id="transition3">   <!-- video blend for V2: a_track is 1, not 2 -->
    <property name="a_track">1</property>
    <property name="b_track">2</property>
    <property name="version">0.1</property>
    <property name="mlt_service">frei0r.cairoblend</property>
    <property name="threads">0</property>
    <property name="disable">0</property>
  </transition>
</tractor>
```

Two rules earned by rendering black frames:

- **The bottom video track's blend is disabled** (`disable=1`). Leave it enabled and adding any overlay track blacks out the video entirely.
- **Every overlay blend uses `a_track=1`**, whatever the track index. `a_track = n-1` (chaining each track onto the one below) renders black; `a_track=0` composites against the background and loses the layer beneath. Add more overlay tracks by incrementing `b_track` only.

`mix` transitions always use `a_track=0`.

## Text and title clips

Shotcut has no "text clip" type. A title is a **transparent color producer carrying a `dynamictext` filter**:

```xml
<producer id="producer0" in="00:00:00.000" out="00:00:02.970">
  <property name="length">00:00:03.003</property>
  <property name="eof">pause</property>
  <property name="resource">#00000000</property>       <!-- #AARRGGBB; opaque colour for a title card -->
  <property name="aspect_ratio">1</property>
  <property name="mlt_service">color</property>
  <property name="mlt_image_format">rgba</property>
  <property name="shotcut:caption">transparent</property>
  <property name="shotcut:detail">transparent</property>
  <property name="seekable">1</property>
  <filter id="filter0" out="00:00:02.970">
    <property name="argument">Hello</property>          <!-- \n for a second line -->
    <property name="geometry">0 540 1920 180 1</property>  <!-- x y w h opacity, or keyframed -->
    <property name="family">Noto Sans JP</property>
    <property name="size">80</property>
    <property name="weight">700</property>
    <property name="style">normal</property>
    <property name="fgcolour">#ffffffff</property>
    <property name="bgcolour">#00000000</property>
    <property name="olcolour">#aa000000</property>
    <property name="pad">0</property>
    <property name="halign">center</property>
    <property name="valign">top</property>
    <property name="outline">3</property>
    <property name="underline">0</property>
    <property name="strikethrough">0</property>
    <property name="opacity">1.0</property>
    <property name="mlt_service">dynamictext</property>
    <property name="shotcut:filter">dynamicText</property>
    <property name="shotcut:usePointSize">1</property>
    <property name="shotcut:pointSize">60</property>
  </filter>
</producer>
```

Animate by keyframing `geometry` (movement) and `opacity` (fade). Put the clip on an overlay track; overlapping text needs separate tracks.

Non-Latin text needs a font that has the glyphs — check it is installed before using it (`Noto Sans JP`, `Yu Gothic`, `BIZ UDGothic` for Japanese). A missing font renders as boxes or nothing.

**Emoji are monochrome.** melt, FFmpeg's drawtext and Windows' own WPF renderer all draw the outline layer of Segoe UI Emoji, not its colour layers. Tint one with `fgcolour` and give each emoji its own clip — mixing emoji into a sentence garbles the surrounding glyphs. True colour needs PNG images (Noto Emoji, Twemoji) composited as image producers.

## Clip filters

Filters belong **inside** the `<chain>` or `<producer>`, after its properties. A `<filter>` written inside an `<entry>` looks valid, renders, and is then silently dropped the next time Shotcut saves. Because filters attach to the producer rather than the timeline entry, giving one entry its own grade means giving it its own copy of the chain.

Property names come from Shotcut's bundled QML (`share\shotcut\qml\filters\<name>\meta*.qml`) — the reliable place to look one up:

```xml
<!-- Saturation. Shotcut's UI percentage = value * 800, so 0.125 is 100% -->
<filter id="filter1" in="…" out="…">
  <property name="0">0.175</property>
  <property name="mlt_service">frei0r.saturat0r</property>
</filter>

<!-- Contrast. UI level v in 0..1; v = 0.5 is neutral -->
<filter id="filter2" in="…" out="…">
  <property name="gamma_r">0.84</property>   <!-- 2*(1-v) on r,g,b -->
  <property name="gamma_g">0.84</property>
  <property name="gamma_b">0.84</property>
  <property name="gain_r">1.16</property>    <!-- 2*v on r,g,b -->
  <property name="gain_g">1.16</property>
  <property name="gain_b">1.16</property>
  <property name="mlt_service">lift_gamma_gain</property>
  <property name="shotcut:filter">contrast</property>
</filter>

<!-- Size, Position & Rotate — a slow zoom -->
<filter id="filter3" in="…" out="…">
  <property name="transition.rect">0=0%/0%:100%x100%;209=-6%/-6%:112%x112%</property>
  <property name="transition.fill">0</property>
  <property name="transition.distort">0</property>
  <property name="transition.valign">middle</property>
  <property name="transition.halign">center</property>
  <property name="transition.threads">0</property>
  <property name="transition.fix_rotate_x">0</property>
  <property name="mlt_service">affine</property>
  <property name="shotcut:filter">affineSizePosition</property>
</filter>
```

`shotcut:filter` is what lets the Shotcut UI show the right editor panel; without it the filter still renders but appears as a raw service.

## Keyframes and time

Positions are `pos=value` pairs separated by `;`. `pos` may be a frame number, a clock string or a timecode; Shotcut normalises to timecodes when the person edits that filter, which is a formatting change rather than a real edit.

| Operator | Interpolation |
|---|---|
| `=` | linear |
| `~=` | smooth spline |
| `\|=` | discrete (hold) |

A negative position counts back from the end (`-1` is the last frame). Rectangles take `x/y:wxh`, in pixels or percent: `0=0%/0%:100%x100%;-1=-6%/-6%:112%x112%`.

`in`, `out` and `length` are written as `HH:MM:SS.mmm`. `out` is **inclusive**, so a clip of `n` frames ends at frame `n-1` — an off-by-one here shows up as a one-frame gap or overlap. At 30000/1001 fps, timecodes land on values like `00:00:07.007`; that is correct rounding, not a bug.

Keyframe positions are relative to the **producer**, not the timeline. Trimming an `<entry>` therefore does not retime the filters on its producer: a shortened text clip keeps keyframes describing its original length, and its fade-out lands past the visible end, so it pops off instead of fading. Give a trimmed text clip its own copy of the producer with the animation pulled back (`mlt_cut.py` does this).

When checking an animation by rendering, sample the fade window rather than the middle. A frame taken during the hold looks identical whether the fade is correct or broken.

## Not yet verified

Check the docs and a Shotcut-saved file before writing any of these: audio fades and crossfades, video transitions between clips, speed and reverse, markers, proxies, still-image clips, audio-only tracks, chroma key, motion tracking.

Shotcut also bundles `whisper-cli.exe` next to `shotcut.exe`, which suggests local speech-to-text for subtitles is possible. Untested here.

## How to verify a new structure

1. Read the docs above, and Shotcut's QML for the filter's exact property names.
2. Do the change once **in the Shotcut GUI**, save, and `git diff` — copy what Shotcut wrote. This is worth more than any documentation, because it is guaranteed to round-trip.
3. Reproduce it from your script, then **render a frame and look at it**.
4. Open the result in Shotcut, confirm the filter appears in the Filters panel, save, and diff again — if your version survives unchanged, it is genuinely correct.
5. Add it to the table above with its confidence level.
