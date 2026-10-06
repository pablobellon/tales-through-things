"""The AI steps behind T3, as one interface with interchangeable implementations.

    transcribe(wav_bytes)              -> what the visitor said
    yes_no(question, answer)           -> 'yes' | 'no' | 'unclear'
    next_question(theme, qa, total)    -> the next question to ask
    compose(theme, qa)                 -> {'object', 'haiku': [3 lines], 'image_prompt', 'tilt'}
    build_object(composition, folder, stage)
                                       -> writes folder/points.bin (+ model.glb); calls
                                          stage('imagining' | 'sculpting' | 'finishing');
                                          may return {'tilt': viewing angle}

Cloud implementation (keys in .env):
    speech-to-text  OpenAI      OPENAI_API_KEY
    conversation    Claude      ANTHROPIC_API_KEY  (Sonnet 5.5; Haiku 4.5 for yes/no)
    image + 3D      fal.ai      FAL_KEY            (FLUX schnell → TRELLIS)
Any service without a key falls back to the mock, so pieces can be tested alone.
"""
import json
import os
import random
import shutil
import time
import urllib.request

from archive import MOCK, SEED
import prompts
from syllables import pattern
from textclean import clean_lines, no_dashes

# Haiku style: 'strict' = classic form, checked (5-7-5 counted here, season word, cut);
#              'free'   = haiku-inspired three lines (the earlier behaviour).
HAIKU_MODE = os.environ.get('T3_HAIKU', 'strict').strip().lower()
HAIKU_FORM = [5, 7, 5]
HAIKU_TRIES = 3  # revisions if the count is off


def pause(seconds):
    # MOCK_FAST=1 skips the pretend thinking time (automated tests)
    if os.environ.get('MOCK_FAST') != '1':
        time.sleep(seconds)


# ------------------------------------------------------------------ mock

class MockProviders:
    """Stand-in AI: scripted questions, a random demo object, realistic delays."""

    def transcribe(self, wav):
        pause(0.6)
        return random.choice([
            'I remember it was red, a bit scratched, and it made a little clicking sound.',
            'It was at my grandmother’s house, every summer.',
            'I used to carry it everywhere, even to school.',
        ])

    def yes_no(self, question, answer):
        # The mock can't hear: MOCK_YESNO=yes|no|unclear picks the branch to test.
        pause(0.4)
        return os.environ.get('MOCK_YESNO', 'yes')

    def next_question(self, theme, qa, total=3):
        pause(1.2)
        scripted = theme['questions']
        return scripted[min(len(qa), len(scripted) - 1)]

    def compose(self, theme, qa):
        pause(1.5)
        name, obj, _, tilt, haiku = random.choice(SEED)
        return {'object': obj, 'haiku': haiku, 'tilt': tilt, 'mock_model': name,
                'image_prompt': f'A {obj}, single object, three-quarter view, plain white background'}

    def build_object(self, composition, folder, stage):
        stage('imagining')
        pause(3)
        stage('sculpting')
        pause(4)
        name = composition.get('mock_model') or random.choice(SEED)[0]
        shutil.copy(os.path.join(MOCK, name + '.bin'), os.path.join(folder, 'points.bin'))


# ------------------------------------------------------------------ cloud

def _conversation(qa):
    return '\n'.join(f'Q: {x["q"]}\nA: {x["a"] or "(no answer)"}' for x in qa)


class CloudProviders(MockProviders):
    def __init__(self):
        self.stt = None
        self.claude = None
        self.fal = None
        if os.environ.get('OPENAI_API_KEY'):
            from openai import OpenAI
            self.stt = OpenAI(timeout=60)
        if os.environ.get('ANTHROPIC_API_KEY'):
            import anthropic
            self.anthropic = anthropic
            self.claude = anthropic.Anthropic(timeout=90)
        if os.environ.get('FAL_KEY'):
            import fal_client
            self.fal = fal_client
        self.model = os.environ.get('T3_MODEL', 'claude-sonnet-5-5')
        self.fast_model = os.environ.get('T3_FAST_MODEL', 'claude-haiku-4-5')
        self.stt_model = os.environ.get('T3_STT_MODEL', 'gpt-4o-mini-transcribe')

    @property
    def name(self):
        parts = [f'speech: {"OpenAI " + self.stt_model if self.stt else "mock"}',
                 f'conversation: {self.model if self.claude else "mock"} (haiku: {HAIKU_MODE})',
                 f'3D: {"fal.ai" if self.fal else "mock"}']
        return ' · '.join(parts)

    # -- speech to text

    def transcribe(self, wav):
        if not self.stt:
            return super().transcribe(wav)
        if len(wav) < 16000:  # under ~0.5 s of audio
            return ''
        try:
            r = self.stt.audio.transcriptions.create(
                model=self.stt_model, file=('answer.wav', wav, 'audio/wav'), language='en',
                prompt='A visitor of an art installation describing a childhood memory.')
        except Exception as err:
            if self.stt_model == 'whisper-1':
                raise
            print(f'transcription with {self.stt_model} failed ({err!r}), using whisper-1', flush=True)
            self.stt_model = 'whisper-1'
            return self.transcribe(wav)
        text = (r.text or '').strip()
        print(f'  heard: {text!r}', flush=True)
        return text

    # -- Claude

    def _ask(self, model, system, user, schema, max_tokens, effort=None):
        """One Claude call with a JSON answer that must match `schema`."""
        output_config = {'format': {'type': 'json_schema', 'schema': schema}}
        if effort:
            output_config['effort'] = effort
        kwargs = dict(model=model, max_tokens=max_tokens, system=system,
                      messages=[{'role': 'user', 'content': user}], output_config=output_config)
        if model.startswith('claude-sonnet-5-5'):
            # server-side refusal fallback: a declined request is retried on another model
            try:
                resp = self.claude.beta.messages.create(
                    betas=['server-side-fallback-2026-07-01'], fallbacks='default', **kwargs)
            except self.anthropic.BadRequestError as err:
                print('fallbacks not accepted, plain request:', err.message, flush=True)
                resp = self.claude.messages.create(**kwargs)
        else:
            resp = self.claude.messages.create(**kwargs)
        if resp.stop_reason == 'refusal':
            raise RuntimeError('Claude declined this request')
        if resp.stop_reason == 'max_tokens':
            raise RuntimeError('Claude ran out of tokens')
        text = next(b.text for b in resp.content if b.type == 'text')
        return json.loads(text)

    def yes_no(self, question, answer):
        if not self.claude:
            return super().yes_no(question, answer)
        if not answer.strip():
            return 'unclear'
        out = self._ask(
            self.fast_model, prompts.YES_NO, f'Question: {question}\nAnswer: {answer}',
            {'type': 'object', 'additionalProperties': False, 'required': ['answer'],
             'properties': {'answer': {'type': 'string', 'enum': ['yes', 'no', 'unclear']}}},
            max_tokens=200)
        return out['answer']

    def next_question(self, theme, qa, total=3):
        if not self.claude:
            return super().next_question(theme, qa, total)
        user = (f'Theme: {theme["title"]}\n'
                'Theme questions (inspiration only):\n' +
                '\n'.join(f'- {q}' for q in theme['questions']) +
                f'\n\nConversation so far:\n{_conversation(qa)}\n\n'
                f'Write question {len(qa) + 1} of {total}'
                f'{" (the last one: lead them to the heart of the moment)" if len(qa) + 1 == total else ""}.')
        out = self._ask(
            self.model, prompts.INTERVIEWER, user,
            {'type': 'object', 'additionalProperties': False, 'required': ['question'],
             'properties': {'question': {'type': 'string'}}},
            max_tokens=4000, effort='low')
        return no_dashes(out['question'])

    def compose(self, theme, qa):
        if not self.claude:
            return super().compose(theme, qa)
        strict = HAIKU_MODE == 'strict'
        props = {
            'object': {'type': 'string'},
            'image_prompt': {'type': 'string'},
            'haiku': {'type': 'array', 'items': {'type': 'string'}},
        }
        if strict:
            props['season_word'] = {'type': 'string'}
        out = self._ask(
            self.model, prompts.COMPOSER_STRICT if strict else prompts.COMPOSER,
            f'Theme: {theme["title"]}\n\nConversation:\n{_conversation(qa)}',
            {'type': 'object', 'additionalProperties': False,
             'required': list(props), 'properties': props},
            max_tokens=8000, effort='medium')
        haiku = clean_lines(out['haiku'])[:3]
        if strict:
            haiku = self._check_haiku(haiku, out.get('season_word', ''))
        print(f'  object: {out["object"]!r}\n  haiku: {haiku} {pattern(haiku)}', flush=True)
        return {'object': out['object'], 'haiku': haiku, 'image_prompt': out['image_prompt'],
                'tilt': 0.15}

    def _check_haiku(self, haiku, season_word):
        """Count syllables here (not Claude's estimate); ask for revisions until 5-7-5."""
        def problems(h):
            p = []
            if len(h) != 3:
                p.append(f'it must have exactly 3 lines (it has {len(h)})')
            else:
                counts = pattern(h)
                for i, (n, want) in enumerate(zip(counts, HAIKU_FORM)):
                    if n != want:
                        p.append(f'line {i + 1} has {n} syllables, it needs {want}')
            if season_word and season_word.lower() not in ' '.join(h).lower():
                p.append(f'the season word "{season_word}" must appear')
            return p

        best, best_score = haiku, None
        for attempt in range(HAIKU_TRIES + 1):
            issues = problems(haiku)
            score = sum(abs(n - w) for n, w in zip(pattern(haiku), HAIKU_FORM)) + 5 * abs(len(haiku) - 3)
            if best_score is None or score < best_score:
                best, best_score = haiku, score
            if not issues:
                return haiku
            if attempt == HAIKU_TRIES:
                break
            print(f'  haiku revision {attempt + 1}: {"; ".join(issues)}', flush=True)
            out = self._ask(
                self.model, prompts.HAIKU_FIX,
                'Haiku:\n' + '\n'.join(haiku) +
                f'\n\nSeason word: {season_word or "(none)"}\n'
                f'Measured syllables per line: {pattern(haiku)}\nTo fix: ' + '; '.join(issues),
                {'type': 'object', 'additionalProperties': False, 'required': ['haiku'],
                 'properties': {'haiku': {'type': 'array', 'items': {'type': 'string'}}}},
                max_tokens=4000, effort='low')
            haiku = clean_lines(out['haiku'])[:3]
        print('  haiku: kept the closest version', flush=True)
        return best

    # -- image + 3D

    def build_object(self, composition, folder, stage):
        if not self.fal:
            return super().build_object(composition, folder, stage)
        from glb_points import glb_to_points

        stage('imagining')
        img = self.fal.subscribe('fal-ai/flux/schnell', arguments={
            'prompt': composition['image_prompt'], 'image_size': 'square_hd',
            'num_inference_steps': 4, 'output_format': 'png'}, client_timeout=120)
        image_url = img['images'][0]['url']
        _download(image_url, os.path.join(folder, 'image.png'))

        stage('sculpting')
        mesh = self.fal.subscribe('fal-ai/trellis', arguments={
            'image_url': image_url, 'texture_size': 1024}, client_timeout=240)
        glb = os.path.join(folder, 'model.glb')
        _download(mesh['model_mesh']['url'], glb)

        stage('finishing')
        n, tilt = glb_to_points(glb, os.path.join(folder, 'points.bin'))
        print(f'  3D: {n} points, viewing angle {tilt}', flush=True)
        return {'tilt': tilt}


def _download(url, path):
    with urllib.request.urlopen(url, timeout=120) as r, open(path, 'wb') as f:
        shutil.copyfileobj(r, f)


def load_providers():
    if any(os.environ.get(k) for k in ('OPENAI_API_KEY', 'ANTHROPIC_API_KEY', 'FAL_KEY')):
        return CloudProviders()
    p = MockProviders()
    p.name = 'mock (no keys in .env)'
    return p
