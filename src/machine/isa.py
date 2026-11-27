"""Спецификация и кодирование инструкций 32-битной RISC ISA.

Форматы R/I/S/B/J, опкоды и раскладки бит -- в docs/ISA.md.
"""

from dataclasses import dataclass

REGISTER_COUNT = 32
OPCODE_SHIFT = 26
HALT_WORD = 0xFC000000

OPCODE: dict[str, int] = {
    # R-класс
    "add": 0,
    "sub": 1,
    "mul": 2,
    "div": 3,
    "mod": 4,
    "and": 5,
    "or": 6,
    "slt": 7,
    "seq": 8,
    # I-класс
    "addi": 16,
    "lui": 17,
    "ori": 18,
    "lw": 19,
    "lb": 20,
    "lbu": 21,
    "jr": 22,
    "in": 23,
    # S-класс
    "sw": 32,
    "sb": 33,
    "out": 34,
    # B/J/системный класс
    "beq": 48,
    "bne": 49,
    "jmp": 52,
    "jal": 53,
    "trap": 62,
    "halt": 63,
}


class ISAError(Exception):
    """Ошибка кодирования инструкции ISA (регистр, immediate или смещение за диапазоном)"""


def _opcode(mnemonic: str) -> int:
    op = OPCODE.get(mnemonic)
    if op is None:
        raise ISAError(f"неизвестная мнемоника инструкции: {mnemonic}")
    return op


def _reg(value: int) -> int:
    if not 0 <= value < REGISTER_COUNT:
        raise ISAError(f"регистр R{value} выходит за диапазон R0..R{REGISTER_COUNT - 1}")
    return value


def _imm16(value: int, unsigned: bool = False) -> int:
    below, above = (0, 0xFFFF) if unsigned else (-0x8000, 0x7FFF)
    if not below <= value <= above:
        raise ISAError(f"imm16 выходит за диапазон [{below}; {above}]: {value}")
    return value & 0xFFFF


def _imm26(value: int) -> int:
    below, above = -(1 << 25), (1 << 25) - 1
    if not below <= value <= above:
        raise ISAError(f"disp26 выходит за диапазон [{below}; {above}]: {value}")
    return value & 0x3FFFFFF


@dataclass(frozen=True)
class R:
    mnemonic: str
    rd: int
    rs1: int
    rs2: int


@dataclass(frozen=True)
class I:
    mnemonic: str
    rd: int
    rs1: int
    imm: int


@dataclass(frozen=True)
class S:
    mnemonic: str
    rs2: int
    base: int
    off: int


@dataclass(frozen=True)
class B:
    mnemonic: str
    rs1: int
    rs2: int
    disp: int


@dataclass(frozen=True)
class J:
    mnemonic: str
    disp: int


@dataclass(frozen=True)
class Jr:
    rs: int


@dataclass(frozen=True)
class In:
    rd: int
    port: int


@dataclass(frozen=True)
class Out:
    rs: int
    port: int


@dataclass(frozen=True)
class Trap:
    code: int


@dataclass(frozen=True)
class Halt:
    pass


Instruction = R | I | S | B | J | Jr | In | Out | Trap | Halt


def encode(ins: Instruction) -> int:
    if isinstance(ins, R):
        op = _opcode(ins.mnemonic)
        return (
            (op << OPCODE_SHIFT)
            | (_reg(ins.rd) << 21)
            | (_reg(ins.rs1) << 16)
            | (_reg(ins.rs2) << 11)
        )
    if isinstance(ins, I):
        op = _opcode(ins.mnemonic)
        imm = _imm16(ins.imm, unsigned=ins.mnemonic in ("lui", "ori"))
        return (
            (op << OPCODE_SHIFT)
            | (_reg(ins.rd) << 21)
            | (_reg(ins.rs1) << 16)
            | imm
        )
    if isinstance(ins, S):
        op = _opcode(ins.mnemonic)
        off = _imm16(ins.off, unsigned=ins.mnemonic == "out")
        return (
            (op << OPCODE_SHIFT)
            | (_reg(ins.rs2) << 21)
            | (_reg(ins.base) << 16)
            | off
        )
    if isinstance(ins, B):
        op = _opcode(ins.mnemonic)
        return (
            (op << OPCODE_SHIFT)
            | (_reg(ins.rs1) << 21)
            | (_reg(ins.rs2) << 16)
            | _imm16(ins.disp)
        )
    if isinstance(ins, J):
        return (OPCODE[ins.mnemonic] << OPCODE_SHIFT) | _imm26(ins.disp)
    if isinstance(ins, Jr):
        return (OPCODE["jr"] << OPCODE_SHIFT) | (_reg(ins.rs) << 16)
    if isinstance(ins, In):
        return (OPCODE["in"] << OPCODE_SHIFT) | (
            (_reg(ins.rd) << 21) | _imm16(ins.port, unsigned=True)
        )
    if isinstance(ins, Out):
        return (OPCODE["out"] << OPCODE_SHIFT) | (
            (_reg(ins.rs) << 21) | _imm16(ins.port, unsigned=True)
        )
    if isinstance(ins, Trap):
        return (OPCODE["trap"] << OPCODE_SHIFT) | _imm16(ins.code, unsigned=True)
    return HALT_WORD  # Halt


def mnemonic(ins: Instruction) -> str:
    if isinstance(ins, R):
        return f"{ins.mnemonic} R{ins.rd}, R{ins.rs1}, R{ins.rs2}"
    if isinstance(ins, I):
        if ins.mnemonic == "addi":
            return f"{ins.mnemonic} R{ins.rd}, R{ins.rs1}, {ins.imm}"
        if ins.mnemonic in ("lui", "ori"):
            return f"{ins.mnemonic} R{ins.rd}, {ins.imm}"
        return f"{ins.mnemonic} R{ins.rd}, {ins.imm}(R{ins.rs1})"
    if isinstance(ins, S):
        if ins.mnemonic in ("sw", "sb"):
            return f"{ins.mnemonic} R{ins.rs2}, {ins.off}(R{ins.base})"
        return f"{ins.mnemonic} R{ins.rs2}, {ins.off}"
    if isinstance(ins, B):
        return f"{ins.mnemonic} R{ins.rs1}, R{ins.rs2}, {ins.disp}"
    if isinstance(ins, J):
        return f"{ins.mnemonic} {ins.disp}"
    if isinstance(ins, Jr):
        return f"jr R{ins.rs}"
    if isinstance(ins, In):
        return f"in R{ins.rd}, {ins.port}"
    if isinstance(ins, Out):
        return f"out R{ins.rs}, {ins.port}"
    if isinstance(ins, Trap):
        return f"trap {ins.code}"
    return "halt"  # Halt


def listing_line(address: int, ins: Instruction) -> str:
    return f"{address} - {encode(ins):08x} - {mnemonic(ins)}"
