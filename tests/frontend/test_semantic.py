from __future__ import annotations

from src.translator.parser import parse_text
from src.translator.semantic import check


def _errors(source: str) -> list[str]:
    return [error.message for error in check(parse_text(source, "semantic.ps")).errors]


def test_positive_programs() -> None:
    sources = [
        "int x = 5; bool b = true; str s = \"hi\";",
        "int[] a = [1, 2, 3]; int[] b = new int[0]; b = a;",
        "str s = input(); s = s + \"!\"; println(s);",
        "const int a = 1; const int b = a * 2; const bool c = b == 2;",
        "def f(int[] a) -> int { return len(a); }",
        "def main() -> int { return 0; }",
        "int x = 1; return x + 1;",
        "def f() -> int { if (true) { return 1; } else { return 0; } }",
        "def f(int x) -> int { { int x = 2; return x; } }",
        "int x = 1; { int x = 2; }",
        "println(1 + \"a\"); println(true); println(5);",
        "print_char(65); int n = input_int(); int ch = input_char();",
        "const int m = -2147483648; const int w = 2147483647 + 1;",
        "def p() { return; }",
    ]
    for source in sources:
        assert _errors(source) == [], source


def test_type_scope_and_builtin_errors() -> None:
    cases = [
        ("int x = true;", "инициализатор 'x': ожидался int, получен bool"),
        ("bool b = 1;", "инициализатор 'b': ожидался bool, получен int"),
        ("x = 1;", "неизвестное имя 'x'"),
        ("int x = 1; int x = 2;", "повторное объявление 'x' в одной области видимости"),
        ("if (1) { }", "условие должно быть bool, получен int"),
        ("def f() -> int { }", "функция 'f' должна вернуть int на всех путях исполнения"),
        ("def p() { return 1; }", "процедура не возвращает значение"),
        ("def f() -> int { return true; }", "возвращаемое значение: ожидался int, получен bool"),
        ("def main(int a) { }", "main не принимает параметров"),
        ("const int c = 1; c = 2;", "нельзя присваивать константе 'c'"),
        ("int[] a = [1, true];", "элемент массива: ожидался int, получен bool"),
        ("int[] a = new int[true];", "размер массива должен быть int, получен bool"),
        ("int a = 5; a[0] = 1;", "индексация применяется только к массивам"),
        ("def f(int x, bool x) { }", "повторное объявление параметра 'x'"),
        (
            "def f(int x) -> int { return x; } int y = f(true);",
            "аргумент 1 функции 'f': ожидался int, получен bool",
        ),
        ("println(1, 2);", "'println' принимает не больше одного аргумента, получено 2"),
        ("int[] a = [1]; print(a);", "'print': не печатает массивы"),
        ("len(5);", "'len': применяется к строкам и массивам, получен int"),
        ("input_char(1);", "'input_char' не принимает аргументов"),
        ("def main() { } def main() { }", "повторное объявление имени 'main'"),
        ("int top = 1; def f() -> int { return top; }", "неизвестное имя 'top'"),
    ]
    for source, expected in cases:
        assert _errors(source) == [expected], source


def test_const_and_runtime_related_diagnostics() -> None:
    cases = [
        ("const int c = input();", "инициализатор const не может использовать вызовы, new и индексацию"),
        ('const str s = "a" + "b";', "конкатенация строк не выполняется на этапе компиляции"),
        ("const int z = 1 / 0;", "деление на ноль в инициализаторе const"),
        ("const int z = 2 ** (0 - 1);", "отрицательная степень в инициализаторе const"),
        ("int[] a = new int[-1];", "размер массива не может быть отрицательным"),
        ("const int n = -1; int[] a = new int[n];", "размер массива не может быть отрицательным"),
        ("int[] a = new int[1 - 2];", "размер массива не может быть отрицательным"),
        ("int x = [1, 2];", "литерал массива не подходит для типа int"),
        ('str s = "a"; s[0] = 120;', "строку нельзя изменять по индексу"),
        ('str s = "a"; s += "b";', "операция '+=' определена только для int"),
    ]
    for source, expected in cases:
        assert _errors(source) == [expected], source


def test_array_size_boundaries() -> None:
    assert _errors("int[] a = new int[0];") == []
    assert _errors("int n = input_int(); int[] a = new int[n];") == []


def test_uninitialized_variables() -> None:
    cases = [
        ("int value; println(value);", "переменная 'value' не инициализирована"),
        ("int value; value = 1; println(value);", None),
        ("def f(int value) -> int { return value; }", None),
        (
            "int value; if (true) { value = 1; } println(value);",
            "переменная 'value' не инициализирована",
        ),
        ("int value; if (true) { value = 1; } else { value = 2; } println(value);", None),
        (
            "int value; while (false) { value = 1; } println(value);",
            "переменная 'value' не инициализирована",
        ),
        ("int value; value += 1;", "переменная 'value' не инициализирована"),
    ]
    for source, expected in cases:
        errors = _errors(source)
        if expected is None:
            assert errors == [], source
        else:
            assert expected in errors, source


def test_semantic_collects_independent_errors() -> None:
    assert len(_errors("foo(); bar();")) == 2
    assert len(_errors("bool a = 1; bool b = 2;")) == 2
