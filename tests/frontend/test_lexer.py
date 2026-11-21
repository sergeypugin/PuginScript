from __future__ import annotations

import pytest

from src.translator.errors import TranslatorError
from src.translator.lexer import TokenKind, lex
from src.translator.syntax_tree import SourceLocation


def test_tokens_positions_and_comments() -> None:
    source = "int x = 1; // line\n/* block\n comment */ int y = 2;"
    tokens = [token for token in lex(source, "tokens.ps") if token.kind is not TokenKind.EOF]
    assert [token.text for token in tokens] == [
        "int", "x", "=", "1", ";",
        "int", "y", "=", "2", ";",
    ]
    assert tokens[0].location == SourceLocation("tokens.ps", 1, 0)
    assert tokens[5].location == SourceLocation("tokens.ps", 3, 12)

    kinds = [
        token.kind
        for token in lex("true false ** == != <= >= += -> & | !", "ops.ps")
        if token.kind is not TokenKind.EOF
    ]
    assert kinds == [
        TokenKind.TRUE,
        TokenKind.FALSE,
        TokenKind.STAR_STAR,
        TokenKind.EQ,
        TokenKind.NE,
        TokenKind.LE,
        TokenKind.GE,
        TokenKind.PLUS_EQ,
        TokenKind.ARROW,
        TokenKind.AND,
        TokenKind.OR,
        TokenKind.NOT,
    ]


def test_literals_and_escapes() -> None:
    source = r'''a = "n\nr\rt\tz\0b\\c\'d\"e"; b = '\n'; c = 1_000_000;'''
    tokens = [token for token in lex(source, "literals.ps") if token.kind is not TokenKind.EOF]
    string_token = next(token for token in tokens if token.kind is TokenKind.STR_LIT)
    assert string_token.value == "n\nr\rt\tz\0b\\c'd\"e"
    assert [token.value for token in tokens if token.kind is TokenKind.CHAR_LIT] == [10]
    assert [token.value for token in tokens if token.kind is TokenKind.INT_LIT] == [1_000_000]


def test_lexer_errors() -> None:
    cases = [
        ('a = "abc', "строка не закрыта"),
        (r'a = "x\q"', r"неизвестная escape-последовательность \q"),
        ("int x = 1_;", "подчёркивание в числе должно стоять между цифрами"),
        ("/* x", "блочный комментарий не закрыт"),
        ("int x = @;", "неизвестный символ '@'"),
        ("char c = 'ab';", "лишние символы в char-литерале"),
        ("int x = 9999999999;", "литерал 9999999999 не помещается в 32-битный знаковый int"),
        ("char c = 'ы';", "недопустимый символ в char-литерале: код 1099"),
        ("char c = '';", "пустой char-литерал"),
    ]
    for source, expected in cases:
        with pytest.raises(TranslatorError) as info:
            lex(source, "bad.ps")
        assert info.value.message == expected, source
