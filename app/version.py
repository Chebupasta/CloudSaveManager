"""Версия приложения и сравнение версий GitHub Releases."""
import re

__version__ = '1.0.0'

_NUMBERS = re.compile(r'\d+')


def parse_version(tag: str) -> tuple:
    """'v1.2.3' / '1.2.3-beta' -> (1, 2, 3)."""
    return tuple(int(part) for part in _NUMBERS.findall(tag or '')[:3])


def is_newer(candidate: str, current: str = __version__) -> bool:
    """True, если candidate старше текущей версии."""
    a, b = parse_version(candidate), parse_version(current)
    # Выравниваем длину: (1, 2) и (1, 2, 0) — одинаковые версии.
    n = max(len(a), len(b))
    return a + (0,) * (n - len(a)) > b + (0,) * (n - len(b))
