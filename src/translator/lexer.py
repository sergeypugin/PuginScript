"""Лексер PuginScript: текст одного файла -> список токенов

- Include обрабатывает parser, поэтому лексер получает текст одного файла
- Пробелы и комментарии пропускаются
- Первая ошибка завершает трансляцию.
"""

from dataclasses import dataclass
from enum import Enum, auto
from typing import NoReturn

from .errors import TranslatorError
from .syntax_tree import SourceLocation


class TokenKind(Enum):
    EOF = auto()
    IDENT = auto()
    INT_LIT = auto()
    STR_LIT = auto()
    CHAR_LIT = auto()

    INT = auto()
    STR = auto()
    BOOL = auto()
    DEF = auto()
    CONST = auto()
    INCLUDE = auto()
    IF = auto()
    ELSE = auto()
    WHILE = auto()
    RETURN = auto()
    NEW = auto()
    TRUE = auto()
    FALSE = auto()

    PLUS = auto()
    MINUS = auto()
    STAR = auto()
    SLASH = auto()
    PERCENT = auto()
    STAR_STAR = auto()
    ASSIGN = auto()
    EQ = auto()
    NE = auto()
    LT = auto()
    LE = auto()
    GT = auto()
    GE = auto()
    AND = auto()
    OR = auto()
    NOT = auto()
    PLUS_EQ = auto()
    MINUS_EQ = auto()
    STAR_EQ = auto()
    SLASH_EQ = auto()
    PERCENT_EQ = auto()
    ARROW = auto()
    COMMA = auto()
    SEMICOLON = auto()
    # скобки, префиксы L и R -- левая и правая:
    # круглые -- PAREN (parenthesis)
    LPAREN = auto()
    RPAREN = auto()
    # фигурные -- BRACE (brace)
    LBRACE = auto()
    RBRACE = auto()
    # квадратные -- BRACKET (square bracket)
    LBRACKET = auto()
    RBRACKET = auto()


KEYWORDS: dict[str, TokenKind] = {
    "int": TokenKind.INT,
    "str": TokenKind.STR,
    "bool": TokenKind.BOOL,
    "def": TokenKind.DEF,
    "const": TokenKind.CONST,
    "include": TokenKind.INCLUDE,
    "if": TokenKind.IF,
    "else": TokenKind.ELSE,
    "while": TokenKind.WHILE,
    "return": TokenKind.RETURN,
    "new": TokenKind.NEW,
    "true": TokenKind.TRUE,
    "false": TokenKind.FALSE,
}

TWO_CHAR_OPS: dict[str, TokenKind] = {
    "==": TokenKind.EQ,
    "!=": TokenKind.NE,
    "<=": TokenKind.LE,
    ">=": TokenKind.GE,
    "+=": TokenKind.PLUS_EQ,
    "-=": TokenKind.MINUS_EQ,
    "*=": TokenKind.STAR_EQ,
    "/=": TokenKind.SLASH_EQ,
    "%=": TokenKind.PERCENT_EQ,
    "**": TokenKind.STAR_STAR,
    "->": TokenKind.ARROW,
}

ONE_CHAR_OPS: dict[str, TokenKind] = {
    "+": TokenKind.PLUS,
    "-": TokenKind.MINUS,
    "*": TokenKind.STAR,
    "/": TokenKind.SLASH,
    "%": TokenKind.PERCENT,
    "<": TokenKind.LT,
    ">": TokenKind.GT,
    "&": TokenKind.AND,
    "|": TokenKind.OR,
    "!": TokenKind.NOT,
    "=": TokenKind.ASSIGN,
    "(": TokenKind.LPAREN,
    ")": TokenKind.RPAREN,
    "{": TokenKind.LBRACE,
    "}": TokenKind.RBRACE,
    "[": TokenKind.LBRACKET,
    "]": TokenKind.RBRACKET,
    ",": TokenKind.COMMA,
    ";": TokenKind.SEMICOLON,
}

ESCAPES: dict[str, str] = {
    "n": "\n",
    "r": "\r",
    "t": "\t",
    "0": "\0",
    "\\": "\\",
    "'": "'",
    '"': '"',
}

# модуль INT_MIN; допустим только как операнд унарного минуса (стиль Java), это проверит parser
INT_ABS_MIN = 2**31


@dataclass(frozen=True)
class Token:
    kind: TokenKind
    text: str
    value: str | int | None  # расшифрованное содержимое литерала (char -- код, вне литералов -- None)
    location: SourceLocation


class Lexer:
    def __init__(self, text: str, file_name: str) -> None:
        self._text = text
        self._file = file_name
        self._pos = 0
        self._line = 1
        self._col = 0

    def tokens(self) -> list[Token]:
        result: list[Token] = []
        while True:
            token = self._next()
            result.append(token)
            if token.kind is TokenKind.EOF:
                return result

    def _next(self) -> Token:
        self._skip()
        location = self._here()
        ch = self._peek()
        if ch == "":
            return Token(TokenKind.EOF, "", None, location)
        if self._is_word_start(ch):
            return self._word()
        if self._is_digit(ch):  # первый символ уже не '_'
            return self._number()
        if ch == '"':
            return self._string()
        if ch == "'":
            return self._char()
        pair = self._text[self._pos : self._pos + 2]
        kind = TWO_CHAR_OPS.get(pair)
        if kind is not None:
            self._pos += 2
            return Token(kind, pair, None, location)
        kind = ONE_CHAR_OPS.get(ch)
        if kind is not None:
            self._step()
            return Token(kind, ch, None, location)
        self._error(f"неизвестный символ {ch!r}")

    def _skip(self) -> None:
        while True:
            ch = self._peek()
            if ch in (" ", "\t", "\r", "\n"):
                self._step()
            elif ch == "/" and self._peek(1) == "/":
                self._step()
                self._step()
                while self._peek() not in ("\n", ""):
                    self._step()
            elif ch == "/" and self._peek(1) == "*":
                location = self._here()  # чтобы знать, где комментарий начинался
                self._step()
                self._step()
                while not (self._peek() == "*" and self._peek(1) == "/"):
                    if self._peek() == "":
                        raise TranslatorError(location, "блочный комментарий не закрыт")
                    self._step()
                self._step()
                self._step()
            else:
                return

    def _word(self) -> Token:
        location = self._here()
        start = self._pos
        while self._is_word_char(self._peek()):
            self._step()
        text = self._text[start : self._pos]
        kind = KEYWORDS.get(text, TokenKind.IDENT)
        return Token(kind, text, None, location)

    def _number(self) -> Token:
        # вызывается только с цифры в текущей позиции,
        # т.е. с '_' слово не начинается
        location = self._here()
        start = self._pos
        while True:
            ch = self._peek()
            if self._is_digit(ch):
                self._step()
            elif ch == "_" and self._is_digit(self._peek(1)):
                self._step()
                self._step()
            elif ch == "_":
                self._error("подчёркивание в числе должно стоять между цифрами")
            else:
                break
        text = self._text[start : self._pos]
        value = int(text.replace("_", ""))
        if value > INT_ABS_MIN:
            self._error(f"литерал {text} не помещается в 32-битный знаковый int")
        return Token(TokenKind.INT_LIT, text, value, location)

    def _string(self) -> Token:
        location = self._here()
        self._step()
        raw: list[str] = ['"']
        value: list[str] = []
        while True:
            ch = self._peek()
            if ch == "" or ch in ("\n", "\r"):
                raise TranslatorError(location, "строка не закрыта")
            if ch == '"':
                self._step()
                raw.append('"')
                break
            if ch == "\\":
                self._step()
                esc = self._peek()
                if esc == "" or esc in ("\n", "\r"):
                    raise TranslatorError(location, "строка не закрыта")
                decoded = ESCAPES.get(esc)
                if decoded is None:
                    self._error(f"неизвестная escape-последовательность \\{esc}")
                self._step()
                raw.append("\\" + esc)
                value.append(decoded)
            else:
                if not (" " <= ch <= "~"):  # В ASCII меньше только непечатаемые символы, а больше -- только DEL
                    self._error(f"недопустимый символ в строке: код {ord(ch)}")
                self._step()
                raw.append(ch)
                value.append(ch)
        return Token(TokenKind.STR_LIT, "".join(raw), "".join(value), location)

    def _char(self) -> Token:
        location = self._here()
        self._step()
        ch = self._peek()
        if ch == "" or ch in ("\n", "\r"):
            raise TranslatorError(location, "char-литерал не закрыт")
        if ch == "'":
            self._error("пустой char-литерал")
        if ch == "\\":
            self._step()
            esc = self._peek()
            if esc == "" or esc in ("\n", "\r"):
                raise TranslatorError(location, "char-литерал не закрыт")
            decoded = ESCAPES.get(esc)
            if decoded is None:
                self._error(f"неизвестная escape-последовательность \\{esc}")
            code = ord(decoded)
            raw = "\\" + esc
            self._step()
        else:
            if not (" " <= ch <= "~"):
                self._error(f"недопустимый символ в char-литерале: код {ord(ch)}")
            code = ord(ch)
            raw = ch
            self._step()
        if self._peek() == "":
            self._error("char-литерал не закрыт")
        if self._peek() != "'":
            self._error("лишние символы в char-литерале")
        self._step()
        return Token(TokenKind.CHAR_LIT, "'" + raw + "'", code, location)

    def _peek(self, offset: int = 0) -> str:
        index = self._pos + offset
        if index >= len(self._text):
            return ""
        return self._text[index]

    def _step(self) -> None:
        ch = self._text[self._pos]
        self._pos += 1
        if ch == "\n":
            self._line += 1
            self._col = 0
        else:
            self._col += 1

    def _here(self) -> SourceLocation:
        return SourceLocation(self._file, self._line, self._col)

    def _error(self, message: str) -> NoReturn:
        raise TranslatorError(self._here(), message)

    @staticmethod
    def _is_word_start(ch: str) -> bool:
        return "a" <= ch <= "z" or "A" <= ch <= "Z" or ch == "_"

    @staticmethod
    def _is_word_char(ch: str) -> bool:
        return Lexer._is_word_start(ch) or Lexer._is_digit(ch)

    @staticmethod
    def _is_digit(ch: str) -> bool:
        return "0" <= ch <= "9"


def lex(text: str, file_name: str) -> list[Token]:
    return Lexer(text, file_name).tokens()


if __name__ == "__main__":
    sample = (
"""
include "constants.h";
const int trash = 1_234;
def main() -> int {
    str greeting = "Hello, \\t\\"my friend!\\0";
    int trash2 = 'x';
    /* комментарий на
    несколько строк */
    int p = 2 ** 10;
    while (p > 0) { p /= 2; }
    return 0; // ещё один комментарий
}
"""
    )
    for token in lex(sample, "demo.ps"):
        tail = "" if token.value is None else f" value={token.value!r}"
        print(
            f"{token.location.file}:{token.location.line:2}:{token.location.column:2}:"
            f" {token.kind.name:10} {token.text!r}{tail}"
        )
