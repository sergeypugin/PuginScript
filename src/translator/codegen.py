"""Кодогенерация PuginScript: из Program + SemResult в инструкции ISA и статику.

Возвращает пару (static_bytes, code_instructions):
- static_bytes -- байтовый образ секции данных (Little Endian, слово 0 = 0)
- code_instructions -- список Instruction для памяти команд (PC = 0)

Следует соглашению из docs/ISA.md:
- R0 -- ноль
- R1 -- RA
- R2 -- SP
- R3 -- FP
- R4-R7 -- аргументы/результат
- R8 -- HP
- R9-R31 -- временные
- jal -> R1, возврат jr R1
- Пролог: addi SP, SP, -8; sw FP, 4(SP); sw RA, 0(SP); addi FP, SP, 4
- Локальные переменные -- в кадре со смещениями от FP (отрицательные).
"""

from dataclasses import dataclass

from src.machine.config import MAX_STATIC_SIZE, RAM_SIZE
from src.machine.isa import (
    B as InsB,
    Halt as InsHalt,
    I as InsI,
    In as InsIn,
    Instruction,
    J as InsJ,
    Jr as InsJr,
    Out as InsOut,
    R as InsR,
    S as InsS,
    Trap as InsTrap,
)
from src.translator.runtime_helpers import RuntimeEmitter, RuntimeHelpers
from src.translator.semantic import ConstSymbol, FuncSymbol, SemResult, VarSymbol
from src.translator.syntax_tree import (
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
    Param,
    Program,
    ReturnStmt,
    Stmt,
    StringLiteral,
    Type,
    Unary,
    VarDecl,
    WhileStmt,
)

# Регистры по docs/ISA.md
ZERO = 0
RA = 1
SP = 2
FP = 3
RESULT_REG = 4
HP = 8

ARG_REGS = (4, 5, 6, 7)
TEMP_REGS = tuple(range(9, 32))


@dataclass(frozen=True)
class _Slot:
    offset: int
    type: Type


def _is_small_int(value: int) -> bool:
    return -0x8000 <= value <= 0x7FFF


class CodegenError(Exception):
    """Ошибка кодогенерации."""


class Codegen:
    def __init__(self, program: Program, result: SemResult) -> None:
        self.program = program
        self.result = result

        self.code: list[Instruction] = []
        self.data: bytearray = bytearray(4)
        self.strings: dict[str, int] = {"": 0}
        self.words: dict[int, int] = {}

        self._label_counter = 0
        self._labels: dict[str, int] = {}
        self._fixups: list[tuple[int, str]] = []

        self._in_use: set[int] = set()
        self._func_slots: dict[int, dict[int, _Slot]] = {}

        self._env: list[dict[str, _Slot]] = []
        self._current_func_id: int = 0
        self._return_labels: list[str] = []
        self._runtime_emitter = RuntimeEmitter(self)
        self._runtime_helpers = RuntimeHelpers(self._runtime_emitter.emit)

    def _use_runtime_helper(self, name: str) -> None:
        self._runtime_helpers.use(name)

    def _emit_runtime_helpers(self) -> None:
        self._runtime_helpers.emit_needed()

    # labels

    def _new_label(self, hint: str = "L") -> str:
        self._label_counter += 1
        return f"{hint}{self._label_counter}"

    def _define_label(self, name: str) -> None:
        if name in self._labels:
            raise CodegenError(f"duplicate label {name}")
        self._labels[name] = len(self.code)

    # static data

    def _align4(self) -> None:
        while len(self.data) % 4:
            self.data.append(0)

    def _add_string(self, value: str) -> int:
        if value in self.strings:
            return self.strings[value]
        self._align4()
        addr = len(self.data)
        raw = value.encode("latin-1")
        self.data.extend(raw)
        self.data.append(0)
        self._align4()
        self.strings[value] = addr
        return addr

    def _add_word(self, value: int) -> int:
        value &= 0xFFFFFFFF
        if value in self.words:
            return self.words[value]
        self._align4()
        addr = len(self.data)
        self.data.extend(value.to_bytes(4, "little", signed=False))
        self.words[value] = addr
        return addr

    def _static_bytes(self) -> bytes:
        self._align4()
        return bytes(self.data)

    def _layout_static(self) -> None:
        """Предварительный обход литералов, которые должны попасть в статическую память."""
        self._add_string("true")
        self._add_string("false")
        self._add_word(0x80000000)
        self._add_string("2147483648")

        for item in self.program.items:
            if isinstance(item, ConstDecl):
                sym = self.result.globals.resolve(item.name)
                if isinstance(sym, ConstSymbol):
                    self._layout_const_value(sym.value)

        roots: list[Stmt] = []
        if self.result.main is None:
            roots.extend(item for item in self.program.items if isinstance(item, Stmt))
        else:
            roots.extend(self.result.main.body.body) # передаём не Block, а именно list[Stmt]
        for stmt in roots:
            self._layout_stmt(stmt)

        for item in self.program.items:
            if isinstance(item, FunctionDecl):
                for stmt in item.body.body:
                    self._layout_stmt(stmt)

    def _layout_const_value(self, value: int | bool | str) -> None:
        if isinstance(value, str):
            self._add_string(value)
        elif isinstance(value, bool):
            return
        elif not _is_small_int(value):
            self._add_word(value)

    def _layout_stmt(self, stmt: Stmt) -> None:
        if isinstance(stmt, VarDecl):
            if stmt.init is not None:
                self._layout_expr(stmt.init)
        elif isinstance(stmt, Assignment):
            if stmt.target.index is not None:
                self._layout_expr(stmt.target.index)
            self._layout_expr(stmt.value)
        elif isinstance(stmt, IfStmt):
            self._layout_expr(stmt.condition)
            self._layout_stmt(stmt.then_body)
            if stmt.else_body is not None:
                self._layout_stmt(stmt.else_body)
        elif isinstance(stmt, WhileStmt):
            self._layout_expr(stmt.condition)
            self._layout_stmt(stmt.body)
        elif isinstance(stmt, ReturnStmt):
            if stmt.value is not None:
                self._layout_expr(stmt.value)
        elif isinstance(stmt, ExprStmt):
            self._layout_expr(stmt.expr)
        elif isinstance(stmt, Block):
            for child in stmt.body:
                self._layout_stmt(child)

    def _layout_expr(self, expr: Expr) -> None:
        if isinstance(expr, IntegerLiteral) and not _is_small_int(expr.value):
            self._add_word(expr.value)
        elif isinstance(expr, StringLiteral):
            self._add_string(expr.value)
        elif isinstance(expr, ArrayLiteral):
            for child in expr.items:
                self._layout_expr(child)
        elif isinstance(expr, Unary):
            self._layout_expr(expr.operand)
        elif isinstance(expr, Binary):
            self._layout_expr(expr.left)
            self._layout_expr(expr.right)
        elif isinstance(expr, Index):
            self._layout_expr(expr.base)
            self._layout_expr(expr.index)
        elif isinstance(expr, Call):
            for arg in expr.args:
                self._layout_expr(arg)
        elif isinstance(expr, New):
            self._layout_expr(expr.size)

    # registers

    def _alloc_temp(self) -> int:
        for reg in TEMP_REGS:
            if reg not in self._in_use:
                self._in_use.add(reg)
                return reg
        raise CodegenError("временные регистры закончились")

    def _free_temp(self, reg: int) -> None:
        self._in_use.discard(reg)

    def _save_temps(self) -> list[int]:
        saved = sorted(self._in_use)
        if saved:
            self._emit_addi(SP, SP, -4 * len(saved))
            for i, reg in enumerate(saved):
                self._emit_sw(reg, SP, i * 4)
        return saved

    def _restore_temps(self, saved: list[int]) -> None:
        if saved:
            for i, reg in enumerate(saved):
                self._emit_lw(reg, SP, i * 4)
            self._emit_addi(SP, SP, 4 * len(saved))

    # emit

    def _emit(self, ins: Instruction) -> int:
        idx = len(self.code)
        self.code.append(ins)
        return idx

    def _emit_addi(self, rd: int, rs1: int, imm: int) -> int:
        return self._emit(InsI("addi", rd, rs1, imm))

    def _emit_mvi(self, rd: int, imm: int) -> int:
        return self._emit_addi(rd, ZERO, imm)

    def _emit_lui(self, rd: int, imm: int) -> int:
        return self._emit(InsI("lui", rd, ZERO, imm))

    def _emit_ori(self, rd: int, rs1: int, imm: int) -> int:
        return self._emit(InsI("ori", rd, rs1, imm))

    def _emit_lw(self, rd: int, base: int, off: int) -> int:
        return self._emit(InsI("lw", rd, base, off))

    def _emit_lbu(self, rd: int, base: int, off: int) -> int:
        return self._emit(InsI("lbu", rd, base, off))

    def _emit_sw(self, rs2: int, base: int, off: int) -> int:
        return self._emit(InsS("sw", rs2, base, off))

    def _emit_sb(self, rs2: int, base: int, off: int) -> int:
        return self._emit(InsS("sb", rs2, base, off))

    def _emit_add(self, rd: int, rs1: int, rs2: int) -> int:
        return self._emit(InsR("add", rd, rs1, rs2))

    def _emit_mv(self, rd: int, rs: int) -> int:
        return self._emit_add(rd, rs, ZERO)

    def _emit_sub(self, rd: int, rs1: int, rs2: int) -> int:
        return self._emit(InsR("sub", rd, rs1, rs2))

    def _emit_mul(self, rd: int, rs1: int, rs2: int) -> int:
        return self._emit(InsR("mul", rd, rs1, rs2))

    def _emit_div(self, rd: int, rs1: int, rs2: int) -> int:
        return self._emit(InsR("div", rd, rs1, rs2))

    def _emit_mod(self, rd: int, rs1: int, rs2: int) -> int:
        return self._emit(InsR("mod", rd, rs1, rs2))

    def _emit_slt(self, rd: int, rs1: int, rs2: int) -> int:
        return self._emit(InsR("slt", rd, rs1, rs2))

    def _emit_seq(self, rd: int, rs1: int, rs2: int) -> int:
        return self._emit(InsR("seq", rd, rs1, rs2))

    def _emit_and(self, rd: int, rs1: int, rs2: int) -> int:
        return self._emit(InsR("and", rd, rs1, rs2))

    def _emit_or(self, rd: int, rs1: int, rs2: int) -> int:
        return self._emit(InsR("or", rd, rs1, rs2))

    def _emit_beq(self, rs1: int, rs2: int, label: str) -> int:
        idx = self._emit(InsB("beq", rs1, rs2, 0))
        self._fixups.append((idx, label))
        return idx

    def _emit_bne(self, rs1: int, rs2: int, label: str) -> int:
        idx = self._emit(InsB("bne", rs1, rs2, 0))
        self._fixups.append((idx, label))
        return idx

    def _emit_jmp(self, label: str) -> int:
        idx = self._emit(InsJ("jmp", 0))
        self._fixups.append((idx, label))
        return idx

    def _emit_jal(self, label: str) -> int:
        if label.startswith("rt_"):
            self._use_runtime_helper(label)
        idx = self._emit(InsJ("jal", 0))
        self._fixups.append((idx, label))
        return idx

    def _emit_jr(self, rs: int) -> int:
        return self._emit(InsJr(rs))

    def _emit_halt(self) -> int:
        return self._emit(InsHalt())

    def _emit_trap(self, code_val: int) -> int:
        return self._emit(InsTrap(code_val))

    def _emit_out(self, rs: int, port: int) -> int:
        return self._emit(InsOut(rs, port))

    def _emit_in(self, rd: int, port: int) -> int:
        return self._emit(InsIn(rd, port))

    def _load_address(self, reg: int, addr: int) -> None:
        if _is_small_int(addr):
            self._emit_mvi(reg, addr)
        else:
            self._emit_lui(reg, (addr >> 16) & 0xFFFF)
            lo = addr & 0xFFFF
            if lo:
                self._emit_ori(reg, reg, lo)

    # patch

    def _patch_labels(self) -> None:

        for idx, name in self._fixups:
            target = self._labels.get(name)
            if target is None:
                raise CodegenError(f"метка {name} не определена")
            ins = self.code[idx]
            disp = target - (idx + 1)
            if isinstance(ins, InsB):
                self.code[idx] = InsB(ins.mnemonic, ins.rs1, ins.rs2, disp)
            elif isinstance(ins, InsJ):
                self.code[idx] = InsJ(ins.mnemonic, disp)

    # entry

    def generate(self) -> tuple[bytes, list[Instruction]]:
        if self.result.errors:
            raise CodegenError("нельзя генерировать код при семантических ошибках")

        self._layout_static()
        hp_init = self._emit_mvi(HP, 0)
        if self.result.main is not None:
            self._emit_jal(f"func_{self.result.main.name}")
        else:
            self._emit_jal("script_func")
        self._emit_halt()

        if self.result.main is None:
            self._compile_script()
        for item in self.program.items:
            if isinstance(item, FunctionDecl):
                self._compile_function(item)

        self._emit_runtime_helpers()
        if len(self.data) > MAX_STATIC_SIZE:
            raise CodegenError("статика превышает максимально допустимый размер")
        self.code[hp_init] = InsI("addi", HP, ZERO, len(self.data))
        self._patch_labels()
        return self._static_bytes(), self.code

    # script mode

    def _collect_frame_slots(
        self,
        func_id: int,
        params: list[Param],
        statements: list[Stmt],
    ) -> None:
        offset = -4
        slots: dict[int, _Slot] = {}
        for param in params:
            offset -= 4
            slots[id(param)] = _Slot(offset, param.param_type)

        def collect_block(block: Block) -> None:
            for stmt in block.body:
                collect_stmt(stmt)

        def collect_stmt(stmt: Stmt) -> None:
            nonlocal offset
            if isinstance(stmt, VarDecl):
                offset -= 4
                slots[id(stmt)] = _Slot(offset, stmt.var_type)
            elif isinstance(stmt, IfStmt):
                collect_block(stmt.then_body)
                if isinstance(stmt.else_body, Block):
                    collect_block(stmt.else_body)
                elif isinstance(stmt.else_body, IfStmt):
                    collect_stmt(stmt.else_body)
            elif isinstance(stmt, WhileStmt):
                collect_block(stmt.body)
            elif isinstance(stmt, Block):
                collect_block(stmt)

        for statement in statements:
            collect_stmt(statement)
        self._func_slots[func_id] = slots

    def _compile_script(self) -> None:
        self._define_label("script_func")
        self._current_func_id = 0

        statements = [item for item in self.program.items if isinstance(item, Stmt)]
        self._collect_frame_slots(0, [], statements)
        self._emit_prologue(4 * len(self._func_slots[0]))

        self._env = [{}]
        end_label = self._new_label("return_script")
        self._return_labels.append(end_label)

        for stmt in statements:
            self._compile_stmt(stmt)

        self._emit_mv(RESULT_REG, ZERO)
        self._define_label(end_label)
        self._emit_epilogue()
        self._return_labels.pop()

    # functions

    def _compile_function(self, func: FunctionDecl) -> None:
        self._define_label(f"func_{func.name}")
        self._current_func_id = id(func)
        self._collect_frame_slots(self._current_func_id, func.params, func.body.body)

        local_bytes = 4 * len(self._func_slots[self._current_func_id])
        self._emit_prologue(local_bytes)

        self._env = [{}]
        for i, param in enumerate(func.params):
            slot = self._func_slots[self._current_func_id][id(param)]
            self._env[-1][param.name] = slot
            if i < 4:
                self._emit_sw(ARG_REGS[i], FP, slot.offset)
            else:
                caller_off = 4 + (i - 4) * 4
                tmp = self._alloc_temp()
                self._emit_lw(tmp, FP, caller_off)
                self._emit_sw(tmp, FP, slot.offset)
                self._free_temp(tmp)

        end_label = self._new_label(f"return_{func.name}")
        self._return_labels.append(end_label)
        self._compile_block(func.body, push_scope=False)
        self._return_labels.pop()

        if func.return_type is None:
            self._emit_mv(RESULT_REG, ZERO)
        self._define_label(end_label)
        self._emit_epilogue()

    def _emit_prologue(self, local_bytes: int) -> None:
        """Собирает кадр: сохраняет FP и RA, переносит базу на FP, отводит место под локальные."""
        self._emit_addi(SP, SP, -8)
        self._emit_sw(FP, SP, 4)
        self._emit_sw(RA, SP, 0)
        self._emit_addi(FP, SP, 4)
        if local_bytes > 0:
            self._emit_addi(SP, SP, -local_bytes)

    def _emit_epilogue(self) -> None:
        """Разбирает кадр: восстанавливает RA, старый FP и SP, возвращает управление по RA."""
        saved_fp = self._alloc_temp()
        self._emit_lw(RA, FP, -4)
        self._emit_lw(saved_fp, FP, 0)
        self._emit_addi(SP, FP, 4)
        self._emit_mv(FP, saved_fp)
        self._free_temp(saved_fp)
        self._emit_jr(RA)

    def _lookup_var_offset(self, name: str) -> tuple[int, Type]:
        for scope in reversed(self._env):
            if name in scope:
                slot = scope[name]
                return (slot.offset, slot.type)
        sym = self.result.globals.resolve(name)
        if isinstance(sym, ConstSymbol):
            return (0, sym.type)
        if isinstance(sym, VarSymbol):
            return (0, sym.type)
        raise CodegenError(f"переменная {name} не найдена")

    def _lookup_var_slot(self, name: str) -> _Slot | None:
        for scope in reversed(self._env):
            if name in scope:
                return scope[name]
        return None

    # statements

    def _compile_block(self, block: Block, push_scope: bool = True) -> None:
        if push_scope:
            self._env.append({})
        for stmt in block.body:
            self._compile_stmt(stmt)
        if push_scope:
            self._env.pop()

    def _compile_stmt(self, stmt: Stmt) -> None:
        if isinstance(stmt, Block):
            self._compile_block(stmt)
        elif isinstance(stmt, VarDecl):
            self._compile_var_decl(stmt)
        elif isinstance(stmt, Assignment):
            self._compile_assignment(stmt)
        elif isinstance(stmt, IfStmt):
            self._compile_if(stmt)
        elif isinstance(stmt, WhileStmt):
            self._compile_while(stmt)
        elif isinstance(stmt, ReturnStmt):
            self._compile_return(stmt)
        elif isinstance(stmt, ExprStmt):
            reg = self._compile_expr(stmt.expr)
            self._free_temp(reg)
        else:
            raise CodegenError(f"неизвестный оператор: {type(stmt).__name__}")

    def _compile_var_decl(self, d: VarDecl) -> None:
        slot = self._func_slots[self._current_func_id][id(d)]
        self._env[-1][d.name] = slot
        if d.init is not None:
            reg = self._compile_expr(d.init)
            self._emit_sw(reg, FP, slot.offset)
            self._free_temp(reg)
        else:
            self._emit_sw(ZERO, FP, slot.offset)

    def _compile_assignment(self, a: Assignment) -> None:
        value_reg = self._compile_expr(a.value)

        if a.target.index is not None:
            idx_reg = self._compile_expr(a.target.index)
            off, _typ = self._lookup_var_offset(a.target.name)
            base_reg = self._alloc_temp()
            length_reg = self._alloc_temp()
            self._emit_lw(base_reg, FP, off)
            self._emit_lw(length_reg, base_reg, 0)
            self._emit_index_check(idx_reg, length_reg)
            addr_reg = self._alloc_temp()
            self._emit_addi(addr_reg, ZERO, 4)
            self._emit_mul(addr_reg, addr_reg, idx_reg)
            self._emit_add(addr_reg, base_reg, addr_reg)
            if a.op == "=":
                self._emit_sw(value_reg, addr_reg, 4)
            else:
                cur_reg = self._alloc_temp()
                res_reg = self._alloc_temp()
                self._emit_lw(cur_reg, addr_reg, 4)
                self._emit_assignment_op(res_reg, cur_reg, value_reg, a.op)
                self._emit_sw(res_reg, addr_reg, 4)
                self._free_temp(cur_reg)
                self._free_temp(res_reg)
            self._free_temp(idx_reg)
            self._free_temp(base_reg)
            self._free_temp(length_reg)
            self._free_temp(addr_reg)
        else:
            off, _typ = self._lookup_var_offset(a.target.name)
            if a.op == "=":
                self._emit_sw(value_reg, FP, off)
            else:
                cur_reg = self._alloc_temp()
                self._emit_lw(cur_reg, FP, off)
                res_reg = self._alloc_temp()
                self._emit_assignment_op(res_reg, cur_reg, value_reg, a.op)
                self._emit_sw(res_reg, FP, off)
                self._free_temp(cur_reg)
                self._free_temp(res_reg)

        self._free_temp(value_reg)

    def _emit_index_check(
        self, index_reg: int, length_reg: int, allow_terminator: bool = False
    ) -> None:
        negative = self._alloc_temp()
        flag = self._alloc_temp()
        ok = self._new_label("index_ok")
        trap = self._new_label("index_trap")
        self._emit_slt(negative, index_reg, ZERO)
        self._emit_bne(negative, ZERO, trap)
        if allow_terminator:
            # индекс == длине разрешён: это позиция терминатора строки
            self._emit_slt(flag, length_reg, index_reg)
            self._emit_beq(flag, ZERO, ok)
        else:
            self._emit_slt(flag, index_reg, length_reg)
            self._emit_bne(flag, ZERO, ok)
        self._define_label(trap)
        self._emit_trap(4)
        self._define_label(ok)
        self._free_temp(negative)
        self._free_temp(flag)

    def _emit_assignment_op(self, result: int, left: int, right: int, op: str) -> None:
        op_map = {"+=": "add", "-=": "sub", "*=": "mul", "/=": "div", "%=": "mod"}
        mnemonic = op_map.get(op)
        if mnemonic is None:
            raise CodegenError(f"неизвестная операция присваивания: {op}")
        self._emit(InsR(mnemonic, result, left, right))

    def _compile_if(self, stmt: IfStmt) -> None:
        cond_reg = self._compile_expr(stmt.condition)
        else_label = self._new_label("else")
        end_label = self._new_label("endif")

        self._emit_beq(cond_reg, ZERO, else_label)
        self._free_temp(cond_reg)

        self._compile_stmt(stmt.then_body)
        self._emit_jmp(end_label)

        self._define_label(else_label)
        if stmt.else_body is not None:
            if isinstance(stmt.else_body, IfStmt):
                self._compile_if(stmt.else_body)
            else:
                self._compile_stmt(stmt.else_body)

        self._define_label(end_label)

    def _compile_while(self, stmt: WhileStmt) -> None:
        start_label = self._new_label("while")
        end_label = self._new_label("endwhile")

        self._define_label(start_label)
        cond_reg = self._compile_expr(stmt.condition)
        self._emit_beq(cond_reg, ZERO, end_label)
        self._free_temp(cond_reg)

        self._compile_stmt(stmt.body)
        self._emit_jmp(start_label)

        self._define_label(end_label)

    def _compile_return(self, stmt: ReturnStmt) -> None:
        if stmt.value is not None:
            reg = self._compile_expr(stmt.value)
            if reg != RESULT_REG:
                self._emit_mv(RESULT_REG, reg)
            self._free_temp(reg)
        else:
            self._emit_mv(RESULT_REG, ZERO)

        if self._current_func_id == 0:
            self._emit_halt()
        else:
            self._emit_jmp(self._return_labels[-1])

    # expressions

    def _expr_type(self, expr: Expr) -> Type:
        if isinstance(expr, IntegerLiteral):
            return Type("int")
        if isinstance(expr, CharLiteral):
            return Type("int")
        if isinstance(expr, BoolLiteral):
            return Type("bool")
        if isinstance(expr, StringLiteral):
            return Type("str")
        if isinstance(expr, ArrayLiteral):
            if expr.items:
                return Type(self._expr_type(expr.items[0]).base, True)
            return Type("int", True)
        if isinstance(expr, New):
            return Type(expr.base, True)
        if isinstance(expr, Identifier):
            slot = self._lookup_var_slot(expr.name)
            if slot is not None:
                return slot.type
            sym = self.result.globals.resolve(expr.name)
            if isinstance(sym, (ConstSymbol, VarSymbol)):
                return sym.type
            return Type("int")
        if isinstance(expr, Index):
            base_t = self._expr_type(expr.base)
            if base_t.base == "str":
                return Type("int")
            return Type(base_t.base, False)
        if isinstance(expr, Call):
            sym = self.result.globals.resolve(expr.name)
            if isinstance(sym, FuncSymbol) and sym.return_type is not None:
                return sym.return_type
            if expr.name in ("len", "input_int", "input_char"):
                return Type("int")
            if expr.name == "input":
                return Type("str")
            if expr.name in ("print", "println", "print_char"):
                return Type("int")
            return Type("int")
        if isinstance(expr, Unary):
            return Type("bool") if expr.op == "!" else Type("int")
        if isinstance(expr, Binary):
            if expr.op in {"==", "!=", "<", "<=", ">", ">=", "&", "|"}:
                return Type("bool")
            if expr.op == "+":
                if self._expr_type(expr.left).base == "str" or self._expr_type(expr.right).base == "str":
                    return Type("str")
            return Type("int")
        return Type("int")

    def _compile_expr(self, e: Expr) -> int:
        if isinstance(e, IntegerLiteral):
            return self._compile_int_lit(e.value)
        if isinstance(e, StringLiteral):
            return self._compile_str_lit(e.value)
        if isinstance(e, CharLiteral):
            return self._compile_char_lit(e.code)
        if isinstance(e, BoolLiteral):
            return self._compile_bool_lit(e.value)
        if isinstance(e, Identifier):
            return self._compile_ident(e)
        if isinstance(e, Index):
            return self._compile_index(e)
        if isinstance(e, Call):
            return self._compile_call(e)
        if isinstance(e, Unary):
            return self._compile_unary(e)
        if isinstance(e, Binary):
            return self._compile_binary(e)
        if isinstance(e, New):
            return self._compile_new(e)
        if isinstance(e, ArrayLiteral):
            return self._compile_array_lit(e)
        raise CodegenError(f"неизвестное выражение: {type(e).__name__}")

    def _compile_int_lit(self, value: int) -> int:
        reg = self._alloc_temp()
        if _is_small_int(value):
            self._emit_mvi(reg, value)
        else:
            addr = self._add_word(value)
            self._emit_lw(reg, ZERO, addr)
        return reg

    def _compile_str_lit(self, value: str) -> int:
        reg = self._alloc_temp()
        addr = self._add_string(value)
        self._load_address(reg, addr)
        return reg

    def _compile_char_lit(self, code: int) -> int:
        reg = self._alloc_temp()
        self._emit_mvi(reg, code)
        return reg

    def _compile_bool_lit(self, value: bool) -> int:
        reg = self._alloc_temp()
        self._emit_mvi(reg, 1 if value else 0)
        return reg

    def _compile_ident(self, e: Identifier) -> int:
        name = e.name
        reg = self._alloc_temp()

        slot = self._lookup_var_slot(name)
        if slot is not None:
            self._emit_lw(reg, FP, slot.offset)
            return reg

        sym = self.result.globals.resolve(name)
        if isinstance(sym, ConstSymbol):
            value = sym.value
            if isinstance(value, bool):
                self._emit_mvi(reg, 1 if value else 0)
            elif isinstance(value, int):
                if _is_small_int(value):
                    self._emit_mvi(reg, value)
                else:
                    addr = self._add_word(value)
                    self._emit_lw(reg, ZERO, addr)
            else:
                addr = self._add_string(value)
                self._load_address(reg, addr)
            return reg

        raise CodegenError(f"переменная {name} не найдена")

    def _compile_index(self, e: Index) -> int:
        base_val = self._compile_expr(e.base)
        idx_reg = self._compile_expr(e.index)
        result = self._alloc_temp()

        base_t = self._expr_type(e.base)
        if base_t.base == "str":
            length_reg = self._alloc_temp()
            self._emit_mv(RESULT_REG, base_val)
            saved = self._save_temps()
            self._emit_jal("rt_len_str")
            self._restore_temps(saved)
            self._emit_mv(length_reg, RESULT_REG)
            self._emit_index_check(idx_reg, length_reg, allow_terminator=True)
            self._free_temp(length_reg)
            addr_reg = self._alloc_temp()
            self._emit_add(addr_reg, base_val, idx_reg)
            self._emit_lbu(result, addr_reg, 0)
            self._free_temp(addr_reg)
        else:
            length_reg = self._alloc_temp()
            self._emit_lw(length_reg, base_val, 0)
            self._emit_index_check(idx_reg, length_reg)
            self._free_temp(length_reg)
            scale_reg = self._alloc_temp()
            self._emit_addi(scale_reg, ZERO, 4)
            self._emit_mul(scale_reg, scale_reg, idx_reg)
            addr_reg = self._alloc_temp()
            self._emit_add(addr_reg, base_val, scale_reg)
            self._emit_lw(result, addr_reg, 4)
            self._free_temp(scale_reg)
            self._free_temp(addr_reg)

        self._free_temp(base_val)
        self._free_temp(idx_reg)
        return result

    def _compile_call(self, call: Call) -> int:
        name = call.name
        args = call.args

        if name in ("print", "println", "print_char", "input", "input_int", "input_char", "len"):
            return self._compile_builtin(call)

        arg_regs: list[int] = []
        for arg in args:
            arg_regs.append(self._compile_expr(arg))


        saved = self._save_temps()

        stack_arg_count = max(0, len(args) - 4)
        if stack_arg_count > 0:
            self._emit_addi(SP, SP, -4 * stack_arg_count)

        for i, reg in enumerate(arg_regs):
            if i < 4:
                self._emit_mv(ARG_REGS[i], reg)
            else:
                self._emit_sw(reg, SP, (i - 4) * 4)

        self._emit_jal(f"func_{name}")

        if stack_arg_count > 0:
            self._emit_addi(SP, SP, 4 * stack_arg_count)

        self._restore_temps(saved)

        for reg in arg_regs:
            self._free_temp(reg)

        result_reg = self._alloc_temp()
        self._emit_mv(result_reg, RESULT_REG)
        return result_reg

    def _compile_builtin(self, call: Call) -> int:
        # result_reg выделяется последним: он не нужен во время вызова, поэтому не
        # попадает в save/restore и не сдвигает номера регистров аргументов
        name = call.name
        args = call.args

        if name == "print_char":
            if not args:
                result_reg = self._alloc_temp()
                self._emit_mv(result_reg, ZERO)
                return result_reg
            reg = self._compile_expr(args[0])
            self._emit_out(reg, 1)
            self._free_temp(reg)
            result_reg = self._alloc_temp()
            self._emit_mv(result_reg, ZERO)
            return result_reg

        if name == "input_char":
            result_reg = self._alloc_temp()
            self._emit_in(result_reg, 0)
            return result_reg

        if name == "len":
            if not args:
                result_reg = self._alloc_temp()
                self._emit_mv(result_reg, ZERO)
                return result_reg
            arg_type = self._expr_type(args[0])
            reg = self._compile_expr(args[0])
            self._emit_mv(RESULT_REG, reg)
            saved = self._save_temps()
            if arg_type.base == "str":
                self._emit_jal("rt_len_str")
            else:
                self._emit_jal("rt_len")
            self._restore_temps(saved)
            self._free_temp(reg)
            result_reg = self._alloc_temp()
            self._emit_mv(result_reg, RESULT_REG)
            return result_reg

        if name in ("print", "println"):
            if not args:
                if name == "println":
                    newline = self._alloc_temp()
                    self._emit_addi(newline, ZERO, 10)
                    self._emit_out(newline, 1)
                    self._free_temp(newline)
                result_reg = self._alloc_temp()
                self._emit_mv(result_reg, ZERO)
                return result_reg
            reg = self._compile_expr(args[0])
            arg_t = self._expr_type(args[0])
            self._emit_mv(RESULT_REG, reg)
            saved = self._save_temps()
            if arg_t.base == "str":
                self._emit_jal("rt_println_str" if name == "println" else "rt_print_str")
            elif arg_t.base == "bool":
                self._emit_jal("rt_println_bool" if name == "println" else "rt_print_bool")
            else:
                self._emit_jal("rt_println_int" if name == "println" else "rt_print_int")
            self._restore_temps(saved)
            self._free_temp(reg)
            result_reg = self._alloc_temp()
            self._emit_mv(result_reg, ZERO)
            return result_reg

        if name == "input":
            saved = self._save_temps()
            self._emit_jal("rt_input")
            self._restore_temps(saved)
            result_reg = self._alloc_temp()
            self._emit_mv(result_reg, RESULT_REG)
            return result_reg

        if name == "input_int":
            saved = self._save_temps()
            self._emit_jal("rt_input_int")
            self._restore_temps(saved)
            result_reg = self._alloc_temp()
            self._emit_mv(result_reg, RESULT_REG)
            return result_reg

        # Неизвестный встроенный вызов -- трапаем
        for arg in args:
            r = self._compile_expr(arg)
            self._free_temp(r)
        self._emit_trap(0)
        result_reg = self._alloc_temp()
        self._emit_mv(result_reg, ZERO)
        return result_reg

    def _compile_unary(self, e: Unary) -> int:
        operand = self._compile_expr(e.operand)
        result = self._alloc_temp()

        if e.op == "-":
            self._emit_sub(result, ZERO, operand)
        elif e.op == "!":
            self._emit_seq(result, operand, ZERO)
        else:
            raise CodegenError(f"неизвестная унарная операция: {e.op}")

        self._free_temp(operand)
        return result

    def _compile_binary(self, e: Binary) -> int:
        left = self._compile_expr(e.left)
        right = self._compile_expr(e.right)
        result = self._alloc_temp()

        op = e.op
        if op == "+":
            left_t = self._expr_type(e.left)
            right_t = self._expr_type(e.right)
            if left_t.base == "str" or right_t.base == "str":
                # Конвертируем не-строковые операнды в строки перед конкатенацией
                if left_t.base != "str":
                    self._emit_add(RESULT_REG, ZERO, left)
                    saved = self._save_temps()
                    self._emit_jal("rt_bool_to_str" if left_t.base == "bool" else "rt_int_to_str")
                    self._restore_temps(saved)
                    self._free_temp(left)
                    left = self._alloc_temp()
                    self._emit_add(left, ZERO, RESULT_REG)
                if right_t.base != "str":
                    self._emit_add(RESULT_REG, ZERO, right)
                    saved = self._save_temps()
                    self._emit_jal("rt_bool_to_str" if right_t.base == "bool" else "rt_int_to_str")
                    self._restore_temps(saved)
                    self._free_temp(right)
                    right = self._alloc_temp()
                    self._emit_add(right, ZERO, RESULT_REG)

                self._emit_add(RESULT_REG, ZERO, left)
                saved = self._save_temps()
                self._emit_add(ARG_REGS[1], ZERO, right)
                self._emit_jal("rt_concat")
                self._restore_temps(saved)
                self._free_temp(left)
                self._free_temp(right)
                self._emit_add(result, ZERO, RESULT_REG)
                return result
            self._emit_add(result, left, right)
        elif op == "-":
            self._emit_sub(result, left, right)
        elif op == "*":
            self._emit_mul(result, left, right)
        elif op == "/":
            self._emit_div(result, left, right)
        elif op == "%":
            self._emit_mod(result, left, right)
        elif op == "**":
            self._emit_add(ARG_REGS[0], ZERO, left)
            self._emit_add(ARG_REGS[1], ZERO, right)
            saved = self._save_temps()
            self._emit_jal("rt_pow")
            self._restore_temps(saved)
            self._emit_add(result, ZERO, RESULT_REG)
        elif op in ("==", "!=") and self._expr_type(e.left).base == "str":
            self._emit_add(RESULT_REG, ZERO, left)
            self._emit_add(ARG_REGS[1], ZERO, right)
            saved = self._save_temps()
            self._emit_jal("rt_str_eq")
            self._restore_temps(saved)
            self._emit_add(result, ZERO, RESULT_REG)
            if op == "!=":
                tmp = self._alloc_temp()
                self._emit_addi(tmp, ZERO, 1)
                self._emit_sub(result, tmp, result)
                self._free_temp(tmp)
        elif op == "==":
            self._emit_seq(result, left, right)
        elif op == "!=":
            self._emit_seq(result, left, right)
            tmp = self._alloc_temp()
            self._emit_addi(tmp, ZERO, 1)
            self._emit_sub(result, tmp, result)
            self._free_temp(tmp)
        elif op == "<":
            self._emit_slt(result, left, right)
        elif op == ">":
            self._emit_slt(result, right, left)
        elif op == "<=":
            self._emit_slt(result, right, left)
            tmp = self._alloc_temp()
            self._emit_addi(tmp, ZERO, 1)
            self._emit_sub(result, tmp, result)
            self._free_temp(tmp)
        elif op == ">=":
            self._emit_slt(result, left, right)
            tmp = self._alloc_temp()
            self._emit_addi(tmp, ZERO, 1)
            self._emit_sub(result, tmp, result)
            self._free_temp(tmp)
        elif op == "&":
            self._emit_and(result, left, right)
        elif op == "|":
            self._emit_or(result, left, right)
        else:
            raise CodegenError(f"неизвестная бинарная операция: {op}")

        self._free_temp(left)
        self._free_temp(right)
        return result

    def _compile_new(self, e: New, zero_initialize: bool = True) -> int:
        size_reg = self._compile_expr(e.size)
        result_reg = self._alloc_temp()

        self._emit_mv(result_reg, HP)
        tmp = self._alloc_temp()

        neg = self._alloc_temp()
        self._emit_slt(neg, size_reg, ZERO)
        ok = self._new_label("new_ok")
        self._emit_beq(neg, ZERO, ok)
        self._emit_trap(10)
        self._define_label(ok)

        max_size = self._alloc_temp()
        max_array_elements = (RAM_SIZE - 4) // 4
        self._load_address(max_size, max_array_elements)
        too_large = self._new_label("new_too_large")
        self._emit_slt(tmp, max_size, size_reg)
        self._emit_bne(tmp, ZERO, too_large)

        self._emit_addi(tmp, ZERO, 4)
        self._emit_mul(tmp, tmp, size_reg)
        self._emit_addi(tmp, tmp, 4)
        self._emit_add(HP, HP, tmp)
        wrapped = self._new_label("new_wrapped")
        self._emit_slt(tmp, HP, result_reg)
        self._emit_bne(tmp, ZERO, wrapped)
        allocation_ok = self._new_label("new_allocation_ok")
        self._emit_jmp(allocation_ok)
        self._define_label(too_large)
        self._emit_trap(3)
        self._define_label(wrapped)
        self._emit_trap(3)
        self._define_label(allocation_ok)

        coll = self._alloc_temp()
        self._emit_slt(coll, SP, HP)
        safe = self._new_label("heap_safe")
        self._emit_beq(coll, ZERO, safe)
        self._emit_trap(3)
        self._define_label(safe)

        self._emit_sw(size_reg, result_reg, 0)
        if zero_initialize:
            index = self._alloc_temp()
            ptr = self._alloc_temp()
            self._emit_addi(index, ZERO, 0)
            self._emit_addi(ptr, result_reg, 4)
            zero_loop = self._new_label("new_zero_loop")
            zero_done = self._new_label("new_zero_done")
            self._define_label(zero_loop)
            self._emit_slt(tmp, index, size_reg)
            self._emit_beq(tmp, ZERO, zero_done)
            self._emit_sw(ZERO, ptr, 0)
            self._emit_addi(ptr, ptr, 4)
            self._emit_addi(index, index, 1)
            self._emit_jmp(zero_loop)
            self._define_label(zero_done)
            self._free_temp(index)
            self._free_temp(ptr)

        self._free_temp(size_reg)
        self._free_temp(tmp)
        self._free_temp(neg)
        self._free_temp(max_size)
        self._free_temp(coll)
        return result_reg

    def _compile_array_lit(self, e: ArrayLiteral) -> int:
        n = len(e.items)
        arr_reg = self._compile_new(
            New("int", IntegerLiteral(n, location=e.location), location=e.location),
            zero_initialize=False,
        )

        for i, item in enumerate(e.items):
            val_reg = self._compile_expr(item)
            self._emit_sw(val_reg, arr_reg, 4 + i * 4)
            self._free_temp(val_reg)

        return arr_reg



def codegen(program: Program, result: SemResult) -> tuple[bytes, list[Instruction]]:
    cg = Codegen(program, result)
    return cg.generate()
