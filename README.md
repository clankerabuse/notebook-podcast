# notebook-podcast

Topic in, 10–15 minute audio explainer out. Research → script → mp3, with free
speech (Edge TTS, no key), so an episode costs a few cents of writing at most.

## Three stages, kept separate

1. **Research** — save the extracted text with its source URLs to
   `notes/<slug>.md`. That file is the only grounding the script may use.
2. **Script** — one prompt ([script-prompt.md](script-prompt.md)) →
   `episodes/<slug>.json`. 1,650 words ≈ 10 minutes, 2,400 ≈ 15 minutes at the
   measured 163 wpm.
3. **Render** — one TTS request per paragraph so prosody carries across
   sentences, then concat and `loudnorm` to podcast level.

```bash
python render.py episodes/<slug>.json episodes/<slug>.mp3
```

## Feed

`station.py` publishes the rendered folder as an RSS feed a phone can subscribe
to.

```bash
python station.py build    # episodes/*.json + *.mp3 -> feed.xml
python station.py serve    # http://<tailnet-addr>:8765/feed.xml
```

`build` takes the title from the script, the duration from ffprobe, the
enclosure length from the file, and `pubDate` from the mp3 mtime. Show notes
are the URLs under `# Sources` in `notes/<slug>.md`, or the URLs in its opening
lines when that heading is absent. The guid is the slug, so a changing tailnet
address does not make clients re-download the archive. A missing or unprobeable
mp3 is skipped with a warning and a non-zero exit. `feed.xml` is generated and
gitignored.

Enclosure URLs use this machine's tailnet address by default (`--base-url` and
`--host` override that). The host firewall drops inbound traffic, so allow the
port on the tailnet interface only:

```bash
sudo ufw allow in on tailscale0 to any port 8765 proto tcp
```

## Notes

The default format is a **solo explainer**: one narrator, paragraph granularity,
no banter to get wrong. A two-host dialogue schema exists in `render.py` but is
the harder thing to make sound good.

Voices: `edge-tts --list-voices` lists 300+; the default is
`en-US-AndrewMultilingualNeural`. `rate` and `pitch` need an explicit sign.

`episodes/*` is gitignored so audio never lands in history — the single tracked
exception is the `one-light-day` reference render. Keep `notes/<slug>.md` next
to the mp3: audio is a bad medium for citations.
