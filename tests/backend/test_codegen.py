import re
from pathlib import Path

from src.machine.config import INPUT_BUFFER_SIZE, RAM_SIZE
from src.machine.isa import Halt, I, Instruction, J, Out, R, S, Trap, encode
from src.translator.codegen import Codegen, codegen, render_listing
from src.translator.parser import parse, parse_text
from src.translator.runtime_helpers import RuntimeHelpers
from src.translator.semantic import check

_ROOT = Path(__file__).resolve().parents[2]
_EXAMPLES = _ROOT / "examples"

LISTING_LINE = re.compile(r"^\d+ - [0-9a-f]{8} - ")
LABEL_LINE = re.compile(r"^\w+:$")


def generate(source: str) -> tuple[bytes, tuple[Instruction, ...]]:
    program = parse_text(source, "test")
    result = check(program)
    assert not result.errors
    translation = codegen(program, result)
    return translation.static, translation.code



def test_codegen_emits_only_used_runtime_helpers() -> None:
    plain_program = parse_text("int value = 1;", "test")
    plain_result = check(plain_program)
    plain_codegen = Codegen(plain_program, plain_result)
    plain_codegen.generate()

    println_program = parse_text("println(1);", "test")
    println_result = check(println_program)
    println_codegen = Codegen(println_program, println_result)
    println_codegen.generate()

    bool_program = parse_text("println(true);", "test")
    bool_result = check(bool_program)
    bool_codegen = Codegen(bool_program, bool_result)
    bool_codegen.generate()

    # тесты намеренно проверяют внутренности кодогенератора, поэтому доступ к
    # _labels подавлен точечно, на конкретных строках, а не на весь файл
    plain_labels = plain_codegen._labels  # pyright: ignore[reportPrivateUsage]
    println_labels = println_codegen._labels  # pyright: ignore[reportPrivateUsage]
    bool_labels = bool_codegen._labels  # pyright: ignore[reportPrivateUsage]

    assert not any(name.startswith("rt_") for name in plain_labels)
    assert "rt_println_int" in println_labels
    assert "rt_print_int" in println_labels
    assert "rt_input" not in println_labels
    assert "rt_println_bool" in bool_labels
    assert "rt_print_bool" in bool_labels
    assert "rt_print_str" in bool_labels


def test_runtime_helper_registry_resolves_dependencies() -> None:
    emitted: list[str] = []
    helpers = RuntimeHelpers(emitted.append)
    helpers.use("rt_println_bool")
    helpers.emit_needed()

    assert emitted == ["rt_print_str", "rt_print_bool", "rt_println_bool"]


def test_codegen_places_first_slot_at_frame_boundary() -> None:
    _, instructions = generate(
        """
        def main() -> int {
            int value = 1;
            return value;
        }
        """
    )
    assert any(isinstance(ins, S) and ins.off == -8 for ins in instructions)
    assert not any(isinstance(ins, S) and ins.off == -12 for ins in instructions)


def test_codegen_lays_out_runtime_static_data_before_heap_init() -> None:
    static_data, instructions = generate("println(-1);")
    hp_init = next(  # addi R8, R0, <imm>, где R8 - HP (указатель кучи)
        ins.imm
        for ins in instructions
        if isinstance(ins, I) and ins.mnemonic == "addi" and ins.rd == 8 and ins.rs1 == 0
    )
    assert hp_init == len(static_data)
    assert b"2147483648\0" in static_data


def test_codegen_zeroes_new_arrays_but_not_array_literals() -> None:
    _, new_instructions = generate("int[] values = new int[2];")
    assert any(
        isinstance(ins, S) and ins.mnemonic == "sw" and ins.rs2 == 0
        for ins in new_instructions
    )

    _, literal_instructions = generate("int[] values = [1, 2];")
    assert not any(
        isinstance(ins, S) and ins.mnemonic == "sw" and ins.rs2 == 0
        for ins in literal_instructions
    )


def test_codegen_checks_array_bounds_and_keeps_compound_assignment() -> None:
    _, instructions = generate(
        """
        int[] values = [5];
        values[0] += 2;
        println(values[0]);
        """
    )
    assert any(isinstance(ins, Trap) and ins.code == 4 for ins in instructions)
    assert any(isinstance(ins, R) and ins.mnemonic == "add" for ins in instructions)


def test_codegen_uses_content_comparison_for_strings() -> None:
    _, instructions = generate(
        """
        str left = input();
        str right = input();
        println(left == right);
        """
    )
    assert any(isinstance(ins, J) and ins.mnemonic == "jal" for ins in instructions)
    assert any(isinstance(ins, I) and ins.mnemonic == "lbu" for ins in instructions)


def test_codegen_checks_input_int_overflow_thresholds() -> None:
    static_data, instructions = generate("println(input_int());")
    assert (214748364).to_bytes(4, "little") in static_data
    assert any(isinstance(ins, Trap) and ins.code == 7 for ins in instructions)
    assert any(isinstance(ins, R) and ins.mnemonic == "slt" for ins in instructions)


def test_codegen_checks_new_size_before_advancing_heap() -> None:
    _, instructions = generate("int size = input_int(); int[] values = new int[size];")
    trap_index = next(
        index
        for index, ins in enumerate(instructions)
        if isinstance(ins, Trap) and ins.code == 10
    )
    hp_advance_index = next(
        index
        for index, ins in enumerate(instructions)
        if isinstance(ins, R) and ins.mnemonic == "add" and ins.rd == 8 and ins.rs1 == 8
    )
    assert trap_index < hp_advance_index


def test_codegen_loads_array_size_limit_without_static_word() -> None:
    static_data, instructions = generate("int size = input_int(); int[] values = new int[size];")
    max_size = (RAM_SIZE - 4) // 4
    high, low = divmod(max_size, 65536)
    limit_loaded = False
    for index, ins in enumerate(instructions):
        if not isinstance(ins, I) or ins.mnemonic != "lui" or ins.imm != high:
            continue
        if index + 1 >= len(instructions):
            continue
        next_ins = instructions[index + 1]
        if (
            isinstance(next_ins, I)
            and next_ins.mnemonic == "ori"
            and next_ins.rd == ins.rd
            and next_ins.rs1 == ins.rd
            and next_ins.imm == low
        ):
            limit_loaded = True
            break
    assert limit_loaded
    assert max_size.to_bytes(4, "little") not in static_data
    assert sum(isinstance(ins, Trap) and ins.code == 3 for ins in instructions) >= 2


def test_codegen_uses_configured_input_buffer_size() -> None:
    _, instructions = generate("input();")
    assert any(
        isinstance(ins, I) and ins.mnemonic == "addi" and ins.imm == INPUT_BUFFER_SIZE
        for ins in instructions
    )
    assert any(
        isinstance(ins, I) and ins.mnemonic == "addi" and ins.imm == INPUT_BUFFER_SIZE - 1
        for ins in instructions
    )


def test_codegen_converts_bool_to_text_and_println_without_arguments() -> None:
    _, instructions = generate(
        """
        println(true + "!");
        println();
        """
    )
    assert any(isinstance(ins, Out) and ins.port == 1 for ins in instructions)
    assert any(isinstance(ins, J) and ins.mnemonic == "jal" for ins in instructions)


def test_listing_keeps_label_names() -> None:
    program = parse(str(_EXAMPLES / "power_many.ps"))
    result = check(program)
    assert not result.errors
    translation = codegen(program, result)

    lines = translation.listing.splitlines()
    assert lines, "листинг не должен быть пустым"
    assert all(LISTING_LINE.match(line) or LABEL_LINE.match(line) for line in lines)
    assert "script_func:" in lines

    label_names = {line[:-1] for line in lines if LABEL_LINE.match(line)}
    branch_targets = [
        line.split(" - ")[2].split()[-1]
        for line in lines
        if LISTING_LINE.match(line)
        and line.split(" - ")[2].split()[0] in ("beq", "bne", "jmp", "jal")
    ]
    assert branch_targets, "в программе должны быть ветвления"
    assert all(target in label_names for target in branch_targets)


def test_listing_hex_matches_patched_code() -> None:
    program = parse_text("println(42);", "test")
    result = check(program)
    assert not result.errors
    translation = codegen(program, result)

    instruction_lines = [
        line for line in translation.listing.splitlines() if LISTING_LINE.match(line)
    ]
    assert len(instruction_lines) == len(translation.code)

    for index, (line, ins) in enumerate(
        zip(instruction_lines, translation.code, strict=True)
    ):
        address, word, text = line.split(" - ", 2)
        assert int(address) == index
        assert word == f"{encode(ins):08x}"
        assert text


def test_codegen_binary_contains_static_and_code() -> None:
    program = parse_text("int x = 1;", "test")
    result = check(program)
    assert not result.errors
    translation = codegen(program, result)
    binary = translation.binary

    assert int.from_bytes(binary[:4], "little") == len(translation.static)
    assert binary[4 : 4 + len(translation.static)] == translation.static
    assert len(binary) == 4 + len(translation.static) + 4 * len(translation.code)


def test_render_listing_substitutes_label_names() -> None:
    listing = render_listing([J("jmp", 5), Halt()], {"loop": 1}, [(0, "loop")])

    assert listing.splitlines() == [
        "0 - d0000005 - jmp loop",
        "loop:",
        "1 - fc000000 - halt",
    ]


def test_render_listing_appends_labels_after_last_instruction() -> None:
    assert render_listing([], {}, []) == ""

    labels_at_end = render_listing([], {"end": 0, "start": 0}, [])
    assert labels_at_end.splitlines() == ["end:", "start:"]
