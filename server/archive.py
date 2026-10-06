"""The collection of memories.

Each memory is a folder archive/<id>/ with:
  meta.json   {"id", "object", "haiku": [3 lines], "theme", "created", "tilt"}
  points.bin  the point cloud shown on the iPad (format: tools/pointfile.py)
  model.glb   the original 3D model, when there is one

A visitor's memory is built in runs/<session>/ first and only moved here
if they agree to add it to the archive; otherwise the run is deleted.
"""
import json
import os
import shutil
import time
import uuid

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.environ.get('T3_DATA', ROOT)  # on a server: a folder outside the code
ARCHIVE = os.path.join(DATA, 'archive')
RUNS = os.path.join(DATA, 'runs')
MOCK = os.path.join(ROOT, 'server', 'mock')

# The demo objects, told by the objects themselves: they seed an empty archive.
SEED = [
    ('gameboy', 'Game Boy', 'toy', 0.12,
     ['Under the blanket', 'my small light keeps you awake,', 'one more level, still']),
    ('bicycle', 'bicycle', 'outside', 0.10,
     ['His hand lets go,', 'for three seconds only I', 'hold the summer up']),
    ('camera', 'disposable camera', 'summer', 0.15,
     ['Twenty-seven blinks,', 'half of them blurred by laughter,', 'you kept every one']),
    ('tin', 'biscuit tin', 'pocket', 0.32,
     ['Sunday, my lid lifts,', 'no biscuits, only buttons,', 'and still you smile']),
]


def _write_meta(folder, meta):
    with open(os.path.join(folder, 'meta.json'), 'w') as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)


def seed_if_empty():
    os.makedirs(ARCHIVE, exist_ok=True)
    if list_memories():
        return
    for i, (name, obj, theme, tilt, haiku) in enumerate(SEED):
        mid = f'seed-{name}'
        folder = os.path.join(ARCHIVE, mid)
        os.makedirs(folder, exist_ok=True)
        shutil.copy(os.path.join(MOCK, f'{name}.bin'), os.path.join(folder, 'points.bin'))
        _write_meta(folder, {'id': mid, 'object': obj, 'haiku': haiku, 'theme': theme,
                             'created': time.time() - 1000 * (len(SEED) - i), 'tilt': tilt})


def _public(meta):
    return dict(meta, points=f"/archive/{meta['id']}/points.bin")


def list_memories():
    out = []
    if not os.path.isdir(ARCHIVE):
        return out
    for mid in os.listdir(ARCHIVE):
        path = os.path.join(ARCHIVE, mid, 'meta.json')
        if os.path.isfile(path) and os.path.isfile(os.path.join(ARCHIVE, mid, 'points.bin')):
            try:
                with open(path) as f:
                    out.append(_public(json.load(f)))
            except (OSError, ValueError):
                pass
    return sorted(out, key=lambda m: m.get('created', 0), reverse=True)


# ---------------------------------------------------------------- runs

def new_run():
    sid = uuid.uuid4().hex[:12]
    os.makedirs(os.path.join(RUNS, sid), exist_ok=True)
    return sid


def run_dir(sid):
    return os.path.join(RUNS, sid)


def save_run_result(sid, meta):
    _write_meta(run_dir(sid), dict(meta, id=sid, created=time.time()))


def run_result(sid):
    path = os.path.join(run_dir(sid), 'meta.json')
    if not os.path.isfile(path):
        return None
    with open(path) as f:
        meta = json.load(f)
    return dict(meta, points=f'/runs/{sid}/points.bin')


def keep_run(sid):
    """Move a finished run into the archive."""
    src = run_dir(sid)
    dst = os.path.join(ARCHIVE, sid)
    if os.path.isfile(os.path.join(src, 'meta.json')) and not os.path.exists(dst):
        for name in os.listdir(src):
            if name not in ('meta.json', 'points.bin', 'model.glb'):
                os.remove(os.path.join(src, name))  # intermediate files (images...)
        shutil.move(src, dst)


def discard_run(sid):
    shutil.rmtree(run_dir(sid), ignore_errors=True)


def cleanup_old_runs(max_age_s=3600):
    """Runs nobody kept (visitor walked away): delete after an hour."""
    if not os.path.isdir(RUNS):
        return
    now = time.time()
    for sid in os.listdir(RUNS):
        path = os.path.join(RUNS, sid)
        if os.path.isdir(path) and now - os.path.getmtime(path) > max_age_s:
            shutil.rmtree(path, ignore_errors=True)
