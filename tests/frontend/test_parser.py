from __future__ import annotations

import os
from pathlib import Path

import pytest

from src.translator.errors import TranslatorError
from src.translator.parser import parse, parse_text
from src.translator.syntax_tree import Binary, IntegerLiteral, Program, VarDecl, dump

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parents[1]
_EXAMPLES = _ROOT / "examples"
_AST_GOLDEN = _HERE / "golden" / "ast"
_EXAMPLE_PATHS = sorted(_EXAMPLES.glob("*.ps"))


def test_ast_basic_shapes() -> None:
    program = parse_text("int x = 1;", "ast.ps")
    assert isinstance(program, Program)
    item = program.items[0]
    assert isinstance(item, VarDecl)
    assert item.name == "x"
    assert isinstance(item.init, IntegerLiteral)


@pytest.mark.parametrize("path", _EXAMPLE_PATHS, ids=[path.stem for path in _EXAMPLE_PATHS])
def test_ast_matches_golden(path: Path) -> None:
    expected = (_AST_GOLDEN / f"{path.stem}.sexp").read_text(encoding="utf-8").rstrip("\n")
    assert dump(parse(str(path))) == expected, path.name


def test_precedence_and_power_associativity() -> None:
    cases = [
        ("1 + 2 * 3;", "(expr (+ 1 (* 2 3)))"),
        ("1 - 2 - 3;", "(expr (- (- 1 2) 3))"),
        ("2 ** 3 ** 2;", "(expr (** 2 (** 3 2)))"),
        ("-2 ** 2;", "(expr (- (** 2 2)))"),
        ("true | false & false;", "(expr (| true (& false false)))"),
    ]
    for source, expected in cases:
        assert dump(parse_text(source, "precedence.ps")) == f"(program\n  {expected})"

    item = parse_text("int x = 2 ** 3 ** 2;", "power.ps").items[0]
    assert isinstance(item, VarDecl)
    assert isinstance(item.init, Binary)
    assert isinstance(item.init.right, Binary)


def test_include_and_parser_errors(tmp_path: Path) -> None:
    missing = os.path.normcase(os.path.abspath("nope.ps"))
    path_errors = [
        ('include "";', "путь include не может быть пустым"),
        ('include "nope.ps";', f"не удалось открыть файл {missing!r}"),
        ('include "x.txt";', "путь include должен заканчиваться на .ps или .h"),
        ('include "../x.ps";', "путь include не может содержать .."),
    ]
    for source, expected in path_errors:
        try:
            parse_text(source, "bad.ps")
        except TranslatorError as error:
            assert error.message == expected, (source, error)
        else:
            raise AssertionError(f"ожидалась ошибка для {source!r}")

    syntax_errors = [
        ("int x = ;", "ожидалось выражение, найдено ';'"),
        ("int x = 5", "ожидалось ;, найдено конец файла"),
        ("int x = 2 ** -3;", "операнд ** не может быть унарным выражением, используйте скобки"),
        ("while (x < 10) x += 1;", "ожидалось {, найдено 'x'"),
        ("int[] a = [];", "пустой литерал массива не поддерживается, используйте new int[0]"),
        ("x + 1 = 2;", "слева от присваивания может стоять только переменная или элемент массива"),
    ]
    for source, expected in syntax_errors:
        try:
            parse_text(source, "bad.ps")
        except TranslatorError as error:
            assert error.message == expected, (source, error)
        else:
            raise AssertionError(f"ожидалась ошибка для {source!r}")

    first = tmp_path / "first.ps"
    second = tmp_path / "second.ps"
    first.write_text('include "second.ps";\n', encoding="utf-8")
    second.write_text('include "first.ps";\n', encoding="utf-8")
    try:
        parse(str(first))
    except TranslatorError as error:
        assert error.message == "файл 'first.ps' уже включён"
    else:
        raise AssertionError("ожидалась ошибка циклического include")
