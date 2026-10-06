"""English syllable counting, for checking haiku (5-7-5).

Uses the CMU Pronouncing Dictionary (the standard reference for English
pronunciation); words it doesn't know fall back to a vowel-group rule.
"""
import re

try:
    import pronouncing
except ImportError:  # still works, less precisely
    pronouncing = None

WORD = re.compile(r"[A-Za-z]+(?:['’][A-Za-z]+)?")


def _dictionary(word):
    if not pronouncing:
        return None
    phones = pronouncing.phones_for_word(word)
    if phones:
        return min(pronouncing.syllable_count(p) for p in phones)  # shortest usual reading
    return None


def _rule(word):
    w = word.lower()
    groups = re.findall(r'[aeiouy]+', w)
    n = len(groups)
    if w.endswith('e') and not w.endswith(('le', 'ee', 'ye')) and n > 1:
        n -= 1  # silent final e (stone, smile)
    if w.endswith(('ed',)) and not w.endswith(('ted', 'ded')) and n > 1:
        n -= 1  # silent -ed (lifted keeps it, walked doesn't)
    return max(1, n)


def word_syllables(word):
    w = word.lower().replace('’', "'")
    n = _dictionary(w)
    if n is None and "'" in w:  # possessives, contractions: sun's, you're
        n = _dictionary(w.split("'")[0])
    return n if n is not None else _rule(w.split("'")[0])


def line_syllables(line):
    return sum(word_syllables(w) for w in WORD.findall(line))


def pattern(lines):
    return [line_syllables(l) for l in lines]
