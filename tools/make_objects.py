"""Generate procedural point-cloud objects in the same style as the Game Boy scan.

usage: python3 tools/make_objects.py          (writes assets/bicycle.bin, camera.bin, tin.bin)
needs: numpy

Each object is sampled as surface points (x-ray look: insides are modelled too),
coloured with the cyan palette of the scan plus a few accents, then written in
the format read by pointcloud.js (see tools/pointfile.py).
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
from pointfile import write_points  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
rng = np.random.default_rng(7)

# palette (close to the colours stored in gameboy.ply)
CYAN = np.array([0.05, 0.50, 0.72])
CYAN_HI = np.array([0.30, 0.85, 1.00])
DEEP = np.array([0.03, 0.22, 0.45])
NAVY = np.array([0.02, 0.05, 0.18])
PINK = np.array([0.85, 0.12, 0.50])
VIOLET = np.array([0.35, 0.30, 0.85])
WHITE = np.array([0.80, 0.92, 1.00])


class Cloud:
    def __init__(self):
        self.p, self.c = [], []

    def add(self, pts, color, vary=0.35, alpha=(0.75, 1.0)):
        pts = np.asarray(pts, float).reshape(-1, 3)
        n = len(pts)
        b = rng.uniform(1 - vary, 1 + vary * 0.6, (n, 1))
        rgb = np.clip(np.asarray(color)[None, :] * b, 0, 1)
        a = rng.uniform(*alpha, (n, 1))
        self.p.append(pts)
        self.c.append(np.hstack([rgb, a]))

    def arrays(self):
        return np.vstack(self.p), np.vstack(self.c)


# ------------------------------------------------------------------ helpers

def basis(axis):
    axis = np.asarray(axis, float)
    axis = axis / np.linalg.norm(axis)
    tmp = np.array([1.0, 0, 0]) if abs(axis[0]) < 0.9 else np.array([0, 1.0, 0])
    u = np.cross(axis, tmp)
    u /= np.linalg.norm(u)
    v = np.cross(axis, u)
    return axis, u, v


def jitter(pts, s):
    return pts + rng.normal(0, s, pts.shape)


def line(p0, p1, n, j=0.002):
    t = rng.random((n, 1))
    return jitter(np.asarray(p0) + (np.asarray(p1) - np.asarray(p0)) * t, j)


def tube(p0, p1, r, n):
    """Surface of a cylinder between p0 and p1."""
    p0, p1 = np.asarray(p0, float), np.asarray(p1, float)
    axis, u, v = basis(p1 - p0)
    t = rng.random((n, 1))
    a = rng.random((n, 1)) * 2 * np.pi
    return p0 + (p1 - p0) * t + r * (np.cos(a) * u + np.sin(a) * v)


def ring(center, axis, R, n, j=0.002):
    _, u, v = basis(axis)
    a = rng.random((n, 1)) * 2 * np.pi
    return jitter(np.asarray(center) + R * (np.cos(a) * u + np.sin(a) * v), j)


def torus(center, axis, R, r, n):
    ax, u, v = basis(axis)
    a = rng.random((n, 1)) * 2 * np.pi
    b = rng.random((n, 1)) * 2 * np.pi
    radial = np.cos(a) * u + np.sin(a) * v
    return np.asarray(center) + (R + r * np.cos(b)) * radial + r * np.sin(b) * ax


def disc(center, axis, R, n, r0=0.0):
    _, u, v = basis(axis)
    a = rng.random((n, 1)) * 2 * np.pi
    rr = np.sqrt(rng.uniform(r0 ** 2 / R ** 2, 1, (n, 1))) * R
    return np.asarray(center) + rr * (np.cos(a) * u + np.sin(a) * v)


def box(c, size, n, edges=0.25):
    """Points on the surface of an axis-aligned box, extra density on edges."""
    c, s = np.asarray(c, float), np.asarray(size, float) / 2
    areas = np.array([s[1] * s[2], s[0] * s[2], s[0] * s[1]]) * 2
    nf = int(n * (1 - edges))
    face = rng.choice(3, nf, p=areas / areas.sum())
    pts = rng.uniform(-1, 1, (nf, 3)) * s
    sign = rng.choice([-1, 1], nf)
    pts[np.arange(nf), face] = sign * s[face]
    # edges
    ne = n - nf
    e = rng.uniform(-1, 1, (ne, 3)) * s
    keep = rng.integers(0, 3, ne)
    for k in range(3):
        m = keep != k
        e[m, k] = np.sign(e[m, k]) * s[k]  # pin every axis except the free one
    return np.vstack([pts, e]) + c


def ellipsoid(c, radii, n):
    d = rng.normal(size=(n, 3))
    d /= np.linalg.norm(d, axis=1, keepdims=True)
    return np.asarray(c) + d * np.asarray(radii)


def rotate(pts, axis, angle, origin=(0, 0, 0)):
    ax, _, _ = basis(axis)
    o = np.asarray(origin, float)
    p = pts - o
    cos, sin = np.cos(angle), np.sin(angle)
    return o + p * cos + np.cross(ax, p) * sin + ax * (p @ ax)[:, None] * (1 - cos)


# ------------------------------------------------------------------ objects

def bicycle():
    cl = Cloud()
    Z = np.array([0, 0, 1.0])
    rear, front = np.array([-0.42, 0.30, 0]), np.array([0.42, 0.30, 0])
    for w in (rear, front):
        cl.add(torus(w, Z, 0.30, 0.026, 14000), DEEP, 0.4)             # tyre
        cl.add(ring(w, Z, 0.30 + 0.026, 2500), CYAN_HI, 0.2)           # tread outline
        cl.add(torus(w, Z, 0.268, 0.008, 5000), CYAN_HI, 0.25)         # rim
        cl.add(tube(w - [0, 0, 0.045], w + [0, 0, 0.045], 0.018, 1200), CYAN_HI)  # hub
        for k in range(20):                                          # spokes
            a = k / 20 * 2 * np.pi
            hub = w + [0.018 * np.cos(a), 0.018 * np.sin(a), 0.035 * (1 if k % 2 else -1)]
            rim = w + [0.262 * np.cos(a + 0.25), 0.262 * np.sin(a + 0.25), 0]
            cl.add(line(hub, rim, 260, 0.0015), WHITE, 0.3)

    bb = np.array([-0.05, 0.27, 0])
    seat_top = np.array([-0.16, 0.62, 0])
    head_top, head_bot = np.array([0.29, 0.66, 0]), np.array([0.33, 0.53, 0])
    tubes = [
        (bb, seat_top, 0.022), (seat_top, head_top, 0.02), (bb, head_bot, 0.026),
        (head_bot, head_top, 0.028),
    ]
    for side in (-1, 1):
        o = np.array([0, 0, 0.05 * side])
        tubes += [(bb + o * 0.5, rear + o, 0.012), (seat_top + o * 0.3, rear + o, 0.011),
                  (head_bot + o * 0.6, front + o * 0.9, 0.013)]
    for a, b, r in tubes:
        n = int(np.linalg.norm(b - a) * 30000)
        cl.add(tube(a, b, r, n), CYAN, 0.35)
        cl.add(line(a, b, n // 5, 0.003), CYAN_HI, 0.2)

    # seat post + saddle
    post_top = np.array([-0.19, 0.73, 0])
    cl.add(tube(seat_top, post_top, 0.014, 1500), CYAN_HI)
    cl.add(ellipsoid(post_top + [0.0, 0.025, 0], [0.12, 0.028, 0.055], 9000), PINK, 0.3)

    # stem + handlebar + grips
    stem_top = np.array([0.27, 0.80, 0])
    cl.add(tube(head_top, stem_top, 0.016, 1800), CYAN)
    bar_l, bar_r = stem_top + [-0.04, 0, -0.24], stem_top + [-0.04, 0, 0.24]
    cl.add(tube(bar_l, bar_r, 0.012, 5000), CYAN_HI)
    for end in (bar_l, bar_r):
        d = (end - stem_top) / np.linalg.norm(end - stem_top)
        cl.add(tube(end - d * 0.09, end + d * 0.01, 0.02, 3000), PINK, 0.3)
    cl.add(ring(stem_top + [0.02, 0.025, 0.12], [0, 1, 0], 0.025, 600), WHITE)  # bell
    cl.add(disc(stem_top + [0.02, 0.04, 0.12], [0, 1, 0], 0.025, 600), WHITE)

    # chainring, chain, cranks, pedals
    cl.add(ring(bb + [0, 0, 0.06], Z, 0.085, 3000), CYAN_HI)
    cl.add(disc(bb + [0, 0, 0.06], Z, 0.085, 2500), CYAN, 0.4, alpha=(0.4, 0.7))
    for s in (-1, 1):
        cl.add(line(bb + [0, 0.085 * s, 0.06], rear + [0, 0.035 * s, 0.06], 900, 0.002), WHITE, 0.3)
    for s, a in ((1, -0.9), (-1, -0.9 + np.pi)):
        end = bb + [0.16 * np.cos(a), 0.16 * np.sin(a), 0.08 * s]
        cl.add(tube(bb + [0, 0, 0.07 * s], end, 0.01, 900), CYAN_HI)
        cl.add(box(end + [0, 0, 0.05 * s], [0.08, 0.018, 0.09], 1500), NAVY, 0.3)

    return cl


def camera():
    cl = Cloud()
    W, H, D = 13.2, 6.8, 3.6
    # body + cardboard sleeve (different shade on the middle band)
    cl.add(box([0, 0, 0], [W, H, D], 90000, edges=0.3), CYAN, 0.35)
    sleeve = box([0, -0.3, 0], [W + 0.08, H * 0.62, D + 0.08], 36000, edges=0.0)
    sleeve = sleeve[np.abs(sleeve[:, 2]) > D / 2]  # only front and back
    cl.add(sleeve, DEEP, 0.4)
    # printed "label" lines on the front band
    for k in range(5):
        y = -1.9 + k * 0.45
        x0 = rng.uniform(-6, -2)
        cl.add(line([x0, y, D / 2 + 0.06], [x0 + rng.uniform(3, 7), y, D / 2 + 0.06], 900, 0.01),
               WHITE, 0.3)

    # lens barrel + glass
    lc = np.array([2.4, 0.7, D / 2])
    cl.add(tube(lc, lc + [0, 0, 0.9], 1.45, 9000), CYAN_HI, 0.3)
    cl.add(ring(lc + [0, 0, 0.9], [0, 0, 1], 1.45, 2500), WHITE, 0.2)
    cl.add(disc(lc + [0, 0, 0.9], [0, 0, 1], 1.45, 4000, r0=0.95), NAVY, 0.3)
    cl.add(disc(lc + [0, 0, 0.75], [0, 0, 1], 0.95, 5000), VIOLET, 0.35)
    cl.add(ring(lc + [0, 0, 0.78], [0, 0, 1], 0.55, 800), WHITE, 0.2)

    # flash window + viewfinder
    cl.add(box([-4.1, 2.1, D / 2 + 0.05], [3.4, 1.5, 0.1], 7000, edges=0.4), WHITE, 0.25)
    cl.add(box([0.3, 2.45, D / 2 + 0.05], [1.4, 0.9, 0.1], 2500, edges=0.5), NAVY, 0.3)
    cl.add(box([0.3, 2.45, -D / 2 - 0.05], [1.4, 0.9, 0.1], 2500, edges=0.5), VIOLET, 0.3)

    # top: shutter button, frame counter; back: film advance wheel
    cl.add(tube([4.2, H / 2, 0.3], [4.2, H / 2 + 0.35, 0.3], 0.5, 2500), PINK, 0.3)
    cl.add(disc([4.2, H / 2 + 0.35, 0.3], [0, 1, 0], 0.5, 1500), PINK, 0.3)
    cl.add(box([2.6, H / 2 + 0.02, -0.6], [0.8, 0.05, 0.6], 800, edges=0.5), WHITE)
    wheel_c = np.array([5.0, H / 2 - 0.2, -D / 2 + 0.6])
    cl.add(tube(wheel_c - [0, 0.35, 0], wheel_c + [0, 0.35, 0], 1.0, 5000), CYAN_HI, 0.3)
    for k in range(36):  # ridges
        a = k / 36 * 2 * np.pi
        p = wheel_c + [1.02 * np.cos(a), 0, 1.02 * np.sin(a)]
        cl.add(line(p - [0, 0.35, 0], p + [0, 0.35, 0], 60, 0.01), WHITE, 0.2)

    # x-ray insides: film canister, take-up spool, film strip, AA battery
    cl.add(tube([-5.0, -2.8, -0.2], [-5.0, 2.6, -0.2], 1.05, 9000), CYAN_HI, 0.3)
    cl.add(ring([-5.0, -2.8, -0.2], [0, 1, 0], 1.05, 800), WHITE)
    cl.add(ring([-5.0, 2.6, -0.2], [0, 1, 0], 1.05, 800), WHITE)
    cl.add(tube([4.8, -2.6, -0.2], [4.8, 2.4, -0.2], 0.8, 6000), CYAN, 0.3)
    film = np.column_stack([rng.uniform(-4.0, 4.0, 9000), rng.uniform(-1.9, 1.9, 9000),
                            np.full(9000, -0.55)])
    cl.add(film, DEEP, 0.4, alpha=(0.5, 0.8))
    for y in (-1.7, 1.7):  # perforations
        for x in np.arange(-3.9, 4.0, 0.35):
            cl.add(box([x, y, -0.55], [0.15, 0.12, 0.02], 25, edges=0.8), WHITE, 0.2)
    cl.add(tube([-5.8, -2.6, 1.0], [-0.8, -2.6, 1.0], 0.7, 5000), CYAN_HI, 0.3)
    cl.add(disc([-0.8, -2.6, 1.0], [1, 0, 0], 0.7, 600), PINK, 0.3)
    cl.add(tube([-3.6, 1.3, 0.8], [-1.6, 1.3, 0.8], 0.45, 2000), WHITE, 0.3)  # flash capacitor
    return cl


def tin():
    cl = Cloud()
    Y = np.array([0, 1.0, 0])
    R, Hb = 1.0, 0.55
    # body wall, bottom, rolled rims
    a = rng.random(30000) * 2 * np.pi
    y = rng.random(30000) * Hb
    cl.add(np.column_stack([R * np.cos(a), y, R * np.sin(a)]), CYAN, 0.35)
    cl.add(disc([0, 0, 0], Y, R, 9000), CYAN, 0.35, alpha=(0.5, 0.8))
    cl.add(torus([0, Hb, 0], Y, R, 0.018, 4000), CYAN_HI, 0.2)
    cl.add(torus([0, 0, 0], Y, R, 0.015, 3000), CYAN_HI, 0.2)
    # decorative bands + dot pattern on the wall
    for yy in (0.12, 0.43):
        cl.add(ring([0, yy, 0], Y, R + 0.004, 2500), WHITE, 0.25)
    for k in range(48):
        ang = k / 48 * 2 * np.pi
        cl.add(disc([1.006 * np.cos(ang), 0.275, 1.006 * np.sin(ang)],
                    [np.cos(ang), 0, np.sin(ang)], 0.045, 90), PINK, 0.3)

    # lid: lifted and tilted so the buttons show
    lid = Cloud()
    Rl, hl = 1.04, 0.14
    a = rng.random(9000) * 2 * np.pi
    y = rng.random(9000) * hl
    lid.add(np.column_stack([Rl * np.cos(a), y, Rl * np.sin(a)]), CYAN, 0.35)
    lid.add(disc([0, hl, 0], Y, Rl, 16000), CYAN, 0.35, alpha=(0.6, 0.9))
    lid.add(torus([0, hl, 0], Y, Rl, 0.02, 3000), CYAN_HI, 0.2)
    lid.add(torus([0, 0, 0], Y, Rl, 0.015, 2000), CYAN_HI, 0.2)
    for r in (0.88, 0.62, 0.2):  # embossed rings
        lid.add(ring([0, hl + 0.01, 0], Y, r, int(3000 * r) + 400), WHITE, 0.25)
    for k in range(8):  # flower petals between the rings
        ang = k / 8 * 2 * np.pi
        t = rng.random(700) * 2 * np.pi
        px, pz = 0.41 + 0.17 * np.cos(t), 0.08 * np.sin(t)
        pts = np.column_stack([px * np.cos(ang) - pz * np.sin(ang), np.full(700, hl + 0.012),
                               px * np.sin(ang) + pz * np.cos(ang)])
        lid.add(jitter(pts, 0.004), PINK, 0.3)
    for k in range(32):  # dot ring
        ang = k / 32 * 2 * np.pi
        lid.add(disc([0.75 * np.cos(ang), hl + 0.012, 0.75 * np.sin(ang)], Y, 0.02, 40), WHITE)
    lp, lc = lid.arrays()
    lp = rotate(lp, [1, 0, 0], -0.32, origin=[0, 0, -Rl])  # hinge open at the back
    lp += [0, Hb + 0.12, 0]
    cl.p.append(lp)
    cl.c.append(lc)

    # x-ray: the buttons inside (and one spool of thread)
    colors = [PINK, WHITE, VIOLET, CYAN_HI, PINK, WHITE]
    for k in range(46):
        r = rng.uniform(0.06, 0.14)
        ang, rad = rng.uniform(0, 2 * np.pi), np.sqrt(rng.random()) * (0.86 - r)
        c = np.array([rad * np.cos(ang), rng.uniform(0.05, 0.42), rad * np.sin(ang)])
        normal = np.array([rng.normal(0, 0.5), 1, rng.normal(0, 0.5)])
        _, u, v = basis(normal)
        n = int(1400 * (r / 0.1) ** 2)
        q = rng.random(n) * 2 * np.pi
        rr = np.sqrt(rng.random(n)) * r
        loc = np.column_stack([rr * np.cos(q), rr * np.sin(q)])
        holes = 2 if k % 3 == 0 else 4
        hole_pos = [(r * 0.28 * np.cos(h * 2 * np.pi / holes + 0.5), r * 0.28 * np.sin(h * 2 * np.pi / holes + 0.5))
                    for h in range(holes)]
        keep = np.ones(n, bool)
        for hx, hy in hole_pos:
            keep &= np.hypot(loc[:, 0] - hx, loc[:, 1] - hy) > r * 0.12
        loc = loc[keep]
        pts = c + loc[:, :1] * u + loc[:, 1:] * v
        cl.add(pts, colors[k % len(colors)], 0.3)
        cl.add(ring(c, normal, r, int(300 * r / 0.1)), WHITE, 0.2)
    spool = np.array([0.35, 0.2, -0.3])
    cl.add(tube(spool - [0, 0.15, 0], spool + [0, 0.15, 0], 0.12, 3000), PINK, 0.3)
    for e in (-0.17, 0.17):
        cl.add(disc(spool + [0, e, 0], Y, 0.17, 800), CYAN_HI, 0.3)
    return cl


# ------------------------------------------------------------------ output

def finish(cl, name, max_w=3.0, max_h=2.0):
    p, c = cl.arrays()
    p = p - (p.max(0) + p.min(0)) / 2
    radial = np.sqrt(p[:, 0] ** 2 + p[:, 2] ** 2).max() * 2  # width while spinning
    s = min(max_w / radial, max_h / (p[:, 1].max() - p[:, 1].min()))
    p *= s
    idx = rng.permutation(len(p))  # shuffle: any prefix is a uniform subsample
    out = os.path.join(ROOT, 'assets', f'{name}.bin')
    write_points(out, p[idx], c[idx])
    print(f'{len(p):7d} points -> {os.path.relpath(out, ROOT)}  size {np.ptp(p, 0).round(2)}')


if __name__ == '__main__':
    finish(bicycle(), 'bicycle', max_w=3.2, max_h=1.9)
    finish(camera(), 'camera', max_w=3.0, max_h=1.8)
    finish(tin(), 'tin', max_w=2.3, max_h=1.4)
