# Script-writing prompt (solo explainer)

Input: the research notes below. Output: one JSON object matching the schema,
nothing else.

## Rules

- **Grounding.** Every fact, number and quote must appear in the notes. If a
  figure is not in the notes, do not state it — describe the thing instead.
  No outside knowledge, no invented quotes, no "studies show".
- **Length.** Measured pace at `rate: +0%` with Andrew is 163 wpm.
  1,650 words ≈ 10 min, 2,400 words ≈ 15 min. Aim for 1,700–2,100.
- **Paragraphs, not lines.** 100–200 words each, 10–14 of them. Each paragraph
  must survive being heard without the one before it — no "as I said".
- **Structure.** Open on the concrete thing that prompted the episode (a date, a
  number, an event), not on "today we're going to talk about". Then one idea per
  paragraph, in the order a curious listener would need them. Close on the
  consequence or the honest limitation — never a recap.
- **Spoken register.** Short sentences mixed with one long one. Say numbers the
  way a person says them ("sixteen point zero nine four billion miles"). Name
  the source out loud when a claim is load-bearing ("NASA's own status page
  lists"). No markdown, no stage directions, no bullet points.
- **Second person sparingly.** "Here is the scale of it" is fine; a paragraph of
  rhetorical questions is not.
- **No padding.** If the notes only support 9 minutes, write 9 minutes and say
  so. Do not invent connective tissue to hit a word count.

## Schema

```json
{"title": "...",
 "host": {"voice": "en-US-AndrewMultilingualNeural", "rate": "+0%", "pitch": "-2Hz"},
 "say": {"2026": "twenty twenty-six", "RTG": "R T G"},
 "paragraphs": [{"text": "..."}, {"text": "...", "beat": true}]}
```

The `say` map should carry every year, initialism and foreign or catalogue name.

## Notes

<paste notes/&lt;slug&gt;.md here>
