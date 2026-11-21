from __future__ import annotations

from pathlib import Path

from src.translator.parser import parse
from src.translator.semantic import check

_ROOT = Path(__file__).resolve().parents[2]
_EXAMPLES = _ROOT / "examples"


def test_examples() -> None:
    for path in sorted(_EXAMPLES.glob("*.ps")):
        result = check(parse(str(path)))
        if path.name == "equality.ps":
            assert len(result.errors) == 1
            assert result.errors[0].message == "сравнение массивов через '==' и '!=' запрещено"
        else:
            assert result.errors == [], path.name
