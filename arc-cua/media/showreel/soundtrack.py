"""Synthesize a 15 s soundtrack locked to reel.html's timeline (150 BPM, cuts on beats).

Usage: python soundtrack.py [variant] [out.wav]   (race finish times come from reel.html's variant)
"""
import pathlib
import sys
import wave

import numpy as np
from playwright.sync_api import sync_playwright

HERE = pathlib.Path(__file__).parent
VARIANT = sys.argv[1] if len(sys.argv) > 1 else "opus"

SR = 48000
DUR = 15.0
N = int(SR * DUR)
L = np.zeros(N)
R = np.zeros(N)
rng = np.random.default_rng(7)

CUTS = [1.6, 3.2, 8.4, 10.8, 13.2]


def race_data(variant):
    """(tasks, RACE_T0, RACE_SPEED) as reel.html computes them, so sound and picture share one source."""
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page()
        pg.goto((HERE / "reel.html").resolve().as_uri() + f"?v={variant}")
        tasks, t0, speed = pg.evaluate("[window.TASKS.map(r => r.slice(1)), window.RACE_T0, window.RACE_SPEED]")
        b.close()
    return tasks, t0, speed


TASKS, RACE_T0, RACE_SPEED = race_data(VARIANT)


def add(sig, t, gain=1.0, pan=0.0):
    i = int(t * SR)
    if i >= N:
        return
    sig = sig[: N - i] * gain
    L[i:i + len(sig)] += sig * (1 - max(0, pan))
    R[i:i + len(sig)] += sig * (1 + min(0, pan))


def env(n, attack=0.003, decay=0.2):
    t = np.arange(n) / SR
    return np.minimum(1, t / attack) * np.exp(-t / decay)


def kick(dur=0.35):
    n = int(SR * dur); t = np.arange(n) / SR
    f = 42 + 110 * np.exp(-t * 28)
    return np.sin(2 * np.pi * np.cumsum(f) / SR) * env(n, 0.001, 0.14)


def hat(dur=0.05):
    n = int(SR * dur)
    x = rng.standard_normal(n); x = np.diff(np.concatenate([[0], x]))
    return x * env(n, 0.0005, 0.018) * 0.5


def impact(dur=1.4):
    n = int(SR * dur); t = np.arange(n) / SR
    boom = np.sin(2 * np.pi * np.cumsum(38 + 60 * np.exp(-t * 9)) / SR) * env(n, 0.001, 0.5)
    noise = rng.standard_normal(n) * env(n, 0.0005, 0.09) * 0.5
    return boom + noise


def riser(dur=0.6):
    n = int(SR * dur); t = np.arange(n) / SR
    x = rng.standard_normal(n)
    # Crude rising band: difference filter strength grows toward the end.
    y = np.copy(x)
    for k in (1, 2):
        y = np.diff(np.concatenate([[0], y]))
    mix = (t / dur) ** 2
    tone = np.sin(2 * np.pi * np.cumsum(300 + 2400 * (t / dur) ** 2) / SR) * 0.15
    return (x * (1 - mix) * 0.15 + y * mix * 0.25 + tone) * (t / dur) ** 1.5


def blip(freq, dur=0.16):
    n = int(SR * dur); t = np.arange(n) / SR
    return (np.sin(2 * np.pi * freq * t) + 0.3 * np.sin(2 * np.pi * freq * 2 * t)) * env(n, 0.002, 0.06)


def buzz(dur=0.35):
    n = int(SR * dur); t = np.arange(n) / SR
    saw = ((t * 110) % 1) * 2 - 1 + ((t * 116.5) % 1) * 2 - 1
    return saw * env(n, 0.003, 0.15) * 0.35


def tick():
    n = int(SR * 0.012)
    return rng.standard_normal(n) * env(n, 0.0003, 0.003) * 0.6


def pad(freqs, dur):
    n = int(SR * dur); t = np.arange(n) / SR
    s = sum(np.sin(2 * np.pi * f * t + i) for i, f in enumerate(freqs)) / len(freqs)
    a = np.minimum(1, t / 0.25) * np.minimum(1, (dur - t) / 0.9)
    return s * a


# Open: two slams as the words land.
add(impact(0.9), 0.5, 0.55)
add(impact(0.9), 0.95, 0.5)
add(blip(440, 0.4), 0.05, 0.25)
# Risers into every cut, impacts on them.
for c in CUTS:
    add(riser(0.6), c - 0.6, 0.8)
    add(impact(), c, 0.9)
add(impact(1.6), 2.32, 0.8)  # VS lands
# Groove: kick on every beat, hats on off-beats, sub on the one, from the race to the end card.
beat = 0.4
t = 3.2
while t < 13.19:
    add(kick(), t, 0.9)
    add(hat(), t + beat / 2, 0.35, pan=0.3)
    t += beat
t = 3.2
while t < 13.19:
    n = int(SR * 0.38); tt = np.arange(n) / SR
    add(np.sin(2 * np.pi * 55 * tt) * env(n, 0.005, 0.25), t, 0.35)
    t += beat * 2
# Race finishes: A lower, B higher; a buzz as a failed run's stamp lands (1/13 of the race clock later).
for sa, ok_a, sb, ok_b in TASKS:
    add(blip(660), RACE_T0 + sa / RACE_SPEED, 0.35, pan=-0.4)
    add(blip(990), RACE_T0 + sb / RACE_SPEED, 0.35, pan=0.4)
    if not ok_a:
        add(buzz(), RACE_T0 + sa / RACE_SPEED + 1 / 13, 0.6, pan=-0.2)
    if not ok_b:
        add(buzz(), RACE_T0 + sb / RACE_SPEED + 1 / 13, 0.6, pan=0.2)
# Token counters: ticks that slow down as the numbers settle, then the 39x slam.
for i in range(60):
    add(tick(), 8.55 + 1.5 * (i / 60) ** 1.8, 0.5, pan=(-0.5 if i % 2 else 0.5))
add(impact(1.2), 10.0, 0.9)
# Chips stacking, then the 33x slam.
for i in range(28):
    add(blip(1400 + (i % 5) * 90, 0.05), 10.9 + 1.1 * (i / 28) ** 1.3, 0.12, pan=-0.3)
add(impact(1.2), 12.2, 0.9)
# End card: A minor add9 pad under the wordmark.
add(pad([220, 261.63, 329.63, 493.88, 110], 1.8), 13.2, 0.35)

mix = np.stack([L, R], axis=1)
mix = np.tanh(mix * 1.2)  # gentle limiting
mix /= np.max(np.abs(mix)) / 0.89
fade = np.ones(N); fade[-int(0.3 * SR):] = np.linspace(1, 0, int(0.3 * SR))
mix *= fade[:, None]
out = pathlib.Path(sys.argv[2]) if len(sys.argv) > 2 else HERE / "soundtrack.wav"
with wave.open(str(out), "wb") as w:
    w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR)
    w.writeframes((mix * 32767).astype(np.int16).tobytes())
print("wrote", out)
