"""Render econ.html with headless Chromium: keyframes for a contact sheet, or every frame.

Usage: python render.py keys [out_dir] [t1,t2,...]   |   python render.py all [out_dir]
"""
import base64
import pathlib
import sys

from playwright.sync_api import sync_playwright

HERE = pathlib.Path(__file__).parent
FPS = 60
DUR = 15
KEYS = [1.6, 3.6, 4.6, 6.8, 8.6, 9.6, 10.6, 12.0, 12.7, 14.6]


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "keys"
    out = pathlib.Path(sys.argv[2]) if len(sys.argv) > 2 else HERE / ("keys" if mode == "keys" else "frames")
    if mode == "keys":
        times = [float(x) for x in sys.argv[3].split(",")] if len(sys.argv) > 3 else KEYS
    else:
        times = [i / FPS for i in range(DUR * FPS)]
    out.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 1920, "height": 1080})
        pg.goto((HERE / "econ.html").resolve().as_uri() + "?clean=1", wait_until="networkidle")
        pg.evaluate("window.ready")
        for i, t in enumerate(times):
            data = pg.evaluate("(t) => { window.render(t); return document.getElementById('c').toDataURL('image/png'); }", t)
            (out / f"f{i:04d}.png").write_bytes(base64.b64decode(data.split(",", 1)[1]))
            if mode == "all" and i % 60 == 0:
                print(f"  {i}/{len(times)}", flush=True)
        b.close()
    print(f"rendered {len(times)} frames to {out}")


if __name__ == "__main__":
    main()
