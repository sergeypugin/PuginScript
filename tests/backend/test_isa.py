"""Кодирование инструкций ISA: опкоды, форматы, границы immediate и смещений."""

from __future__ import annotations

import pytest

from src.machine.isa import (
    B,
    Halt,
    I,
    In,
    ISAError,
    J,
    Jr,
    Out,
    R,
    Trap,
    encode,
    listing_line,
    pack_bin,
)


def test_add() -> None:
    ins = R(mnemonic="add", rd=1, rs1=2, rs2=3)
    assert encode(ins) == 0x00221800
    assert listing_line(0, ins) == "0 - 00221800 - add R1, R2, R3"


def test_addi() -> None:
    ins = I(mnemonic="addi", rd=5, rs1=0, imm=42)
    assert encode(ins) == 0x40A0002A
    assert listing_line(1, ins) == "1 - 40a0002a - addi R5, R0, 42"


def test_addi_negative_imm() -> None:
    ins = I(mnemonic="addi", rd=5, rs1=0, imm=-32768)
    assert encode(ins) == 0x40A08000


def test_lui() -> None:
    ins = I(mnemonic="lui", rd=1, rs1=0, imm=0x1234)
    assert encode(ins) == 0x44201234


def test_lw() -> None:
    ins = I(mnemonic="lw", rd=9, rs1=2, imm=4)
    assert encode(ins) == 0x4D220004
    assert listing_line(5, ins) == "5 - 4d220004 - lw R9, 4(R2)"


def test_beq() -> None:
    ins = B(mnemonic="beq", rs1=1, rs2=2, disp=12)
    assert encode(ins) == 0xC022000C
    assert listing_line(3, ins) == "3 - c022000c - beq R1, R2, 12"


def test_bne_negative_disp() -> None:
    ins = B(mnemonic="bne", rs1=3, rs2=4, disp=-5)
    assert encode(ins) == 0xC464FFFB


def test_jmp() -> None:
    ins = J(mnemonic="jmp", disp=1000)
    assert encode(ins) == 0xD00003E8


def test_jal_negative_disp() -> None:
    ins = J(mnemonic="jal", disp=-100)
    assert encode(ins) == 0xD7FFFF9C


def test_jr() -> None:
    ins = Jr(rs=3)
    assert encode(ins) == 0x58030000


def test_in() -> None:
    ins = In(rd=4, port=1)
    assert encode(ins) == 0x5C800001


def test_port_field_unsigned_for_in_and_out() -> None:
    # поле Port беззнаковое в обеих командах PMIO; раньше in был знаковым,
    # хотя out -- беззнаковым
    assert encode(In(rd=4, port=40000)) == 0x5C809C40
    assert encode(Out(rs=4, port=40000)) == 0x88809C40
    for ins in (
        In(rd=4, port=-1),
        In(rd=4, port=65536),
        Out(rs=4, port=-1),
        Out(rs=4, port=65536),
    ):
        with pytest.raises(ISAError):
            encode(ins)


def test_out() -> None:
    ins = Out(rs=4, port=1)
    assert encode(ins) == 0x88800001


def test_trap() -> None:
    ins = Trap(code=5)
    assert encode(ins) == 0xF8000005
    assert listing_line(10, ins) == "10 - f8000005 - trap 5"


def test_halt() -> None:
    ins = Halt()
    assert encode(ins) == 0xFC000000
    assert listing_line(0, ins) == "0 - fc000000 - halt"


def test_unknown_mnemonic() -> None:
    with pytest.raises(ISAError):
        encode(R(mnemonic="xor", rd=1, rs1=2, rs2=3))


def test_register_out_of_range() -> None:
    with pytest.raises(ISAError):
        encode(R(mnemonic="add", rd=32, rs1=0, rs2=0))


def test_imm16_out_of_range() -> None:
    with pytest.raises(ISAError):
        encode(I(mnemonic="addi", rd=1, rs1=0, imm=40000))
    with pytest.raises(ISAError):
        encode(I(mnemonic="addi", rd=1, rs1=0, imm=-32769))


def test_lui_unsigned_boundary() -> None:
    assert encode(I(mnemonic="lui", rd=1, rs1=0, imm=65535)) == 0x4420FFFF
    with pytest.raises(ISAError):
        encode(I(mnemonic="lui", rd=1, rs1=0, imm=65536))


def test_disp26_out_of_range() -> None:
    with pytest.raises(ISAError):
        encode(J(mnemonic="jmp", disp=-33554433))
    with pytest.raises(ISAError):
        encode(J(mnemonic="jmp", disp=33554432))


def test_pack_bin_layout() -> None:
    static = b"\x00\x00\x00\x00\x2a\x00\x00\x00"
    first = R(mnemonic="add", rd=1, rs1=2, rs2=3)
    binary = pack_bin(static, [first, Halt()])

    assert int.from_bytes(binary[:4], "little") == len(static)
    assert binary[4:12] == static
    assert int.from_bytes(binary[12:16], "little") == encode(first)
    assert int.from_bytes(binary[16:20], "little") == 0xFC000000


def test_pack_bin_words_are_little_endian() -> None:
    static = b"\x00\x00\x00\x00"
    ins = I(mnemonic="addi", rd=5, rs1=0, imm=42)
    binary = pack_bin(static, [ins])

    assert int.from_bytes(binary[:4], "little") == 4
    assert binary[4:8] == static
    assert binary[8:12] == encode(ins).to_bytes(4, "little")


def test_listing_line_substitutes_label_for_branches_only() -> None:
    branch = B(mnemonic="beq", rs1=1, rs2=2, disp=12)
    plain = I(mnemonic="addi", rd=5, rs1=0, imm=42)

    assert listing_line(3, branch) == "3 - c022000c - beq R1, R2, 12"
    assert listing_line(3, branch, "endwhile") == "3 - c022000c - beq R1, R2, endwhile"
    assert listing_line(1, plain, "ignored") == "1 - 40a0002a - addi R5, R0, 42"
