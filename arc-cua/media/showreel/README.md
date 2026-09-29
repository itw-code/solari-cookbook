# Solari race showreel

A 15-second motion piece of `docs/BENCHMARK_VS_SOLARI_MCP.md`'s head-to-head. It compares Claude Opus 5.5 + Solari MCP against Gemini 3.8 Flash + ARC, both on Solari browsers, across 8 tasks. Output: `artifacts/solari-race-showreel.mp4`.

A second cut, variant `gemini`, holds the model fixed: Gemini 3.8 Flash + Solari MCP vs Gemini 3.8 Flash + ARC (Part E). Output: `artifacts/gemini-harness-showreel.mp4`. Each variant's copy and numbers live in `VARIANTS` in `reel.html`; pick one with `?v=<name>`.

- `reel.html`: a 1920×1080 canvas where every frame is a pure function of time (`window.render(t)`).
- `render.py`: renders frames with headless Chromium. `python render.py keys|all [variant] [out_dir]`: 12 keyframes for a contact sheet, or all 450 frames at 30 fps.
- `soundtrack.py`: synthesizes a 150 BPM soundtrack locked to the scene cuts (numpy, no samples). `python soundtrack.py [variant] [out.wav]` reads the race times from `reel.html`.

Encode:

    ffmpeg -framerate 30 -i frames/f%04d.png -i soundtrack.wav -c:v libx264 -crf 18 -pix_fmt yuv420p -c:a aac -b:a 192k -shortest -movflags +faststart out.mp4
