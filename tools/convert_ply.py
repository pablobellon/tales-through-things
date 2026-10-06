"""Convert a Gaussian-splat .ply into the compact point file used by gameboy.js.

usage: python3 tools/convert_ply.py mockup/3D/gameboy.ply assets/gameboy.bin [max_points]
needs: numpy

Assumes the splat is Z-up with its front facing -Y (true for gameboy.ply);
adjust the axis swap below for other scans.
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
from pointfile import write_points  # noqa: E402

src, dst = sys.argv[1], sys.argv[2]
max_points = int(sys.argv[3]) if len(sys.argv) > 3 else 320000

data = open(src, 'rb').read()
header_end = data.index(b'end_header\n') + len(b'end_header\n')
props = [l.split()[-1].decode() for l in data[:header_end].splitlines() if l.startswith(b'property')]
a = np.frombuffer(data[header_end:], dtype='<f4').reshape(-1, len(props))
col = {name: a[:, i] for i, name in enumerate(props)}

opacity = 1 / (1 + np.exp(-col['opacity']))
keep = opacity > 0.25

# splat (x, y, z) -> three.js (x, z, -y): up = +z, front = -y
p = np.stack([col['x'], col['z'], -col['y']], 1)[keep]
p -= (p.max(0) + p.min(0)) / 2
p *= 2 / (p[:, 1].max() - p[:, 1].min())  # 2 units tall

SH_C0 = 0.28209479
rgb = np.clip(0.5 + SH_C0 * np.stack([col['f_dc_0'], col['f_dc_1'], col['f_dc_2']], 1)[keep], 0, 1)
opacity = opacity[keep]

# shuffle so any prefix is a uniform subsample
idx = np.random.default_rng(1).permutation(len(p))[:max_points]
p, rgb, opacity = p[idx], rgb[idx], opacity[idx]

write_points(dst, p, np.concatenate([rgb, opacity[:, None]], 1))
print(f'{len(p)} points -> {dst}')
