"""Render reel.html frames with headless Chromium: keyframes (contact sheet) or all frames.

Usage: python render.py keys|all [variant] [out_dir]   (variant: a key of VARIANTS in reel.html)
"""
import base64
import pathlib
import sys

from playwright.sync_api import sync_playwright

HERE = pathlib.Path(__file__).parent
FPS = 30


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "keys"
    variant = sys.argv[2] if len(sys.argv) > 2 else "opus"
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 1920, "height": 1080})
        pg.goto((HERE / "reel.html").resolve().as_uri() + f"?v={variant}", wait_until="networkidle")
        pg.evaluate("window.ready")
        if mode == "keys":
            times = [0.9, 1.35, 2.5, 3.18, 4.6, 6.6, 8.25, 9.6, 10.5, 11.9, 12.8, 14.4]
            out = HERE / "keys"
        else:
            times = [i / FPS for i in range(int(15 * FPS))]
            out = HERE / "frames"
        out = pathlib.Path(sys.argv[3]) if len(sys.argv) > 3 else out
        out.mkdir(parents=True, exist_ok=True)
        for i, t in enumerate(times):
            data = pg.evaluate("(t) => { window.render(t); return document.getElementById('c').toDataURL('image/png'); }", t)
            (out / f"f{i:04d}.png").write_bytes(base64.b64decode(data.split(",", 1)[1]))
        b.close()
    print(f"rendered {len(times)} frames ({variant}) to {out}")


if __name__ == "__main__":
    main()
