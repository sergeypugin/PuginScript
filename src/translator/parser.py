"""Парсер PuginScript: токены одного файла -> AST

Include подставляется на месте директивы: вложенный файл лексируется и
разбирается рекурсивно, его элементы вставляются в общий список программы.
Повторное включение и цикл -- ошибка; путь include должен быть
относительным (без ..) и оканчиваться на `.ps` или `.h`. Первая синтаксическая
ошибка останавливает трансляцию
"""

import os
from collections.abc import Callable
from typing import NoReturn

from .errors import TranslatorError
from .lexer import INT_ABS_MIN, Token, TokenKind, lex
from .syntax_tree import (
    ArrayLiteral,
    Assignment,
    Binary,
    Block,
    BoolLiteral,
    Call,
    CharLiteral,
    ConstDecl,
    Decl,
    Expr,
    ExprStmt,
    FunctionDecl,
    Identifier,
    IfStmt,
    Index,
    IntegerLiteral,
    LValue,
    New,
    Param,
    Program,
    ReturnStmt,
    SourceLocation,
    Stmt,
    StringLiteral,
    Type,
    Unary,
    VarDecl,
    WhileStmt,
    dump,
)

_OR_OPS: dict[TokenKind, str] = {TokenKind.OR: "|"}
_AND_OPS: dict[TokenKind, str] = {TokenKind.AND: "&"}
_COMPARE_OPS: dict[TokenKind, str] = {
    TokenKind.EQ: "==",
    TokenKind.NE: "!=",
    TokenKind.LT: "<",
    TokenKind.LE: "<=",
    TokenKind.GT: ">",
    TokenKind.GE: ">=",
}
_ADD_OPS: dict[TokenKind, str] = {TokenKind.PLUS: "+", TokenKind.MINUS: "-"}
_MUL_OPS: dict[TokenKind, str] = {
    TokenKind.STAR: "*",
    TokenKind.SLASH: "/",
    TokenKind.PERCENT: "%",
}
_ASSIGN_OPS: dict[TokenKind, str] = {
    TokenKind.ASSIGN: "=",
    TokenKind.PLUS_EQ: "+=",
    TokenKind.MINUS_EQ: "-=",
    TokenKind.STAR_EQ: "*=",
    TokenKind.SLASH_EQ: "/=",
    TokenKind.PERCENT_EQ: "%=",
}
_BASE_TYPES: dict[TokenKind, str] = {
    TokenKind.INT: "int",
    TokenKind.STR: "str",
    TokenKind.BOOL: "bool",
}
_EXPECTED: dict[TokenKind, str] = {
    TokenKind.IDENT: "ожидался идентификатор",
    TokenKind.STR_LIT: "ожидался строковый литерал",
    TokenKind.SEMICOLON: "ожидалось ;",
    TokenKind.LPAREN: "ожидалось (",
    TokenKind.RPAREN: "ожидалось )",
    TokenKind.LBRACE: "ожидалось {",
    TokenKind.RBRACE: "ожидалось }",
    TokenKind.LBRACKET: "ожидалось [",
    TokenKind.RBRACKET: "ожидалось ]",
    TokenKind.ASSIGN: "ожидалось =",
    TokenKind.ARROW: "ожидалось ->",
}

# литерал 2147483648 проходит лексер только ради -2147483648 (стиль Java)
_INT_MIN_TEXT = "литерал 2147483648 допустим только в составе -2147483648"


def _describe(kind: TokenKind) -> str:
    return _EXPECTED.get(kind, "ожидался токен " + kind.name)


def _found(token: Token) -> str:
    if token.kind is TokenKind.EOF:
        return "конец файла"
    return "'" + token.text + "'"


def _base_type_name(token: Token) -> str:
    base = _BASE_TYPES.get(token.kind)
    if base is None:
        raise TranslatorError(token.location, "ожидался базовый тип: int, str или bool")
    return base


def _read_source(path: str, location: SourceLocation) -> str:
    try:
        # utf-8-sig "прозрачно" съедает BOM (Byte Order Mark)
        with open(path, "r", encoding="utf-8-sig") as source:
            return source.read()
    except OSError:
        raise TranslatorError(location, f"не удалось открыть файл {path!r}") from None
    except UnicodeDecodeError:
        raise TranslatorError(location, f"файл {path!r} не в utf-8") from None


class _FileParser:
    def __init__(self, tokens: list[Token], path: str, included: set[str]) -> None:
        self._tokens = tokens
        self._path = path
        self._included = included
        self._pos = 0

    def parse_program(self) -> Program:
        items: list[Decl | Stmt] = []
        while self._peek().kind is not TokenKind.EOF:
            kind = self._peek().kind
            if kind is TokenKind.INCLUDE:
                items.extend(self._include())
            elif kind is TokenKind.CONST:
                items.append(self._const_decl())
            elif kind is TokenKind.DEF:
                items.append(self._function_decl())
            else:
                items.append(self._statement())
        return Program(items=items)

    def _include(self) -> list[Decl | Stmt]:
        self._advance()  # include
        path_token = self._expect(TokenKind.STR_LIT)
        self._expect(TokenKind.SEMICOLON)
        raw = path_token.value
        if not isinstance(raw, str):
            raise TranslatorError(path_token.location, "путь include должен быть строкой")
        # путь include обязан вести внутрь древа исходников
        if raw == "":
            raise TranslatorError(path_token.location, "путь include не может быть пустым")
        if "\0" in raw:
            raise TranslatorError(path_token.location, "путь include содержит недопустимый символ")
        if os.path.isabs(raw) or os.path.splitdrive(raw)[0]:
            raise TranslatorError(path_token.location, f"путь include должен быть относительным: {raw!r}")
        if ".." in raw.replace("\\", "/").split("/"):
            raise TranslatorError(path_token.location, "путь include не может содержать ..")
        if os.path.splitext(raw)[1].lower() not in (".ps", ".h"):
            raise TranslatorError(path_token.location, "путь include должен заканчиваться на .ps или .h")
        target = os.path.normcase(os.path.abspath(os.path.join(os.path.dirname(self._path), raw)))
        if target in self._included:
            raise TranslatorError(path_token.location, f"файл {raw!r} уже включён")
        self._included.add(target)
        text = _read_source(target, path_token.location)
        nested = _FileParser(lex(text, target), target, self._included)
        return nested.parse_program().items

    def _const_decl(self) -> ConstDecl:
        start = self._advance()  # const
        base = _base_type_name(self._advance())
        name = self._expect(TokenKind.IDENT)
        self._expect(TokenKind.ASSIGN)
        init = self._expression()
        self._expect(TokenKind.SEMICOLON)
        return ConstDecl(
            name=name.text,
            const_type=Type(base),
            init=init,
            location=start.location,
        )

    def _function_decl(self) -> FunctionDecl:
        start = self._advance()  # def
        name = self._expect(TokenKind.IDENT)
        self._expect(TokenKind.LPAREN)
        params: list[Param] = []
        if self._peek().kind is not TokenKind.RPAREN:
            params.append(self._param())
            while self._peek().kind is TokenKind.COMMA:
                self._advance()
                params.append(self._param())
        self._expect(TokenKind.RPAREN)
        return_type: Type | None = None
        if self._peek().kind is TokenKind.ARROW:
            self._advance()
            return_type = self._type()
        body = self._block()
        return FunctionDecl(
            name=name.text,
            params=params,
            body=body,
            return_type=return_type,
            location=start.location,
        )

    def _param(self) -> Param:
        start = self._peek()
        param_type = self._type()
        name = self._expect(TokenKind.IDENT)
        return Param(name=name.text, param_type=param_type, location=start.location)

    def _type(self) -> Type:
        base_token = self._advance()
        base = _base_type_name(base_token)
        is_array = False
        if self._peek().kind is TokenKind.LBRACKET:
            self._advance()
            self._expect(TokenKind.RBRACKET)
            is_array = True
        return Type(base=base, is_array=is_array)

    def _statement(self) -> Stmt:
        kind = self._peek().kind
        if kind in _BASE_TYPES:
            return self._var_decl()
        if kind is TokenKind.IF:
            return self._if_stmt()
        if kind is TokenKind.WHILE:
            return self._while_stmt()
        if kind is TokenKind.RETURN:
            return self._return_stmt()
        if kind is TokenKind.LBRACE:
            return self._block()
        return self._expr_statement()

    def _var_decl(self) -> VarDecl:
        start = self._peek()
        var_type = self._type()
        name = self._expect(TokenKind.IDENT)
        init: Expr | None = None
        if self._peek().kind is TokenKind.ASSIGN:
            self._advance()
            init = self._expression()
        self._expect(TokenKind.SEMICOLON)
        return VarDecl(
            name=name.text, var_type=var_type, init=init, location=start.location
        )

    def _if_stmt(self) -> IfStmt:
        start = self._advance()  # if
        self._expect(TokenKind.LPAREN)
        condition = self._expression()
        self._expect(TokenKind.RPAREN)
        then_body = self._block()
        else_body: Block | IfStmt | None = None
        if self._peek().kind is TokenKind.ELSE:
            self._advance()
            if self._peek().kind is TokenKind.IF:
                else_body = self._if_stmt()
            else:
                else_body = self._block()
        return IfStmt(
            condition=condition,
            then_body=then_body,
            else_body=else_body,
            location=start.location,
        )

    def _while_stmt(self) -> WhileStmt:
        start = self._advance()  # while
        self._expect(TokenKind.LPAREN)
        condition = self._expression()
        self._expect(TokenKind.RPAREN)
        return WhileStmt(
            condition=condition, body=self._block(), location=start.location
        )

    def _return_stmt(self) -> ReturnStmt:
        start = self._advance()  # return
        if self._peek().kind is TokenKind.SEMICOLON:
            self._advance()
            return ReturnStmt(value=None, location=start.location)
        value = self._expression()
        self._expect(TokenKind.SEMICOLON)
        return ReturnStmt(value=value, location=start.location)

    def _block(self) -> Block:
        start = self._expect(TokenKind.LBRACE)
        body: list[Stmt] = []
        while self._peek().kind not in (TokenKind.RBRACE, TokenKind.EOF):
            body.append(self._statement())
        self._expect(TokenKind.RBRACE)
        return Block(body=body, location=start.location)

    def _expr_statement(self) -> Stmt:
        expr = self._expression()
        op_token = self._peek()
        if op_token.kind in _ASSIGN_OPS:
            target = self._lvalue_of(expr)
            self._advance()
            value = self._expression()
            self._expect(TokenKind.SEMICOLON)
            return Assignment(
                target=target,
                op=_ASSIGN_OPS[op_token.kind],
                value=value,
                location=expr.location,
            )
        self._expect(TokenKind.SEMICOLON)
        return ExprStmt(expr=expr, location=expr.location)

    def _lvalue_of(self, expr: Expr) -> LValue:
        if isinstance(expr, Identifier):
            return LValue(name=expr.name, location=expr.location)
        if isinstance(expr, Index) and isinstance(expr.base, Identifier):
            return LValue(name=expr.base.name, index=expr.index, location=expr.location)
        raise TranslatorError(
            expr.location,
            "слева от присваивания может стоять только переменная или элемент массива",
        )

    def _binary_level(self, ops: dict[TokenKind, str], operand: Callable[[], Expr]) -> Expr:
        left = operand()
        while True:
            token = self._peek()
            op = ops.get(token.kind)
            if op is None:
                return left
            self._advance()
            left = Binary(op=op, left=left, right=operand(), location=token.location)

    def _expression(self) -> Expr:
        return self._binary_level(_OR_OPS, self._and)

    def _and(self) -> Expr:
        return self._binary_level(_AND_OPS, self._comparison)

    def _comparison(self) -> Expr:
        left = self._term()
        token = self._peek()
        op = _COMPARE_OPS.get(token.kind)
        if op is None:
            return left
        self._advance()
        return Binary(op=op, left=left, right=self._term(), location=token.location)

    def _term(self) -> Expr:
        return self._binary_level(_ADD_OPS, self._factor)

    def _factor(self) -> Expr:
        return self._binary_level(_MUL_OPS, self._unary)

    def _unary(self) -> Expr:
        token = self._peek()
        if token.kind is TokenKind.NOT:
            self._advance()
            return Unary(op="!", operand=self._unary(), location=token.location)
        if token.kind is TokenKind.MINUS:
            literal = self._peek(1)
            if literal.kind is TokenKind.INT_LIT and literal.value == INT_ABS_MIN:
                if self._peek(2).kind is TokenKind.STAR_STAR:
                    raise TranslatorError(literal.location, _INT_MIN_TEXT)
                self._advance()
                self._advance()
                return IntegerLiteral(value=-INT_ABS_MIN, location=literal.location)
            self._advance()
            return Unary(op="-", operand=self._unary(), location=token.location)
        return self._power()

    def _power(self) -> Expr:
        base = self._primary()
        if self._peek().kind is TokenKind.STAR_STAR:
            token = self._advance()
            operand = self._peek()
            if operand.kind in (TokenKind.MINUS, TokenKind.NOT):
                raise TranslatorError(
                    operand.location,
                    "операнд ** не может быть унарным выражением, используйте скобки",
                )
            return Binary(
                op="**", left=base, right=self._power(), location=token.location
            )
        return base

    def _primary(self) -> Expr:
        token = self._peek()
        if token.kind is TokenKind.INT_LIT:
            self._advance()
            value = token.value
            if not isinstance(value, int):
                raise TranslatorError(token.location, "ожидалось число")
            if value == INT_ABS_MIN:
                raise TranslatorError(token.location, _INT_MIN_TEXT)
            return IntegerLiteral(value=value, location=token.location)
        if token.kind is TokenKind.STR_LIT:
            self._advance()
            value = token.value
            if not isinstance(value, str):
                raise TranslatorError(token.location, "ожидалась строка")
            return StringLiteral(value=value, location=token.location)
        if token.kind is TokenKind.CHAR_LIT:
            self._advance()
            code = token.value
            if not isinstance(code, int):
                raise TranslatorError(token.location, "ожидался символ")
            return CharLiteral(code=code, location=token.location)
        if token.kind is TokenKind.TRUE or token.kind is TokenKind.FALSE:
            self._advance()
            return BoolLiteral(value=token.kind is TokenKind.TRUE, location=token.location)
        if token.kind is TokenKind.NEW:
            self._advance()
            base = _base_type_name(self._advance())
            self._expect(TokenKind.LBRACKET)
            size = self._expression()
            self._expect(TokenKind.RBRACKET)
            return New(base=base, size=size, location=token.location)
        if token.kind is TokenKind.LPAREN:
            self._advance()
            inner = self._expression()
            self._expect(TokenKind.RPAREN)
            return inner
        if token.kind is TokenKind.LBRACKET:
            return self._array_literal()
        if token.kind is TokenKind.IDENT:
            self._advance()
            return self._ident_tail(token)
        raise TranslatorError(token.location, f"ожидалось выражение, найдено {_found(token)}")

    def _ident_tail(self, name_token: Token) -> Expr:
        after = self._peek()
        if after.kind is TokenKind.LPAREN:
            self._advance()
            args: list[Expr] = []
            if self._peek().kind is not TokenKind.RPAREN:
                args.append(self._expression())
                while self._peek().kind is TokenKind.COMMA:
                    self._advance()
                    args.append(self._expression())
            self._expect(TokenKind.RPAREN)
            return Call(name=name_token.text, args=args, location=name_token.location)
        if after.kind is TokenKind.LBRACKET:
            self._advance()
            index = self._expression()
            self._expect(TokenKind.RBRACKET)
            return Index(
                base=Identifier(name=name_token.text, location=name_token.location),
                index=index,
                location=name_token.location,
            )
        return Identifier(name=name_token.text, location=name_token.location)

    def _array_literal(self) -> Expr:
        start = self._advance()  # [
        if self._peek().kind is TokenKind.RBRACKET:
            raise TranslatorError(
                self._peek().location,
                "пустой литерал массива не поддерживается, используйте new int[0]",
            )
        items = [self._expression()]
        while self._peek().kind is TokenKind.COMMA:
            self._advance()
            items.append(self._expression())
        self._expect(TokenKind.RBRACKET)
        return ArrayLiteral(items=items, location=start.location)

    def _peek(self, offset: int = 0) -> Token:
        if offset < 0:
            raise ValueError("Отрицательное смещение: парсер идёт только вперёд")
        index = self._pos + offset
        if index >= len(self._tokens):
            return self._tokens[-1]
        return self._tokens[index]

    def _advance(self) -> Token:
        token = self._peek()
        if token.kind is not TokenKind.EOF:
            self._pos += 1
        return token

    def _expect(self, kind: TokenKind) -> Token:
        token = self._peek()
        if token.kind is not kind:
            self._error(f"{_describe(kind)}, найдено {_found(token)}")
        return self._advance()

    def _error(self, message: str) -> NoReturn:
        raise TranslatorError(self._peek().location, message)


def parse(file_path: str) -> Program:
    path = os.path.normcase(os.path.abspath(file_path))
    text = _read_source(path, SourceLocation(file_path, 1, 0))
    included = {path}
    return _FileParser(lex(text, path), path, included).parse_program()


def parse_text(text: str, file_name: str) -> Program:
    path = os.path.normcase(os.path.abspath(file_name))
    return _FileParser(lex(text, path), path, {path}).parse_program()


if __name__ == "__main__":
    demo_path = os.path.join(os.path.dirname(__file__), "..", "..", "examples", "hello.ps")
    print(dump(parse(demo_path)))
