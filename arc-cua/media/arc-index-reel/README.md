# ARC Index showreel

A 15-second motion piece of `docs/ARC_INDEX_PLAN.md`. One red thread carries a cited value (CPT 99214) from a 50-page denial letter, through the PageIndex tree and into a portal form via `[#N]` reflexes. From there it passes through a SimHash state check and ends on a printed receipt. Output: `artifacts/arc-index-showreel.mp4`.

The figures on screen are measured, from the live Solari run of 2026-09-29 (`artifacts/benchmarks/arc_index_live_solari_pageindex_20260929-111127.json`, `docs/ARC_INDEX_PLAN.md` §9–10):

- 4-page synthetic denial letter; PageIndex (local) indexes it in 9.8 s.
- Citations are page-level (`<cite page=2/>`). The receipt cites CPT 99214 on the page-2 denied row and CO-16 on page 3.
- The fields go into the form in one batched call, 386 ms on Solari. The submit click takes 2,289 ms. One `act` per field is ≈ 2 s.
- Fill + submit: 20.5 s one `act` per field → 6.1 s batched (−70.2%).
- SimHash: 10 bits changed. Confirmation code APL-MUM5SGU2-2835 matched.
- End-card tally: wrong values accepted on the two-denied-lines decoy letter, block index, 20 runs. The old presence check accepted 40 (CPT 20 + billed amount 20); the evidence check accepts 0. In those runs the model answered `AMBIGUOUS` for both fields. Since plan §10.7 a rule also rejects a model that picks one of the two rows (16 → 0 wrong with Sonnet 5.5, n=8). The caption reads "wrong values let through: 40 → 0 · forced pick: 0"; the second half is that result. The numbers get their own reel in `media/arc-index-bench-reel/`. PageIndex was already at 0 on this letter, so the tally shows the block index.

An earlier cut showed projected figures (50 pages, $0.001/page, 2.31 ms/step, $0.78 → $0.0315, −95.9%) that no run has measured.

The portal is a stand-in form, not a real payer site. The Denial reason field is drawn as a dropdown. `fill_many` does set `<select>` elements, but the live portal used a text field.

- `reel.html`: a 1920×1080 canvas where every frame is a pure function of time (`window.render(t)`), with 6-sample sub-frame motion blur. Open it directly to preview. It autoplays and loops; Space pauses, R restarts, `?t=6.2` freezes a frame.
- `render.py`: renders frames with headless Chromium. `python render.py keys [out] [t1,t2,…]` renders keyframes for a contact sheet; `python render.py all [out]` renders all 900 frames at 60 fps.
- `soundtrack.py`: synthesizes a 120 BPM bed plus foley locked to the reel's timeline (numpy, no samples). `python soundtrack.py [out.wav]`.

Encode:

    ffmpeg -framerate 60 -i frames/f%04d.png -i soundtrack.wav -c:v libx264 -crf 16 -preset slow -pix_fmt yuv420p -c:a aac -b:a 192k -shortest -movflags +faststart arc-index-showreel.mp4
