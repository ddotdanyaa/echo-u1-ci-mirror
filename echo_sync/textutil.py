"""Only the exact production Unicode normalization needed by the pure E41 judge."""
import re
import unicodedata

WORDS = re.compile(r"[^\W_]+(?:[-’'][^\W_]+)*", re.UNICODE)

def normalize(text):
    return ' '.join(WORDS.findall(unicodedata.normalize('NFKC', str(text or '')).casefold().replace('ё', 'е')))
