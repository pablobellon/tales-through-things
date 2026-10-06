"""Did the visitor actually say something? (before paying for a transcription)

Measures how much of the recording is louder than the room's own noise.
Speech-to-text models tend to "hear" words in silence ("Thank you.", "you"...),
so a recording without voice is treated as empty and the iPad shows the
"hold the button while you speak" hint instead.
"""
import io
import os
import wave

import numpy as np

MIN_VOICE_MS = int(os.environ.get('T3_MIN_VOICE_MS', 150))  # a short "yes" is ~200 ms of voice
ABS_FLOOR = float(os.environ.get('T3_VOICE_LEVEL', 0.006))   # RMS below this is never voice

# what speech-to-text typically invents from silence or noise
PHANTOMS = {'', 'you', 'thank you', 'thank you.', 'thanks for watching!', 'bye', 'bye.',
            '.', 'okay.', 'hmm', 'mm', 'uh'}


def voiced_ms(wav_bytes):
    """Milliseconds of voice in a 16-bit mono WAV; None if it can't be read."""
    try:
        with wave.open(io.BytesIO(wav_bytes)) as w:
            rate = w.getframerate()
            samples = np.frombuffer(w.readframes(w.getnframes()), '<i2').astype(np.float32) / 32768
    except (wave.Error, EOFError, ValueError):
        return None
    frame = max(1, int(rate * 0.02))  # 20 ms frames
    n = len(samples) // frame
    if n == 0:
        return 0
    rms = np.sqrt((samples[: n * frame].reshape(n, frame) ** 2).mean(1))
    noise = np.percentile(rms, 20)  # the quietest moments ≈ the room
    voiced = rms > max(ABS_FLOOR, noise * 3)
    return int(voiced.sum() * 20)


def hear(ai, wav_bytes):
    """Transcribe only if there is voice in the recording; '' when nothing was said."""
    ms = voiced_ms(wav_bytes)
    if ms is not None and ms < MIN_VOICE_MS:
        print(f'  no voice ({ms} ms)', flush=True)
        return ''
    text = ai.transcribe(wav_bytes).strip()
    if text.lower() in PHANTOMS and (ms is None or ms < 600):
        print(f'  ignored {text!r} ({ms} ms of voice)', flush=True)
        return ''
    return text
