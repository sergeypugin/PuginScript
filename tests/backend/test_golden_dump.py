"""Golden-тесты трансляции: дампы обязательных примеров."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.translator.codegen import codegen, dump
from src.translator.parser import parse
from src.translator.semantic import check

_HERE = Path(__file__).resolve().parent
_EXAMPLES = _HERE.parents[1] / "examples"
_DUMP_GOLDEN = _HERE / "golden" / "dump"
_EXAMPLE_PATHS = sorted(_EXAMPLES.glob("*.ps"))

# equality.ps намеренно содержит семантическую ошибку и не транслируется
_GOLDEN_EXAMPLES = [path for path in _EXAMPLE_PATHS if path.name != "equality.ps"]


@pytest.mark.parametrize("path", _GOLDEN_EXAMPLES, ids=[path.stem for path in _GOLDEN_EXAMPLES])
def test_listing_matches_golden(path: Path) -> None:
    golden_path = _DUMP_GOLDEN / f"{path.stem}.dump"
    expected = golden_path.read_text(encoding="utf-8")
    assert expected.endswith("\n"), f"{golden_path} must end with a newline"

    program = parse(str(path))
    result = check(program)
    assert not result.errors, path.name
    assert dump(codegen(program, result)) + "\n" == expected, path.name
