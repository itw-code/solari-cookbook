"""Synthesize the benchmark reel's 15 s soundtrack (numpy only, 48 kHz stereo, no samples).

Same voices and 120 BPM bed as media/arc-index-reel/soundtrack.py; foley locked to bench.html's
timeline: title hits, the table landing, the model's pick, three verdicts, the stamp, counters.
Usage: python soundtrack.py [out.wav]
"""
import sys
import wave

import numpy as np

SR, DUR, BEAT = 48000, 15.0, 0.5
N = int(SR * DUR)
L = np.zeros(N)
R = np.zeros(N)
SEND = np.zeros(N)  # reverb bus (mono)
rs = np.random.default_rng(7)


def mtof(m):
    return 440.0 * 2 ** ((m - 69) / 12)


def put(t0, sig, gain=1.0, pan=0.0, verb=0.0):
    i = int(t0 * SR)
    if i >= N:
        return
    sig = sig[: N - i] * gain
    L[i:i + len(sig)] += sig * np.sqrt((1 - pan) / 2)
    R[i:i + len(sig)] += sig * np.sqrt((1 + pan) / 2)
    SEND[i:i + len(sig)] += sig * verb


def tt(d):
    return np.arange(int(d * SR)) / SR


def onepole(x, a):
    """Lowpass with per-sample (or scalar) coefficient a in (0,1]; higher = brighter."""
    a = np.broadcast_to(a, x.shape)
    y = np.empty_like(x)
    acc = 0.0
    for i in range(len(x)):
        acc += a[i] * (x[i] - acc)
        y[i] = acc
    return y


def noise(d):
    return rs.standard_normal(int(d * SR))


# ---------- voices ----------
def kick(d=0.45):
    t = tt(d)
    f = 45 + 95 * np.exp(-t * 28)
    return np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 7) + 0.3 * noise(d) * np.exp(-t * 300)


def paper(d=0.14):
    t = tt(d)
    body = onepole(noise(d), 0.25) * np.exp(-t * 32)
    return body * 1.6 + np.sin(2 * np.pi * 85 * t) * np.exp(-t * 30) * 0.6


def whoosh(d, up=True):
    t = tt(d)
    p = t / d
    sweep = (p if up else 1 - p)
    a = 0.02 + 0.35 * sweep ** 2
    env = np.sin(np.pi * np.clip(p, 0, 1)) ** 1.5
    return onepole(noise(d), a) * env * 2.2


def pluck(m, d=0.6):
    t = tt(d)
    f = mtof(m)
    return (np.sin(2 * np.pi * f * t) + 0.35 * np.sin(4 * np.pi * f * t) + 0.12 * np.sin(6 * np.pi * f * t)) * np.exp(-t * 7) * (1 - np.exp(-t * 900))


def bell(m, d=2.2):
    t = tt(d)
    f = mtof(m)
    out = np.zeros_like(t)
    for r, a, k in [(1, 1, 2.2), (2.76, .5, 3.5), (5.4, .25, 6), (8.93, .12, 9)]:
        out += a * np.sin(2 * np.pi * f * r * t) * np.exp(-t * k)
    return out * (1 - np.exp(-t * 2000))


def tick(d=0.018, bright=0.9):
    t = tt(d)
    x = noise(d)
    x = x - onepole(x, 0.3)  # crude highpass
    return x * np.exp(-t * 350) * bright


def stamp():
    d = 0.6
    t = tt(d)
    thud = np.sin(2 * np.pi * np.cumsum(70 + 60 * np.exp(-t * 40)) / SR) * np.exp(-t * 11)
    slap = onepole(noise(d), 0.5) * np.exp(-t * 45)
    return thud * 1.2 + slap * 1.1


def impact(d=1.6, depth=1.0):
    t = tt(d)
    sub = np.sin(2 * np.pi * np.cumsum(32 + 70 * np.exp(-t * 9)) / SR) * np.exp(-t * 2.6)
    crack = onepole(noise(d), 0.6) * np.exp(-t * 22)
    return (sub * 1.3 + crack * 0.8) * depth


def marker(d=0.3):
    t = tt(d)
    f = 1800 + 900 * np.sin(2 * np.pi * 9 * t)
    band = onepole(noise(d), 0.45) - onepole(noise(d), 0.08)
    return (band * 0.8 + 0.08 * np.sin(2 * np.pi * np.cumsum(f) / SR)) * np.sin(np.pi * t / d)


def riser(d):
    t = tt(d)
    p = t / d
    f = 220 * 2 ** (p * 2.5)
    tone = np.sin(2 * np.pi * np.cumsum(f) / SR) * 0.25
    return (tone + onepole(noise(d), 0.03 + 0.5 * p ** 3) * 1.4) * p ** 2.2


def printer(d):
    t = tt(d)
    sq = np.sign(np.sin(2 * np.pi * 165 * t)) * 0.25 + np.sign(np.sin(2 * np.pi * 330.7 * t)) * 0.12
    gate = (np.sin(2 * np.pi * 14 * t) > -0.2).astype(float)
    return onepole(sq * gate, 0.2) * np.minimum(1, t * 30) * np.minimum(1, (d - t) * 30)


# ---------- music bed ----------
CHORDS = [[50, 57, 62, 66, 69, 76], [47, 54, 62, 66, 69, 73], [43, 55, 62, 66, 71, 73], [45, 57, 61, 64, 66, 69]]
ROOTS = [38, 35, 31, 33]
bed_t = np.arange(N) / SR
pad = np.zeros(N)
for k in range(8):  # 2 s per chord, cycle twice (8 x 2 s = 16 s)
    t0, t1 = k * 2.0, k * 2.0 + 2.25
    i0, i1 = int(t0 * SR), min(N, int(t1 * SR))
    if i0 >= N:
        break
    seg_t = bed_t[i0:i1] - t0
    env = np.minimum(1, seg_t / 0.35) * np.minimum(1, (2.25 - seg_t) / 0.4)
    s = np.zeros(i1 - i0)
    for j, m in enumerate(CHORDS[k % 4]):
        f = mtof(m + 12)
        for det in (-0.12, 0.12):
            s += np.sin(2 * np.pi * f * (1 + det / 100) * seg_t + j) + 0.3 * np.sin(4 * np.pi * f * seg_t)
    pad[i0:i1] += s * env
pad = onepole(pad, 0.02 + 0.10 * np.clip(bed_t / 13, 0, 1)) * 0.10
duck = np.ones(N)
bass = np.zeros(N)
for b in range(4, 26):  # kicks from 2.0 s to 12.5 s
    tb = b * BEAT
    put(tb, kick(), 0.9, 0, 0.05)
    i = int(tb * SR)
    dt = np.arange(int(0.3 * SR)) / SR
    duck[i:i + len(dt)] = np.minimum(duck[i:i + len(dt)], 0.35 + 0.65 * (dt / 0.3))
    for half in (0, 1):  # 8th-note bass
        ts = tb + half * BEAT / 2
        f = mtof(ROOTS[int(ts // 2.0) % 4])
        d = tt(0.22)
        sig = (np.sin(2 * np.pi * f * d) + 0.4 * np.sin(4 * np.pi * f * d)) * np.exp(-d * 9) * (1 - np.exp(-d * 400))
        j = int(ts * SR)
        bass[j:j + len(sig)] += sig[: N - j] * (0.35 if half else 0.5)
    if b >= 8:
        put(tb + BEAT / 2, tick(0.04, 0.5), 0.35, 0.4)
L += pad * duck + bass * duck * 0.8
R += pad * duck + bass * duck * 0.8

# ---------- foley on bench.html's timeline ----------
put(0.30, whoosh(0.4, True), 0.3, -0.2)
put(0.45, impact(0.9, 0.5), 0.6, 0, 0.2)                 # "Wrong values"
put(0.80, impact(1.2, 0.7), 0.7, 0.1, 0.3)               # "accepted."
put(1.35, marker(0.3), 0.35, 0.2)
put(1.75, tick(0.03, 0.8), 0.4)
put(2.95, whoosh(0.5, False), 0.6, 0.3, 0.1)             # title leaves
put(3.28, paper(), 1.2, 0, 0.15)                         # the page lands
for i in range(3):                                       # rows
    put(3.52 + i * 0.12, tick(0.02, 0.8), 0.45, (i - 1) * 0.3)
put(4.05, marker(0.45), 0.55, 0.2)                       # outline round row 2
put(4.32, pluck(81, 0.4), 0.35, 0.4, 0.3)                # model chip
for k, t0 in enumerate([5.0, 5.55]):                     # two red ticks: accepted
    put(t0, pluck(86 + 3 * k, 0.5), 0.4, 0.3, 0.4)
    put(t0, tick(0.03, 1.0), 0.5, 0.3)
put(5.95, marker(0.4), 0.45, -0.2)                       # dashed outline, row 3
put(6.20, pluck(62, 0.9), 0.55, -0.1, 0.4)               # the cross: rejected
put(6.47, stamp(), 1.1, 0.1, 0.35)                       # BLANK FOR A HUMAN
put(7.35, whoosh(0.55, True), 0.8, 0.5, 0.1)
put(7.85, impact(1.3, 0.8), 0.8, 0, 0.3)                 # tallies headline
for k in range(12):                                      # counters roll up
    put(8.62 + k * 0.045, tick(0.02, 0.7), 0.3, -0.4)
for k in range(10):
    put(9.12 + k * 0.05, tick(0.02, 0.7), 0.3, 0.4)
put(9.55, pluck(62, 0.9), 0.45, 0.4, 0.4)                # the 0 lands
put(10.15, bell(86), 0.25, 0, 0.5)
put(11.15, whoosh(0.5, False), 0.7, -0.3, 0.1)
for k in range(10):                                      # 20.5 -> 6.1 counter
    put(11.72 + 0.6 * (1 - 2 ** (-k * 0.8)), tick(0.02, 0.8), 0.35, 0.2)
put(12.35, marker(0.3), 0.5, 0.2)                        # strike "was 20.5 s"
put(12.47, impact(1.2, 0.9), 0.8, 0, 0.3)                # -70.2%
put(12.85, whoosh(0.6, False), 0.8, 0, 0.3)
put(13.22, impact(2.2, 1.1), 1.0, 0, 0.5)                # the 0
for k, m in enumerate([62, 69, 74, 78, 81]):             # end chord (D add9 spread)
    put(13.45 + k * 0.05, bell(m + 12, 1.6), 0.18, (k - 2) * 0.25, 0.7)
    put(13.45, pluck(m, 1.4), 0.2, (k - 2) * 0.2, 0.6)
put(13.95, marker(0.45), 0.35, 0)                        # underline

# ---------- reverb (feedback combs) + master ----------
wet = np.zeros(N)
for dl, fb in [(0.0297, 0.78), (0.0371, 0.76), (0.0411, 0.74), (0.0437, 0.72)]:
    d = int(dl * SR)
    y = SEND.copy()
    for i in range(d, N, d):
        y[i:i + d] += y[i - d:i][: len(y[i:i + d])] * fb
    wet += y
wet = onepole(wet, 0.3) * 0.18
L += wet
R += np.roll(wet, int(0.011 * SR))
fade = np.clip((DUR - bed_t) / 0.6, 0, 1) * np.clip(bed_t / 0.02, 0, 1)
mix = np.stack([L, R], 1) * fade[:, None]
mix = np.tanh(mix / np.max(np.abs(mix)) * 1.6)
mix = mix / np.max(np.abs(mix)) * 0.89
out = sys.argv[1] if len(sys.argv) > 1 else "soundtrack.wav"
with wave.open(out, "wb") as w:
    w.setnchannels(2)
    w.setsampwidth(2)
    w.setframerate(SR)
    w.writeframes((mix * 32767).astype("<i2").tobytes())
print(f"wrote {out}")
