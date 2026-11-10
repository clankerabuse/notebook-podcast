#!/usr/bin/env python3
"""Render a podcast episode from a script JSON, in either of two shapes.

1. Solo explainer (default for research-to-audio work) — one voice, paragraph
   granularity so prosody carries across sentences inside a paragraph:

   {
     "title": "Episode title",
     "host": {"voice": "en-US-AndrewMultilingualNeural", "rate": "+0%", "pitch": "-2Hz"},
     "paragraphs": [
       {"text": "Opening paragraph..."},
       {"text": "New section opens here.", "beat": true},
       {"text": "Closing thought.", "pause": 1.1}
     ],
     "say": {"Voyager 1": "Voyager One"}
   }

   `pause` = seconds of silence after that paragraph (default 0.8).
   `beat` = section break before it (default 1.3 s).

2. Two-host dialogue — turn granularity, gaps per speaker change:

   {"title": ..., "hosts": {"A": {...}, "B": {...}},
    "lines": [{"who": "A", "text": "..."}, {"who": "B", "text": "..."}]}

Pipeline: edge-tts (free Microsoft neural voices) -> raw PCM concat with silence
-> loudness-normalised MP3 with ID3 tags.
"""
import argparse
import concurrent.futures
import json
import os
import re
import shutil
import subprocess
import sys
import wave

RATE = 24000
CHANNELS = 1
SAMPWIDTH = 2

GAP_SWITCH = 0.34      # dialogue: different speaker
GAP_SAME = 0.16        # dialogue: same speaker continuing
GAP_PARA = 0.80        # solo: paragraph to paragraph
GAP_BEAT = 1.30        # solo: section break
GAP_TURN_BEAT = 0.55   # dialogue: explicit beat marker


def sh(cmd, **kw):
    return subprocess.run(cmd, check=True, capture_output=True, text=True, **kw)


def norm_pct(v, default):
    """edge-tts requires an explicit sign: '+0%', '-2Hz' — '0%' is rejected."""
    v = (v or default).strip()
    return v if v[0] in "+-" else "+" + v


def synth(idx, unit, host, say, workdir):
    text = unit["text"]
    for k, v in say.items():
        text = re.sub(re.escape(k), v, text, flags=re.IGNORECASE)
    mp3 = os.path.join(workdir, f"{idx:04d}.mp3")
    cmd = [
        "edge-tts",
        "--voice", host["voice"],
        "--rate", norm_pct(host.get("rate"), "+0%"),
        "--pitch", norm_pct(host.get("pitch"), "+0Hz"),
        "--text", text,
        "--write-media", mp3,
    ]
    last = None
    for attempt in range(4):
        try:
            sh(cmd)
            if os.path.getsize(mp3) > 0:
                return mp3
        except subprocess.CalledProcessError as e:
            last = e.stderr or str(e)
            # edge-tts occasionally 403s / drops the websocket; just retry
    raise RuntimeError(f"tts failed for line {idx}: {last}")


def pcm(mp3, workdir):
    raw = os.path.join(workdir, os.path.basename(mp3) + ".pcm")
    sh(["ffmpeg", "-y", "-loglevel", "error", "-i", mp3,
        "-ar", str(RATE), "-ac", str(CHANNELS), "-f", "s16le", raw])
    with open(raw, "rb") as f:
        return f.read()


def load(spec, default_gap):
    """Normalise either schema into (hosts, units, solo, gap_after(i))."""
    say = spec.get("say", {})
    if "paragraphs" in spec:
        hosts = {"A": spec.get("host", {"voice": "en-US-AndrewMultilingualNeural"})}
        units = [{"who": "A", "text": p["text"],
                  "pause": p.get("pause"), "beat": p.get("beat")}
                 for p in spec["paragraphs"]]
        solo = True
    else:
        hosts = spec["hosts"]
        units = spec["lines"]
        solo = False
        for u in units:
            if u["who"] not in hosts:
                sys.exit(f"unknown host {u['who']!r}; define it in hosts")

    def gap_after(i):
        if i >= len(units) - 1:
            return 0.0
        nxt, cur = units[i + 1], units[i]
        if solo:
            if nxt.get("beat"):
                return GAP_BEAT
            if cur.get("pause") is not None:
                return float(cur["pause"])
            return GAP_PARA
        if nxt.get("beat"):
            return GAP_TURN_BEAT
        return default_gap if nxt["who"] != cur["who"] else GAP_SAME

    return hosts, units, solo, gap_after, say


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("script")
    ap.add_argument("output")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--gap", type=float, default=GAP_SWITCH,
                    help="dialogue only: seconds between speaker changes")
    ap.add_argument("--title", default=None)
    args = ap.parse_args()

    with open(args.script) as f:
        spec = json.load(f)
    hosts, units, solo, gap_after, say = load(spec, args.gap)
    title = args.title or spec.get("title", "Episode")
    words = sum(len(u["text"].split()) for u in units)

    workdir = os.path.join(os.path.dirname(os.path.abspath(args.output)),
                           ".render-" + re.sub(r"\W+", "-", title.lower())[:40])
    os.makedirs(workdir, exist_ok=True)

    print(f"{len(units)} {'paragraphs' if solo else 'turns'}, {words} words, "
          f"{args.workers} workers", flush=True)
    done = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {
            ex.submit(synth, i, u, hosts[u["who"]], say, workdir): i
            for i, u in enumerate(units)
        }
        for n, fut in enumerate(concurrent.futures.as_completed(futs), 1):
            i = futs[fut]
            done[i] = fut.result()
            if n % 10 == 0 or n == len(units):
                print(f"  {n}/{len(units)}", flush=True)

    wav_tmp = os.path.join(workdir, "episode.wav")
    silence = {}
    with wave.open(wav_tmp, "wb") as w:
        w.setnchannels(CHANNELS)
        w.setsampwidth(SAMPWIDTH)
        w.setframerate(RATE)
        for i in range(len(units)):
            w.writeframes(pcm(done[i], workdir))
            gap = gap_after(i)
            if gap <= 0:
                continue
            if gap not in silence:
                silence[gap] = b"\x00" * (int(RATE * gap) * SAMPWIDTH * CHANNELS)
            w.writeframes(silence[gap])
    frames = wave.open(wav_tmp, "rb").getnframes()

    sh(["ffmpeg", "-y", "-loglevel", "error", "-i", wav_tmp,
        "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
        "-ac", str(CHANNELS), "-c:a", "libmp3lame", "-b:a", "96k",
        "-metadata", f"title={title}",
        "-metadata", "album=Notebook Podcast",
        "-metadata", "artist=in-house",
        args.output])

    dur = frames / RATE
    size = os.path.getsize(args.output) / 1e6
    wpm = words / (dur / 60) if dur else 0
    print(f"done: {args.output}\n  {int(dur//60)}m{int(dur%60):02d}s, {size:.1f} MB, "
          f"{words} words, {wpm:.0f} wpm, {len(units)} {'paragraphs' if solo else 'turns'}")
    shutil.rmtree(workdir, ignore_errors=True)


if __name__ == "__main__":
    main()
