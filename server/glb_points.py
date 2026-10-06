"""3D model (GLB) → coloured point cloud in the T3 format.

Points are sampled on the model's surface and take the colour of the texture
under them, so each object keeps its real colours in the point-cloud style.
"""
import os
import sys

import numpy as np
import trimesh

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'tools'))
from pointfile import write_points  # noqa: E402

POINTS = 180_000
MAX_W, MAX_H = 3.0, 1.9  # same framing as the demo objects (width while spinning, height)

# Viewing angle (radians, the turntable leaning towards the camera) from the object's
# flatness = height / width: upright things are seen almost from the side, flat things
# (a towel, a plate, a book) from above so their face stays visible while they turn.
TILT_UPRIGHT, TILT_FLAT = 0.15, 0.9      # ≈ 9° and ≈ 52°
FLAT_BELOW, UPRIGHT_ABOVE = 0.15, 0.6    # flatness thresholds


def view_tilt(height, width):
    r = height / max(width, 1e-6)
    k = min(1.0, max(0.0, (UPRIGHT_ABOVE - r) / (UPRIGHT_ABOVE - FLAT_BELOW)))
    return TILT_UPRIGHT + (TILT_FLAT - TILT_UPRIGHT) * k


def _colours(mesh, faces, bary):
    """RGBA 0..255 for points given as (face index, barycentric coordinates)."""
    n = len(faces)
    v = mesh.visual
    try:
        if isinstance(v, trimesh.visual.TextureVisuals) and v.uv is not None:
            mat = v.material
            tex = getattr(mat, 'baseColorTexture', None) or getattr(mat, 'image', None)
            factor = np.asarray(getattr(mat, 'baseColorFactor', None) if
                                getattr(mat, 'baseColorFactor', None) is not None else [255] * 4, float)
            if factor.max() <= 1.0:
                factor = factor * 255
            if tex is not None:
                img = np.asarray(tex.convert('RGBA'), float)
                h, w = img.shape[:2]
                uv = (v.uv[mesh.faces[faces]] * bary[:, :, None]).sum(1)  # per point
                x = np.clip((uv[:, 0] % 1.0) * (w - 1), 0, w - 1).astype(int)
                y = np.clip((1 - uv[:, 1] % 1.0) * (h - 1), 0, h - 1).astype(int)
                return img[y, x] * factor / 255
            return np.tile(factor, (n, 1))
        if isinstance(v, trimesh.visual.ColorVisuals):
            vc = np.asarray(v.vertex_colors, float)  # interpolate vertex colours
            return (vc[mesh.faces[faces]] * bary[:, :, None]).sum(1)
    except Exception as err:
        print('colour lookup failed:', repr(err), flush=True)
    return np.tile([120, 200, 230, 255], (n, 1)).astype(float)  # no colour: T3 cyan


def glb_to_points(glb_path, out_path, count=POINTS):
    scene = trimesh.load(glb_path, force='scene')
    meshes = [g for g in scene.dump() if isinstance(g, trimesh.Trimesh) and len(g.faces)]
    if not meshes:
        raise ValueError('no mesh in the 3D model')

    # spread the points over the meshes by surface area
    areas = np.array([m.area for m in meshes])
    counts = np.maximum(1, np.round(count * areas / areas.sum())).astype(int)
    pts, cols = [], []
    for mesh, n in zip(meshes, counts):
        p, faces, bary = trimesh.sample.sample_surface(mesh, n, return_barycentric=True)
        c = _colours(mesh, faces, bary)
        pts.append(p)
        cols.append(c / 255.0)
    p = np.vstack(pts)
    c = np.vstack(cols)
    c[:, 3] = np.clip(c[:, 3], 0.75, 1.0)

    # centre, choose the viewing angle, and fit the same frame as the other objects
    p = p - (p.max(0) + p.min(0)) / 2
    radial = np.sqrt(p[:, 0] ** 2 + p[:, 2] ** 2).max() * 2
    height = p[:, 1].max() - p[:, 1].min()
    tilt = view_tilt(height, radial)
    # seen from above, the depth shows on screen too: keep the tilted silhouette in frame
    on_screen_h = height * np.cos(tilt) + radial * np.sin(tilt)
    p *= min(MAX_W / max(radial, 1e-6), MAX_H / max(on_screen_h, 1e-6))

    order = np.random.default_rng(1).permutation(len(p))  # any prefix = uniform subsample
    write_points(out_path, p[order], c[order])
    return len(p), round(float(tilt), 3)


if __name__ == '__main__':
    # python server/glb_points.py model.glb points.bin
    n, tilt = glb_to_points(sys.argv[1], sys.argv[2])
    print(n, 'points, tilt', tilt)
