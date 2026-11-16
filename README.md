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

## Notes

The default format is a **solo explainer**: one narrator, paragraph granularity,
no banter to get wrong. A two-host dialogue schema exists in `render.py` but is
the harder thing to make sound good.

Voices: `edge-tts --list-voices` lists 300+; the default is
`en-US-AndrewMultilingualNeural`. `rate` and `pitch` need an explicit sign.

`episodes/*` is gitignored so audio never lands in history — the single tracked
exception is the `one-light-day` reference render. Keep `notes/<slug>.md` next
to the mp3: audio is a bad medium for citations.
