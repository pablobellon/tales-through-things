"""House style for every text shown to visitors: no dashes (— or –).

A dash ending a line is dropped (the line break already makes the pause);
a dash inside a sentence becomes a comma. Hyphens inside words (pine-warm)
are kept.
"""
import re

DASH = r'\s*[—–]\s*|\s+-{1,2}\s+'  # em/en dash, or a spaced hyphen used as a dash


def no_dashes(text):
    text = text.strip()
    text = re.sub(r'(' + DASH + r')+$', '', text)          # at the end: just drop it
    text = re.sub(r'^(' + DASH + r')+', '', text)          # at the start too
    text = re.sub(DASH, ', ', text)                        # inside: a comma
    text = re.sub(r',\s*([,.;:!?])', r'\1', text)          # no doubled punctuation
    text = re.sub(r'\s{2,}', ' ', text)
    return text.strip()


def clean_lines(lines):
    return [no_dashes(l) for l in lines if no_dashes(l)]
