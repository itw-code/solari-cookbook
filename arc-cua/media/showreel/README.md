# Solari race showreel

A 15-second motion piece of `docs/BENCHMARK_VS_SOLARI_MCP.md`'s head-to-head. It compares Claude Opus 5.5 + Solari MCP against Gemini 3.8 Flash + ARC, both on Solari browsers, across 8 tasks. Output: `artifacts/solari-race-showreel.mp4`.

- `reel.html`: a 1920×1080 canvas where every frame is a pure function of time (`window.render(t)`).
- `render.py`: renders frames with headless Chromium. `python render.py keys` makes a contact sheet; `python render.py all` renders all 450 frames at 30 fps.
- `soundtrack.py`: synthesizes a 150 BPM soundtrack locked to the scene cuts (numpy, no samples).

Encode:

    ffmpeg -framerate 30 -i frames/f%04d.png -i soundtrack.wav -c:v libx264 -crf 18 -pix_fmt yuv420p -c:a aac -b:a 192k -shortest -movflags +faststart out.mp4
