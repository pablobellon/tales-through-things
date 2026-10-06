"""One visitor's conversation: theme → questions → object + haiku → archive or not.

Nothing about the visitor is stored beyond the session: answers live in memory
only, and the generated memory is deleted unless they choose to archive it.
"""
import json
import os
import random
import threading
import time

import archive
from voice import hear

MAX_QUESTIONS = 3  # the theme's first question + AI follow-ups
SESSION_TTL = 3600
# Spending cap: new visits per hour, whatever happens (a leaked passcode can't drain the credit).
MAX_SESSIONS_PER_HOUR = int(os.environ.get('T3_MAX_SESSIONS_PER_HOUR', 40))

with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'script.json')) as f:
    SCRIPT = json.load(f)


class Session:
    def __init__(self, theme_key):
        self.sid = archive.new_run()
        self.theme_key = theme_key
        self.theme = SCRIPT['themes'][theme_key]
        self.qa = []                    # [{'q': ..., 'a': ...}]
        self.question = self.theme['questions'][0]
        self.status = 'asking'          # asking | generating | ready | error
        self.stage = None
        self.result = None
        self.error = None
        self.touched = time.time()


class Sessions:
    def __init__(self, providers):
        self.ai = providers
        self.items = {}
        self.lock = threading.Lock()
        self.started = []  # timestamps of recent visits (spending cap)

    # ---------------------------------------------------------------- helpers

    def _get(self, sid):
        with self.lock:
            s = self.items.get(sid)
        if not s:
            raise KeyError('unknown session')
        s.touched = time.time()
        return s

    def _expire(self):
        now = time.time()
        with self.lock:
            for sid in [k for k, s in self.items.items() if now - s.touched > SESSION_TTL]:
                del self.items[sid]
        archive.cleanup_old_runs(SESSION_TTL)

    # ---------------------------------------------------------------- API

    def transcribe_yes_no(self, question_key, wav):
        text = hear(self.ai, wav)
        if not text:
            return {'answer': 'empty'}
        answer = self.ai.yes_no(SCRIPT['lines'].get(question_key, question_key), text)
        print(f'  {question_key}: {text!r} → {answer}', flush=True)
        return {'answer': answer, 'heard': text}

    def start(self):
        self._expire()
        now = time.time()
        with self.lock:
            self.started = [t for t in self.started if now - t < 3600]
            if len(self.started) >= MAX_SESSIONS_PER_HOUR:
                raise RuntimeError('hourly limit of new memories reached')
            self.started.append(now)
        s = Session(random.choice(list(SCRIPT['themes'])))
        with self.lock:
            self.items[s.sid] = s
        return {'session': s.sid, 'theme': s.theme_key, 'question': s.question,
                'index': 1, 'total': MAX_QUESTIONS}

    def answer(self, sid, wav):
        s = self._get(sid)
        if s.status != 'asking':
            raise ValueError('not asking')
        text = hear(self.ai, wav)
        if not text:
            # nothing heard: same question again (the iPad shows the "hold" hint)
            return {'question': s.question, 'index': len(s.qa) + 1, 'total': MAX_QUESTIONS,
                    'empty': True}
        s.qa.append({'q': s.question, 'a': text})
        if len(s.qa) < MAX_QUESTIONS:
            s.question = self.ai.next_question(s.theme, s.qa, MAX_QUESTIONS)
            return {'question': s.question, 'index': len(s.qa) + 1, 'total': MAX_QUESTIONS,
                    'heard': text}
        s.status = 'generating'
        threading.Thread(target=self._generate, args=(s,), daemon=True).start()
        return {'done': True, 'heard': text}

    def _generate(self, s):
        try:
            s.stage = 'composing'
            comp = self.ai.compose(s.theme, s.qa)
            info = self.ai.build_object(comp, archive.run_dir(s.sid),
                                        lambda st: setattr(s, 'stage', st)) or {}
            archive.save_run_result(s.sid, {
                'object': comp['object'], 'haiku': comp['haiku'],
                'theme': s.theme_key, 'tilt': info.get('tilt', comp.get('tilt', 0.15)),
            })
            s.result = archive.run_result(s.sid)
            s.status = 'ready'
        except Exception as err:  # shown as a friendly error on the iPad
            s.error = repr(err)
            s.status = 'error'
            print('generation failed:', s.error, flush=True)

    def status(self, sid):
        s = self._get(sid)
        out = {'status': s.status, 'stage': s.stage}
        if s.status == 'ready':
            out['memory'] = s.result
        return out

    def finish(self, sid, keep):
        s = self._get(sid)
        if keep and s.status == 'ready':
            archive.keep_run(sid)
        else:
            archive.discard_run(sid)
        with self.lock:
            self.items.pop(sid, None)
        return {'kept': bool(keep and s.status == 'ready')}
