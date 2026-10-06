"""Check each AI service with the keys in .env, one by one.

usage:  .venv/bin/python tools/check_ai.py          speech + Claude (a fraction of a cent)
        .venv/bin/python tools/check_ai.py --3d     also image + 3D on fal.ai (~3 cents)
"""
import os
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'server'))

from main import load_env  # noqa: E402

load_env()
from providers import load_providers  # noqa: E402
from sessions import SCRIPT  # noqa: E402

ai = load_providers()
print('providers:', ai.name, '\n')


def step(title, fn):
    t = time.time()
    try:
        out = fn()
        print(f'✓ {title} ({time.time() - t:.1f}s): {out}')
        return out
    except Exception as err:
        print(f'✗ {title}: {err!r}')
        return None


# speech: the Mac's own voice reads an answer, OpenAI transcribes it
def speech():
    with tempfile.TemporaryDirectory() as d:
        wav = os.path.join(d, 'a.wav')
        subprocess.run(['say', '-o', wav, '--data-format=LEI16@16000',
                        'It was a small red tin robot, a bit rusty, and it made a clicking sound.'],
                       check=True)
        return ai.transcribe(open(wav, 'rb').read())


heard = step('speech-to-text', speech) or 'It was a small red tin robot, a bit rusty.'
step('yes/no "sure, let\'s do it"', lambda: ai.yes_no(SCRIPT['lines']['invite'], "sure, let's do it"))
step('yes/no "maybe later"', lambda: ai.yes_no(SCRIPT['lines']['invite'], 'maybe later'))

theme = SCRIPT['themes']['toy']
qa = [{'q': theme['questions'][0], 'a': heard}]
q2 = step('follow-up question', lambda: ai.next_question(theme, qa, 3))
qa.append({'q': q2 or theme['questions'][1], 'a': 'It was cold and heavy, I kept it under my pillow.'})
q3 = step('last question', lambda: ai.next_question(theme, qa, 3))
qa.append({'q': q3 or theme['questions'][2], 'a': 'My grandfather gave it to me the summer before he died.'})
comp = step('object + haiku', lambda: ai.compose(theme, qa))

if comp and '--3d' in sys.argv:
    out = os.path.join(ROOT, 'runs', 'check')
    os.makedirs(out, exist_ok=True)
    step('image + 3D + points', lambda: (ai.build_object(comp, out, lambda s: print('   ...', s)),
                                         sorted(os.listdir(out)))[1])
    print(f'\nFiles in {out} (image.png = the generated picture)')
