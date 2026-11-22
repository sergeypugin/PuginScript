"""AST PuginScript и его Lisp-подобный вывод в форме S-выражений"""

from dataclasses import dataclass, field

BASE_TYPES = ("int", "bool", "str")


@dataclass(frozen=True)
class SourceLocation:
    file: str
    line: int
    column: int


@dataclass(kw_only=True)
class Node:
    location: SourceLocation


class Expr(Node):
    pass


@dataclass
class Type:
    base: str
    is_array: bool = False

    def __str__(self) -> str:
        return self.base + ("[]" if self.is_array else "")


@dataclass
class New(Expr):
    base: str
    size: Expr


@dataclass
class IntegerLiteral(Expr):
    value: int


@dataclass
class StringLiteral(Expr):
    value: str  # декодированный текст, без кавычек и escape-последовательностей


@dataclass
class CharLiteral(Expr):
    code: int  # код символа 0-255


@dataclass
class BoolLiteral(Expr):
    value: bool


@dataclass
class ArrayLiteral(Expr):
    items: list[Expr]


@dataclass
class Identifier(Expr):
    name: str


@dataclass
class Index(Expr):
    base: Expr  # по грамматике это всегда Identifier; semantic отбраковывает остальное
    index: Expr


@dataclass
class Call(Expr):
    name: str
    args: list[Expr]


@dataclass
class Unary(Expr):
    op: str  # "!" | "-"
    operand: Expr


@dataclass
class Binary(Expr):
    op: str  # "+", "-", "*", "/", "%", "**", "==", "!=", "<", "<=", ">", ">=", "&", "|"
    left: Expr
    right: Expr


class Stmt(Node):
    pass


@dataclass
class VarDecl(Stmt):
    name: str
    var_type: Type
    init: Expr | None = None  # None -- объявление без значения


@dataclass
class LValue(Node):
    name: str
    index: Expr | None = None  # None -- простая переменная


@dataclass
class Assignment(Stmt):
    target: LValue
    op: str  # "=", "+=", "-=", "*=", "/=", "%="
    value: Expr


@dataclass
class IfStmt(Stmt):
    condition: Expr
    then_body: Block
    else_body: Block | IfStmt | None = None  # "else if" -- вложенный IfStmt


@dataclass
class WhileStmt(Stmt):
    condition: Expr
    body: Block


@dataclass
class ReturnStmt(Stmt):
    value: Expr | None = None


@dataclass
class ExprStmt(Stmt):
    expr: Expr


@dataclass
class Block(Stmt):
    body: list[Stmt]


class Decl(Node):
    pass


@dataclass
class Param(Node):
    name: str
    param_type: Type


@dataclass
class ConstDecl(Decl):
    name: str
    const_type: Type
    init: Expr


@dataclass
class FunctionDecl(Decl):
    name: str
    params: list[Param]
    body: Block
    return_type: Type | None = None  # None -- процедура


@dataclass
class Program:
    items: list[Decl | Stmt]


def _quote_string(text: str) -> str:
    escaped = (
        text
        .replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\0", "\\0")
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )
    return '"' + escaped + '"'


def _expr(e: Expr) -> str:
    if isinstance(e, IntegerLiteral):
        return str(e.value)
    if isinstance(e, StringLiteral):
        return _quote_string(e.value)
    if isinstance(e, CharLiteral):
        return "(char " + str(e.code) + ")"
    if isinstance(e, BoolLiteral):
        return "true" if e.value else "false"
    if isinstance(e, Identifier):
        return "(identifier " + e.name + ")"
    if isinstance(e, ArrayLiteral):
        return "(array" + "".join(" " + _expr(item) for item in e.items) + ")"
    if isinstance(e, New):
        return "(new " + e.base + " " + _expr(e.size) + ")"
    if isinstance(e, Index):
        return "(index " + _expr(e.base) + " " + _expr(e.index) + ")"
    if isinstance(e, Call):
        return "(call " + e.name + "".join(" " + _expr(arg) for arg in e.args) + ")"
    if isinstance(e, Unary):
        return "(" + e.op + " " + _expr(e.operand) + ")"
    if isinstance(e, Binary):
        return "(" + e.op + " " + _expr(e.left) + " " + _expr(e.right) + ")"
    raise TypeError("unknown expression: " + type(e).__name__)


def _lvalue(lv: LValue) -> str:
    if lv.index is None:
        return "(lv " + lv.name + ")"
    return "(lv " + lv.name + " " + _expr(lv.index) + ")"


@dataclass
class Sexp:
    """Узел для вывода S-выражений: atoms идут после головы, subs -- дочерние узлы"""

    head: str
    atoms: list[str] = field(default_factory=lambda: list[str]())
    subs: list[Sexp] = field(default_factory=lambda: list[Sexp]())


def _stmt(s: Stmt) -> Sexp:
    if isinstance(s, Block):
        sexp = Sexp("block")
        sexp.subs.extend(_stmt(x) for x in s.body)
        return sexp
    if isinstance(s, VarDecl):
        atoms = [str(s.var_type), s.name]
        if s.init is not None:
            atoms.append(_expr(s.init))
        return Sexp("var_decl", atoms)
    if isinstance(s, Assignment):
        return Sexp("assign", [_lvalue(s.target), s.op, _expr(s.value)])
    if isinstance(s, IfStmt):
        sexp = Sexp("if", [_expr(s.condition)])
        sexp.subs.append(_stmt(s.then_body))
        if s.else_body is not None:
            sexp.subs.append(Sexp("else", subs=[_stmt(s.else_body)]))
        return sexp
    if isinstance(s, WhileStmt):
        sexp = Sexp("while", [_expr(s.condition)])
        sexp.subs.append(_stmt(s.body))
        return sexp
    if isinstance(s, ReturnStmt):
        atoms: list[str] = []
        if s.value is not None:
            atoms.append(_expr(s.value))
        return Sexp("return", atoms)
    if isinstance(s, ExprStmt):
        return Sexp("expr", [_expr(s.expr)])
    raise TypeError("unknown statement: " + type(s).__name__)


def _item(item: Decl | Stmt) -> Sexp:
    if isinstance(item, ConstDecl):
        return Sexp("const", [str(item.const_type), item.name, _expr(item.init)])
    if isinstance(item, FunctionDecl):
        sexp = Sexp("def", [item.name])
        for param in item.params:
            sexp.subs.append(Sexp("param", [str(param.param_type), param.name]))
        if item.return_type is not None:
            sexp.subs.append(Sexp("returns", [str(item.return_type)]))
        sexp.subs.append(_stmt(item.body))
        return sexp
    if isinstance(item, Stmt):
        return _stmt(item)
    raise TypeError("unknown item: " + type(item).__name__)


def _fmt(sexp: Sexp, depth: int) -> list[str]:
    pad = "  " * depth
    line = pad + "(" + sexp.head + "".join(" " + atom for atom in sexp.atoms)
    if not sexp.subs:
        return [line + ")"]
    lines = [line]
    for sub in sexp.subs:
        lines.extend(_fmt(sub, depth + 1))
    lines[-1] += ")"
    return lines


def dump(program: Program) -> str:
    root = Sexp("program")
    root.subs.extend(_item(item) for item in program.items)
    return "\n".join(_fmt(root, 0))


if __name__ == "__main__":
    location = SourceLocation("example.ps", 1, 1)
    demo = Program(
        [
            VarDecl(
                "total",
                Type("int"),
                Binary(
                    "+",
                    IntegerLiteral(2, location=location),
                    IntegerLiteral(3, location=location),
                    location=location,
                ),
                location=location,
            )
        ]
    )
    print(dump(demo))
