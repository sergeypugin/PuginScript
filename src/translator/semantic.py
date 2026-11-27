"""Семантический анализ PuginScript: имена, типы, константы, точка входа

Парсер останавливается на первой ошибке, семантика собирает все ошибки.
Неизвестное или уже ошибочное выражение даёт тип None: он подавляет каскад
повторных сообщений об одной проблеме.
"""

import os
from collections.abc import Callable
from dataclasses import dataclass

from .errors import TranslatorError
from .parser import parse
from .syntax_tree import (
    ArrayLiteral,
    Assignment,
    Binary,
    Block,
    BoolLiteral,
    Call,
    CharLiteral,
    ConstDecl,
    Expr,
    ExprStmt,
    FunctionDecl,
    Identifier,
    IfStmt,
    Index,
    IntegerLiteral,
    New,
    Program,
    ReturnStmt,
    SourceLocation,
    Stmt,
    StringLiteral,
    Type,
    Unary,
    VarDecl,
    WhileStmt,
)

INT = Type("int")
BOOL = Type("bool")
STR = Type("str")

def _int_only(t: Type) -> bool:
    return t == INT


def _printable(t: Type) -> bool:
    return not t.is_array


def _has_length(t: Type) -> bool:
    return t == STR or t.is_array


@dataclass(frozen=True)
class _Builtin:
    """Сигнатура встроенной функции
    (_BUILTINS -- единственное место, знающее о них):
    - __init__ объявляет функции в globals по словарю _BUILTINS, метод _builtin проверяет вызовы по ним
    - arg -- проверка типа единственного аргумента, None -- аргументов нет
    - hint -- ожидаемый тип аргумента при выводе выражения
    - reject -- текст ошибки при несоответствии
    - optional разрешает println() без аргументов.
    """

    arg: Callable[[Type], bool] | None
    hint: Type | None
    returns: Type | None
    reject: str = ""
    optional: bool = False


_BUILTINS: dict[str, _Builtin] = {
    "print": _Builtin(arg=_printable, hint=None, returns=None, reject="не печатает массивы"),
    "println": _Builtin(arg=_printable, hint=None, returns=None, reject="не печатает массивы", optional=True),
    "print_char": _Builtin(arg=_int_only, hint=INT, returns=None, reject="ожидался int, получен {t}"),
    "len": _Builtin(arg=_has_length, hint=None, returns=INT, reject="применяется к строкам и массивам, получен {t}"),
    "input": _Builtin(arg=None, hint=None, returns=STR),
    "input_int": _Builtin(arg=None, hint=None, returns=INT),
    "input_char": _Builtin(arg=None, hint=None, returns=INT),
}


def _wrap32(value: int) -> int:
    return (value + 2**31) % 2**32 - 2**31


def _div_trunc(a: int, b: int) -> int:
    quot = abs(a) // abs(b)
    if (a < 0) != (b < 0):
        quot = -quot
    return quot


def _mod_trunc(a: int, b: int) -> int:
    return a - _div_trunc(a, b) * b


def _pow32(a: int, b: int) -> int:
    r = pow(a, b, 2**32)
    return r - 2**32 if r >= 2**31 else r


def _default_value(t: Type) -> int | bool | str:
    if t == BOOL:
        return False
    if t == STR:
        return ""
    return 0


@dataclass
class ConstSymbol:
    name: str
    type: Type
    value: int | bool | str


@dataclass(eq=False)
class VarSymbol:
    name: str
    type: Type


@dataclass
class FuncSymbol:
    name: str
    params: list[Type]
    return_type: Type | None  # None -- процедура
    builtin: bool = False


Symbol = ConstSymbol | VarSymbol | FuncSymbol


class Scope:
    def __init__(self, parent: Scope | None = None) -> None:
        self.parent = parent
        self._symbols: dict[str, Symbol] = {}

    def declare(self, symbol: Symbol) -> bool:
        if symbol.name in self._symbols:
            return False
        self._symbols[symbol.name] = symbol
        return True

    def resolve(self, name: str) -> Symbol | None:
        scope: Scope | None = self
        while scope is not None:
            found = scope._symbols.get(name)
            if found is not None:
                return found
            scope = scope.parent
        return None


@dataclass
class SemResult:
    errors: list[TranslatorError]
    globals: Scope  # встроенные функции, пользовательские функции и константы
    script: Scope  # верхнеуровневые переменные; функции их не видят
    main: FunctionDecl | None  # None -- скриптовый режим


class _Checker:
    def __init__(self) -> None:
        self.errors: list[TranslatorError] = []
        self.globals = Scope()
        self.script = Scope(self.globals)
        self._func: FunctionDecl | None = None
        self._initialized_vars: set[VarSymbol] = set()
        for name in _BUILTINS:
            self.globals.declare(
                FuncSymbol(name=name, params=[], return_type=None, builtin=True)
            )

    def _error(self, location: SourceLocation, message: str) -> None:
        self.errors.append(TranslatorError(location, message))

    def run(self, program: Program) -> SemResult:
        # проход 1: константы по порядку объявления, функции поднимаются наверх
        functions: list[FunctionDecl] = []
        for item in program.items:
            if isinstance(item, ConstDecl):
                self._const_decl(item)
            elif isinstance(item, FunctionDecl):
                functions.append(item)
                symbol = FuncSymbol(
                    item.name, [p.param_type for p in item.params], item.return_type
                )
                if not self.globals.declare(symbol):
                    self._error(item.location, f"повторное объявление имени '{item.name}'")
        # проход 2: верхний уровень в порядке следования
        for item in program.items:
            if isinstance(item, (ConstDecl, FunctionDecl)):
                continue
            if isinstance(item, Stmt):
                self._stmt(item, self.script)
        # проход 3: тела функций
        main: FunctionDecl | None = None
        for d in functions:
            self._check_function(d)
            if d.name == "main" and main is None:
                main = d
                self._check_main(d)
        return SemResult(self.errors, self.globals, self.script, main)

    def _check_main(self, d: FunctionDecl) -> None:
        if d.params:
            self._error(d.location, "main не принимает параметров")
        if d.return_type is not None and d.return_type != INT:
            self._error(d.location, "main должен возвращать int или быть процедурой")

    def _check_function(self, d: FunctionDecl) -> None:
        scope = Scope(self.globals)
        for p in d.params:
            if not scope.declare(VarSymbol(p.name, p.param_type)):
                self._error(p.location, f"повторное объявление параметра '{p.name}'")
        self._func = d
        previous_initialized = self._initialized_vars
        initialized: set[VarSymbol] = set()
        for p in d.params:
            symbol = scope.resolve(p.name)
            if isinstance(symbol, VarSymbol):
                initialized.add(symbol)
        self._initialized_vars = initialized
        for stmt in d.body.body:
            self._stmt(stmt, scope)
        self._initialized_vars = previous_initialized
        self._func = None
        if d.return_type is not None and not self._returns_always(d.body):
            self._error(
                d.location,
                f"функция '{d.name}' должна вернуть {d.return_type} на всех путях исполнения",
            )

    def _returns_always(self, block: Block) -> bool:
        for stmt in block.body:
            if self._stmt_returns(stmt):
                return True
        return False

    def _stmt_returns(self, s: Stmt) -> bool:
        if isinstance(s, ReturnStmt):
            return True
        if isinstance(s, Block):
            return self._returns_always(s)
        if isinstance(s, IfStmt):
            if s.else_body is None:
                return False
            if not self._returns_always(s.then_body):
                return False
            if isinstance(s.else_body, Block):
                return self._returns_always(s.else_body)
            return self._stmt_returns(s.else_body)
        return False

    def _stmt(self, s: Stmt, scope: Scope) -> None:
        if isinstance(s, VarDecl):
            self._var_decl(s, scope)
        elif isinstance(s, Assignment):
            self._assign(s, scope)
        elif isinstance(s, IfStmt):
            self._if(s, scope)
        elif isinstance(s, WhileStmt):
            self._while(s, scope)
        elif isinstance(s, ReturnStmt):
            self._return(s, scope)
        elif isinstance(s, ExprStmt):
            self._expr_stmt(s, scope)
        elif isinstance(s, Block):
            self._block(s, scope)
        else:
            raise TypeError("unknown statement: " + type(s).__name__)

    def _block(self, b: Block, scope: Scope) -> None:
        inner = Scope(scope)
        for stmt in b.body:
            self._stmt(stmt, inner)

    def _if(self, s: IfStmt, scope: Scope) -> None:
        self._condition(s.condition, scope)
        before = self._initialized_vars.copy()
        self._block(s.then_body, scope)
        then_initialized = self._initialized_vars.copy()
        if isinstance(s.else_body, Block):
            self._initialized_vars = before.copy()
            self._block(s.else_body, scope)
            self._initialized_vars.intersection_update(then_initialized)
        elif isinstance(s.else_body, IfStmt):
            self._initialized_vars = before.copy()
            self._if(s.else_body, scope)
            self._initialized_vars.intersection_update(then_initialized)
        else:
            self._initialized_vars.intersection_update(before)

    def _while(self, s: WhileStmt, scope: Scope) -> None:
        self._condition(s.condition, scope)
        before = self._initialized_vars.copy()
        self._block(s.body, scope)
        self._initialized_vars = before

    def _condition(self, expr: Expr, scope: Scope) -> None:
        t = self._expr(expr, scope)
        if t is not None and t != BOOL:
            self._error(expr.location, f"условие должно быть bool, получен {t}")

    def _return(self, s: ReturnStmt, scope: Scope) -> None:
        func = self._func
        if func is None:
            # return на верхнем уровне завершает программу
            if s.value is None:
                return
            t = self._expr(s.value, scope, INT)
            if t is not None and t != INT:
                self._error(s.value.location, f"код выхода должен быть int, получен {t}")
            return
        ret = func.return_type
        if ret is None:
            if s.value is not None:
                self._error(s.location, "процедура не возвращает значение")
            return
        if s.value is None:
            self._error(s.location, f"функция должна вернуть значение типа {ret}")
            return
        t = self._expr(s.value, scope, ret)
        if t is not None and t != ret:
            self._error(
                s.value.location, f"возвращаемое значение: ожидался {ret}, получен {t}"
            )

    def _expr_stmt(self, s: ExprStmt, scope: Scope) -> None:
        expr = s.expr
        if isinstance(expr, Call):
            sym = scope.resolve(expr.name)
            if isinstance(sym, FuncSymbol) and sym.return_type is None:
                self._call(expr, scope)  # вызов процедуры как оператор
                return
        self._expr(expr, scope)

    def _assign(self, s: Assignment, scope: Scope) -> None:
        sym = scope.resolve(s.target.name)
        if sym is None:
            self._error(s.target.location, f"неизвестное имя '{s.target.name}'")
            return
        if isinstance(sym, ConstSymbol):
            self._error(s.target.location, f"нельзя присваивать константе '{s.target.name}'")
            return
        if not isinstance(sym, VarSymbol):
            self._error(s.target.location, f"'{s.target.name}' не является переменной")
            return
        target = sym.type
        if s.target.index is not None:
            self._read_var(s.target.name, sym, s.target.location)
            if target == STR:
                self._error(s.target.location, "строку нельзя изменять по индексу")
                return
            if not target.is_array:
                self._error(s.target.location, "индексация применяется только к массивам")
                return
            idx = self._expr(s.target.index, scope, INT)
            if idx is not None and idx != INT:
                self._error(s.target.index.location, f"индекс должен быть int, получен {idx}")
            target = Type(target.base)
        if s.op == "=":
            got = self._expr(s.value, scope, target)
            if got is not None and got != target:
                self._error(s.value.location, f"присваивание: ожидался {target}, получен {got}")
            if s.target.index is None:
                self._initialized_vars.add(sym)
            return
        self._read_var(s.target.name, sym, s.target.location)
        if target != INT:
            self._error(s.target.location, f"операция '{s.op}' определена только для int")
            return
        got = self._expr(s.value, scope, INT)
        if got is not None and got != INT:
            self._error(s.value.location, f"операция '{s.op}': ожидался int, получен {got}")

    def _var_decl(self, d: VarDecl, scope: Scope) -> None:
        if scope is self.script:
            # верхнеуровневая переменная делит пространство имён с функциями
            # и константами; локальная в функции может их затенять
            above = self.globals.resolve(d.name)
            if isinstance(above, (ConstSymbol, FuncSymbol)):
                self._error(d.location, f"повторное объявление имени '{d.name}'")
        if d.init is not None:
            init = self._expr(d.init, scope, d.var_type)
            if init is not None and init != d.var_type:
                self._error(
                    d.location, f"инициализатор '{d.name}': ожидался {d.var_type}, получен {init}"
                )
        symbol = VarSymbol(d.name, d.var_type)
        if not scope.declare(symbol):
            self._error(d.location, f"повторное объявление '{d.name}' в одной области видимости")
        elif d.init is not None:
            self._initialized_vars.add(symbol)

    def _expr(self, e: Expr, scope: Scope, expected: Type | None = None) -> Type | None:
        if isinstance(e, IntegerLiteral):
            return INT
        if isinstance(e, CharLiteral):
            return INT
        if isinstance(e, BoolLiteral):
            return BOOL
        if isinstance(e, StringLiteral):
            return STR
        if isinstance(e, Identifier):
            return self._ident(e, scope)
        if isinstance(e, ArrayLiteral):
            return self._array_literal(e, scope, expected)
        if isinstance(e, New):
            return self._new(e, scope)
        if isinstance(e, Index):
            return self._index(e, scope)
        if isinstance(e, Call):
            return self._call(e, scope, True)
        if isinstance(e, Unary):
            return self._unary(e, scope)
        if isinstance(e, Binary):
            return self._binary(e, scope)
        raise TypeError("unknown expression: " + type(e).__name__)

    def _read_var(self, name: str, symbol: VarSymbol, location: SourceLocation) -> None:
        if symbol not in self._initialized_vars:
            self._error(location, f"переменная '{name}' не инициализирована")

    def _ident(self, e: Identifier, scope: Scope) -> Type | None:
        sym = scope.resolve(e.name)
        if sym is None:
            self._error(e.location, f"неизвестное имя '{e.name}'")
            return None
        if isinstance(sym, VarSymbol):
            self._read_var(e.name, sym, e.location)
            return sym.type
        if isinstance(sym, ConstSymbol):
            return sym.type
        self._error(e.location, f"функция '{e.name}' использована как значение")
        return None

    def _array_literal(
        self, e: ArrayLiteral, scope: Scope, expected: Type | None
    ) -> Type | None:
        if expected is None:
            self._error(
                e.location,
                "тип литерала массива нельзя вывести, укажите тип переменной или параметра",
            )
            return None
        if not expected.is_array:
            self._error(e.location, f"литерал массива не подходит для типа {expected}")
            return None
        elem = Type(expected.base)
        for item in e.items:
            got = self._expr(item, scope, elem)
            if got is not None and got != elem:
                self._error(
                    item.location,
                    f"элемент массива: ожидался {expected.base}, получен {got}",
                )
        return expected

    def _constant_int_value(self, e: Expr, scope: Scope) -> int | None:
        if isinstance(e, IntegerLiteral):
            return e.value
        if isinstance(e, CharLiteral):
            return e.code
        if isinstance(e, Identifier):
            symbol = scope.resolve(e.name)
            if isinstance(symbol, ConstSymbol) and symbol.type == INT:
                return int(symbol.value)
            return None
        if isinstance(e, Unary) and e.op == "-":
            value = self._constant_int_value(e.operand, scope)
            return None if value is None else _wrap32(-value)
        if not isinstance(e, Binary) or e.op not in ("+", "-", "*", "/", "%", "**"):
            return None
        left = self._constant_int_value(e.left, scope)
        right = self._constant_int_value(e.right, scope)
        if left is None or right is None:
            return None
        if e.op == "+":
            return _wrap32(left + right)
        if e.op == "-":
            return _wrap32(left - right)
        if e.op == "*":
            return _wrap32(left * right)
        if e.op == "/" or e.op == "%":
            if right == 0:
                return None
            if e.op == "/":
                return _wrap32(_div_trunc(left, right))
            return _wrap32(_mod_trunc(left, right))
        if e.op == "**":
            if right < 0:
                return None
            return _pow32(left, right)
        return None

    def _new(self, e: New, scope: Scope) -> Type | None:
        size = self._expr(e.size, scope, INT)
        if size is not None:
            if size == INT:
                constant_size = self._constant_int_value(e.size, scope)
                if constant_size is not None and constant_size < 0:
                    self._error(e.size.location, "размер массива не может быть отрицательным")
            else:
                self._error(e.size.location, f"размер массива должен быть int, получен {size}")
        return Type(e.base, True)

    def _index(self, e: Index, scope: Scope) -> Type | None:
        base = self._expr(e.base, scope)
        idx = self._expr(e.index, scope, INT)
        if idx is not None and idx != INT:
            self._error(e.index.location, f"индекс должен быть int, получен {idx}")
        if base is None:
            return None
        if base.is_array:
            return Type(base.base)
        if base == STR:
            return INT  # код байта, терминатор даёт 0
        self._error(e.base.location, "индексация применяется только к массивам и строкам")
        return None

    def _call(self, e: Call, scope: Scope, value_context: bool = False) -> Type | None:
        sym = scope.resolve(e.name)
        if sym is None:
            self._error(e.location, f"неизвестная функция '{e.name}'")
            return None
        if not isinstance(sym, FuncSymbol):
            self._error(e.location, f"'{e.name}' не является функцией")
            return None
        errors_before = len(self.errors)
        if sym.builtin:
            ret = self._builtin(e, scope)
        else:
            if len(e.args) != len(sym.params):
                self._error(
                    e.location,
                    f"функция '{e.name}': ожидалось {len(sym.params)} аргументов, получено {len(e.args)}",
                )
            for i, arg in enumerate(e.args):
                if i >= len(sym.params):
                    break
                expected = sym.params[i]
                got = self._expr(arg, scope, expected)
                if got is not None and got != expected:
                    self._error(
                        arg.location,
                        f"аргумент {i + 1} функции '{e.name}': ожидался {expected}, получен {got}",
                    )
            ret = sym.return_type
        if value_context and ret is None and len(self.errors) == errors_before:
            self._error(e.location, f"'{e.name}' не возвращает значения")
        return ret

    def _builtin(self, e: Call, scope: Scope) -> Type | None:
        name = e.name
        spec = _BUILTINS[name]
        check = spec.arg
        if check is None:
            if e.args:
                self._error(e.location, f"'{name}' не принимает аргументов")
            return spec.returns
        if len(e.args) > 1:
            self._error(
                e.location,
                f"'{name}' принимает не больше одного аргумента, получено {len(e.args)}",
            )
            return spec.returns
        if not e.args:
            if spec.optional:  # println() печатает только перевод строки
                return spec.returns
            self._error(e.location, f"'{name}': ожидался 1 аргумент, получено 0")
            return spec.returns
        got = self._expr(e.args[0], scope, spec.hint)
        if got is not None and not check(got):
            self._error(e.args[0].location, f"'{name}': " + spec.reject.format(t=got))
        return spec.returns

    def _unary(self, e: Unary, scope: Scope) -> Type | None:
        t = self._expr(e.operand, scope)
        if t is None:
            return None
        if e.op == "!":
            if t != BOOL:
                self._error(e.location, f"операция '!': ожидался bool, получен {t}")
                return None
            return BOOL
        if t != INT:
            self._error(e.location, f"унарный минус: ожидался int, получен {t}")
            return None
        return INT

    def _binary(self, e: Binary, scope: Scope) -> Type | None:
        left = self._expr(e.left, scope)
        right = self._expr(e.right, scope)
        if left is None or right is None:
            return None
        op = e.op
        if op == "+":
            if left.is_array or right.is_array:
                self._error(e.location, "конкатенация массивов не поддерживается")
                return None
            if left == INT and right == INT:
                return INT
            if left.base == "str" and right.base in ("int", "bool", "str"):
                return STR
            if right.base == "str" and left.base in ("int", "bool"):
                return STR
            self._error(e.location, f"операция '+': несовместимые типы {left} и {right}")
            return None
        if op in ("-", "*", "/", "%", "**"):
            if left == INT and right == INT:
                return INT
            self._error(
                e.location,
                f"операция '{op}' определена только для int, получены {left} и {right}",
            )
            return None
        if op in ("&", "|"):
            if left == BOOL and right == BOOL:
                return BOOL
            self._error(
                e.location,
                f"операция '{op}' определена только для bool, получены {left} и {right}",
            )
            return None
        if op in ("<", "<=", ">", ">="):
            if left == INT and right == INT:
                return BOOL
            self._error(
                e.location,
                f"операция '{op}' определена только для int, получены {left} и {right}",
            )
            return None
        # == и !=
        if left.is_array or right.is_array:
            self._error(e.location, "сравнение массивов через '==' и '!=' запрещено")
            return BOOL
        if left == right:
            return BOOL
        self._error(e.location, f"сравнение {left} и {right} не определено")
        return BOOL

    def _const_decl(self, d: ConstDecl) -> None:
        if self.globals.resolve(d.name) is not None:
            self._error(d.location, f"повторное объявление имени '{d.name}'")
            return
        got = self._const_expr(d.init)
        # при ошибке объявляем с нейтральным значением заявленного типа,
        # чтобы ссылки на константу не давали каскад неизвестных имён
        value = _default_value(d.const_type)
        if got is not None:
            c_type, eval_value = got
            if c_type != d.const_type:
                self._error(
                    d.location,
                    f"константа '{d.name}': ожидался {d.const_type}, получен {c_type}",
                )
            else:
                value = eval_value
        self.globals.declare(ConstSymbol(d.name, d.const_type, value))

    def _const_expr(self, e: Expr) -> tuple[Type, int | bool | str] | None:
        if isinstance(e, IntegerLiteral):
            return (INT, e.value)
        if isinstance(e, CharLiteral):
            return (INT, e.code)
        if isinstance(e, BoolLiteral):
            return (BOOL, e.value)
        if isinstance(e, StringLiteral):
            return (STR, e.value)
        if isinstance(e, Identifier):
            sym = self.globals.resolve(e.name)
            if sym is None:
                self._error(e.location, f"неизвестное имя '{e.name}' в инициализаторе const")
                return None
            if isinstance(sym, ConstSymbol):
                return (sym.type, sym.value)
            self._error(e.location, "инициализатор const может ссылаться только на константы")
            return None
        if isinstance(e, Unary):
            got = self._const_expr(e.operand)
            if got is None:
                return None
            t, v = got
            if e.op == "!":
                if t != BOOL:
                    self._error(e.location, f"операция '!': ожидался bool, получен {t}")
                    return None
                assert isinstance(v, bool)
                return (BOOL, not v)
            if t != INT:
                self._error(e.location, f"унарный минус: ожидался int, получен {t}")
                return None
            return (INT, _wrap32(-int(v)))
        if isinstance(e, Binary):
            left = self._const_expr(e.left)
            right = self._const_expr(e.right)
            if left is None or right is None:
                return None
            (lt, lv), (rt, rv) = left, right
            op = e.op
            if op == "+":
                if lt.base == "str" or rt.base == "str":
                    self._error(
                        e.location,
                        "конкатенация строк не выполняется на этапе компиляции",
                    )
                    return None
                if lt == INT and rt == INT:
                    return (INT, _wrap32(int(lv) + int(rv)))
                self._error(e.location, f"операция '+': несовместимые типы {lt} и {rt}")
                return None
            if op in ("-", "*", "/", "%", "**"):
                if lt != INT or rt != INT:
                    self._error(
                        e.location,
                        f"операция '{op}' определена только для int, получены {lt} и {rt}",
                    )
                    return None
                a, b = int(lv), int(rv)
                if op == "/":
                    if b == 0:
                        self._error(e.location, "деление на ноль в инициализаторе const")
                        return None
                    return (INT, _wrap32(_div_trunc(a, b)))
                if op == "%":
                    if b == 0:
                        self._error(e.location, "деление на ноль в инициализаторе const")
                        return None
                    return (INT, _wrap32(_mod_trunc(a, b)))
                if op == "**":
                    if b < 0:
                        self._error(e.location, "отрицательная степень в инициализаторе const")
                        return None
                    return (INT, _pow32(a, b))
                return (INT, _wrap32(a - b if op == "-" else a * b))
            if op in ("&", "|"):
                if lt != BOOL or rt != BOOL:
                    self._error(
                        e.location,
                        f"операция '{op}' определена только для bool, получены {lt} и {rt}",
                    )
                    return None
                if op == "&":
                    return (BOOL, bool(lv) and bool(rv))
                return (BOOL, bool(lv) or bool(rv))
            if op in ("<", "<=", ">", ">="):
                if lt != INT or rt != INT:
                    self._error(
                        e.location,
                        f"операция '{op}' определена только для int, получены {lt} и {rt}",
                    )
                    return None
                a, b = int(lv), int(rv)
                if op == "<":
                    return (BOOL, a < b)
                if op == "<=":
                    return (BOOL, a <= b)
                if op == ">":
                    return (BOOL, a > b)
                return (BOOL, a >= b)
            if lt.is_array or rt.is_array:
                self._error(e.location, "сравнение массивов не выполняется на этапе компиляции")
                return None
            if lt != rt:
                self._error(e.location, f"сравнение {lt} и {rt} не определено")
                return None
            if op == "==":
                return (BOOL, lv == rv)
            return (BOOL, lv != rv)
        if isinstance(e, (Call, New, Index)):
            self._error(
                e.location,
                "инициализатор const не может использовать вызовы, new и индексацию",
            )
            return None
        if isinstance(e, ArrayLiteral):
            self._error(e.location, "массивы не могут быть константами")
            return None
        raise TypeError("unknown expression: " + type(e).__name__)


def check(program: Program) -> SemResult:
    return _Checker().run(program)


if __name__ == "__main__":
    demo_path = os.path.join(
        os.path.dirname(__file__), "..", "..", "examples", "hello.ps"
    )
    result = check(parse(demo_path))
    if result.errors:
        for error in result.errors:
            print(error)
    else:
        mode = "main" if result.main is not None else "скрипт"
        print("ok:", mode)
