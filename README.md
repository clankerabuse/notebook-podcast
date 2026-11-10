# notebook-podcast

Topic in, 10–15 minute audio explainer out. Research → single-voice script → mp3.
Speech is free (Edge TTS, no key), so an episode costs a few cents of writing at most.

The default format is a **solo explainer** — one narrator, paragraph granularity, no
banter to get wrong. Two-host dialogue is supported as a second schema, but it is the
harder thing to make sound good and it is not the point of this repo.

## The three stages

1. **Research** — `web_search` / `web_extract`, extracted text saved to
   `notes/<slug>.md` with the source URLs at the top. That file is the grounding
   constraint: the script may only use what is in it. Do not let the writing step
   also research.
2. **Script** — one prompt (see `script-prompt.md`) → `episodes/<slug>.json`.
   1,650 words ≈ 10 minutes, 2,400 ≈ 15 minutes at the measured 163 wpm.
3. **Render** — `python render.py episodes/<slug>.json episodes/<slug>.mp3`
   ~2 minutes of wall clock for a 10-minute episode, 96 kbps mono, ~0.75 MB/min.

## Solo script format (default)

```json
{
  "title": "One Light-Day",
  "host": {"voice": "en-US-AndrewMultilingualNeural", "rate": "+0%", "pitch": "-2Hz"},
  "say": {"2026": "twenty twenty-six", "RTG": "R T G"},
  "paragraphs": [
    {"text": "Opening paragraph, 120–200 words."},
    {"text": "New section opens here.", "beat": true},
    {"text": "Closing thought.", "pause": 1.1}
  ]
}
```

- One TTS request per paragraph, so prosody carries across sentences instead of
  resetting every line. Keep paragraphs 100–200 words; do not hand it 800.
- `pause` = silence after that paragraph in seconds (default 0.8).
- `beat` = section break before it (1.3 s of silence).
- `say` = case-insensitive pronunciation overrides, applied before synthesis.
  Use it for years (2026 → twenty twenty-six), initialisms, and catalogue names.

## Two-host format (optional)

```json
{"title": "...", "hosts": {"A": {"voice": "en-US-AvaMultilingualNeural", "rate": "+7%"},
                            "B": {"voice": "en-US-AndrewMultilingualNeural", "rate": "+0%"}},
 "lines": [{"who": "A", "text": "8–25 words."}, {"who": "B", "text": "...", "beat": true}]}
```

Gaps: 0.34 s between speakers, 0.16 s same speaker, 0.55 s at a `beat`.

## Voices

`edge-tts --list-voices` shows 300+. For a solo explainer the safe picks are
`en-US-AndrewMultilingualNeural` (default), `en-US-BrianMultilingualNeural`,
`en-GB-RyanNeural`, or `en-US-AvaMultilingualNeural` / `en-GB-SoniaNeural`.

`rate` and `pitch` need an explicit sign — `0%` is rejected by edge-tts, so
`render.py` adds `+` when you forget.

## Assembly details that matter

- Decode each clip to raw 24 kHz mono PCM, concat with measured silence, then
  encode once. No concat-demuxer drift, no re-encode per segment.
- `loudnorm=I=-16:TP=-1.5` on the final pass, so the episode sits at podcast
  loudness instead of needing a volume nudge against real shows.
- ID3 title/album/artist, otherwise players show a bare filename.

## Cost

| item | cost |
|---|---|
| speech (Edge TTS) | $0, no key, no account |
| speech (Kokoro 82M local, Apache-2.0) | $0, ~150 MB model, CPU real-time |
| speech (OpenAI tts-1) | $15 / 1M chars ≈ $0.18 per 15 min |
| speech (OpenAI gpt-4o-mini-tts) | low single-digit cents per 15 min |
| writing | a few cents, or $0 marginal on an existing subscription |
| storage | ~0.75 MB per minute at 96 kbps |

## Episodes stay local

`episodes/*` is gitignored so generated audio never lands in history. The single
tracked exception is `one-light-day.{json,mp3}`, the reference render, kept so the
repo has one playable sample.

## Known gaps

- **No citations you can click.** Audio is a bad medium for receipts; keep
  `notes/<slug>.md` next to the mp3 and treat it as the source list.
- **Prosody only spans a paragraph.** Long-form energy has to be carried by word
  choice and section pauses.
- **No overlap or breath** in the dialogue schema — turns are strictly sequential,
  and faking crosstalk by offsetting clips sounds broken about half the time.
- **No interactive mode** (barge-in, live questions). Transcribing the finished
  episode and letting you query that is the cheap adjacent version.
- Edge TTS is an undocumented endpoint: no SLA, can rate-limit. Retries are built
  in (4 per unit); if you ever depend on this, switch the voice to Kokoro.
