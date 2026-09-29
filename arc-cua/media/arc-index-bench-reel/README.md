# ARC Index benchmark reel

A 15-second piece on one number: **wrong values accepted**. That is a field that passes the grounding check but is not the right value, so it would be typed into the portal. A rejected field is left blank for a person, which is safe. Output: `artifacts/arc-index-benchmark-showreel.mp4`. The companion reel, `media/arc-index-reel/`, follows one value from the letter to the receipt.

Every figure on screen is measured (`docs/ARC_INDEX_PLAN.md` §9.3, §10.5, §10.7):

- **The dangerous case.** The page-2 table of the two-denied-lines letter (`synthetic_denial_letter_two_denied.pdf`). A model told to "give the one that fits best" picks CPT 99214. The presence check and the evidence check both accept it. The uniqueness rule rejects it with `2 rows fit: 93000 / 99214`, the error the bridge actually returns. Table rows are shortened on screen; the PDF wraps rows 2 and 3 over two lines.
- **Gemini 3.8 Flash, n=20, 5 letters:** presence 77 → evidence 0. That is 40 + 37 in the block-index columns, with and without descriptions (§10.5).
- **Claude Sonnet 5.5, two-denied letter, forced pick, n=8:** presence 16, evidence 16, + uniqueness rule 0. The same 8 answers are graded by all three checks (`scripts/eval_offline.py`, `artifacts/benchmarks/offline/sonnet-5.5_grades.json`). No field with a right answer was lost: 8/8 on every one.
- **Solari:** fill + submit 20.5 s → 6.1 s (−70.2%), with 386 ms for the batched fill of 7 fields (§9.3).

Caveats: the Sonnet runs were Claude Code subagents, not bare API calls, so they give no latency or cost figures. The letters are synthetic. The rows are found with a regex in the schema.

- `bench.html`: a 1920×1080 canvas, `window.render(t)`, with 6-sample motion blur. Same palette, type and helpers as the companion reel. `?t=5.5` freezes a frame.
- `render.py`: `python render.py keys [out] [t1,…]` for keyframes, `python render.py all [out]` for 900 frames at 60 fps.
- `soundtrack.py`: the companion reel's voices and 120 BPM bed, with foley on this timeline.

Encode (two-pass, 10 Mb/s):

    ffmpeg -y -framerate 60 -i frames/f%04d.png -c:v libx264 -b:v 10M -pass 1 -preset slow -pix_fmt yuv420p -an -f mp4 NUL
    ffmpeg -framerate 60 -i frames/f%04d.png -i soundtrack.wav -c:v libx264 -b:v 10M -pass 2 -preset slow -pix_fmt yuv420p -c:a aac -b:a 192k -shortest -movflags +faststart arc-index-benchmark-showreel.mp4
