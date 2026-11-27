from src.machine.config import INPUT_BUFFER_SIZE, RAM_SIZE
from src.machine.isa import I, Instruction, J, Out, R, S, Trap
from src.translator.codegen import Codegen, codegen
from src.translator.parser import parse_text
from src.translator.runtime_helpers import RuntimeHelpers
from src.translator.semantic import check


def generate(source: str) -> tuple[bytes, list[Instruction]]:
    program = parse_text(source, "test")
    result = check(program)
    assert not result.errors
    return codegen(program, result)



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
