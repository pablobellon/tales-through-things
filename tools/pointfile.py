"""Compact point-cloud file read by pointcloud.js.

    uint32  count
    float32 scale                  (position = int16 value * scale)
    int16   x, y, z, pad           (count times)
    uint8   r, g, b, a             (count times)
"""
import numpy as np


def write_points(path, positions, rgba):
    """positions: (n, 3) floats in world units. rgba: (n, 4) floats 0..1."""
    positions = np.asarray(positions, np.float64)
    scale = float(np.abs(positions).max()) / 32767
    q = np.zeros((len(positions), 4), np.int16)
    q[:, :3] = np.round(positions / scale)
    c = np.round(np.clip(rgba, 0, 1) * 255).astype(np.uint8)
    with open(path, 'wb') as f:
        f.write(np.uint32(len(positions)).tobytes())
        f.write(np.float32(scale).tobytes())
        f.write(q.tobytes())
        f.write(c.tobytes())
