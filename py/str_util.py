import string
from typing import Iterable


def strip_punctuation(s: str) -> str:
    return s.translate(str.maketrans('', '', string.punctuation))


def extract_parenthesized_strs(s: str) -> Iterable[str]:
    """
    Returns all parenthesized strings in the input string.
    """
    while s:
        start = s.find('(')
        if start == -1:
            return []
        end = s.find(')')
        if end == -1:
            return []
        yield s[start + 1:end]
        s = s[end + 1:]


def remove_parenthesized_strs(s: str) -> str:
    """
    Removes all parenthesized strings from the input string.
    """
    orig_s = s
    tokens = []
    while s:
        start = s.find('(')
        if start == -1:
            tokens.append(s)
            break
        end = s.find(')')
        if end == -1:  # unmatched left paren
            tokens.append(s[:start].strip())
            break
        if end < start:  # unmatched right paren
            s = s[end+1:]
            continue

        tokens.append(s[:start].strip())
        s = s[end + 1:]
    return ' '.join(tokens).strip()
