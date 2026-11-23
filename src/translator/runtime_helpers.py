"""Реестр и генерация runtime-хелперов."""

from collections.abc import Callable
from typing import Any

from src.machine.config import INPUT_BUFFER_SIZE


ZERO = 0
RA = 1
SP = 2
FP = 3
RESULT_REG = 4
HP = 8
ARG_REGS = (4, 5, 6, 7)


class RuntimeEmitter:
    """Генерирует runtime-хелперы через состояние основного кодогенератора."""

    def __init__(self, backend: Any) -> None:
        self._backend = backend

    def __getattr__(self, name: str) -> Any:
        return getattr(self._backend, name)

    def emit(self, name: str) -> None:
        """Генерирует хелпер по его имени."""
        getattr(self, f"_{name}")()

    def _helper_prologue(self: Any, name: str) -> None:
        self._define_label(name)
        self._emit_addi(SP, SP, -8)
        self._emit_sw(FP, SP, 4)
        self._emit_sw(RA, SP, 0)
        self._emit_addi(FP, SP, 4)

    def _helper_epilogue(self: Any) -> None:
        old_fp = self._alloc_temp()
        self._emit_lw(RA, FP, -4)
        self._emit_lw(old_fp, FP, 0)
        self._emit_addi(SP, FP, 4)
        self._emit_mv(FP, old_fp)
        self._free_temp(old_fp)
        self._emit_jr(RA)

    def _rt_print_char(self: Any) -> None:
        """Выводит символ из регистра результата."""
        self._helper_prologue("rt_print_char")
        self._emit_out(RESULT_REG, 1)
        self._emit_mv(RESULT_REG, ZERO)
        self._helper_epilogue()

    def _rt_print_str(self: Any) -> None:
        """Выводит нуль-терминированную строку."""
        self._helper_prologue("rt_print_str")
        ptr = self._alloc_temp()
        ch = self._alloc_temp()
        loop = self._new_label("ps_loop")
        done = self._new_label("ps_done")
        self._emit_mv(ptr, RESULT_REG)
        self._define_label(loop)
        self._emit_lbu(ch, ptr, 0)
        self._emit_beq(ch, ZERO, done)
        self._emit_out(ch, 1)
        self._emit_addi(ptr, ptr, 1)
        self._emit_jmp(loop)
        self._define_label(done)
        self._emit_mv(RESULT_REG, ZERO)
        self._free_temp(ptr)
        self._free_temp(ch)
        self._helper_epilogue()

    def _rt_println_str(self: Any) -> None:
        """Выводит строку и перевод строки."""
        self._helper_prologue("rt_println_str")
        saved = self._save_temps()
        self._emit_jal("rt_print_str")
        self._restore_temps(saved)
        nl = self._alloc_temp()
        self._emit_addi(nl, ZERO, 10)
        self._emit_out(nl, 1)
        self._free_temp(nl)
        self._emit_mv(RESULT_REG, ZERO)
        self._helper_epilogue()

    def _rt_print_int(self: Any) -> None:
        """Выводит знаковое целое число."""
        self._helper_prologue("rt_print_int")
        val = self._alloc_temp()
        tmp = self._alloc_temp()
        count = self._alloc_temp()
        ten = self._alloc_temp()
        digit = self._alloc_temp()
        nonneg = self._new_label("pi_nonneg")
        loop_div = self._new_label("pi_div")
        done = self._new_label("pi_done")
        zero_case = self._new_label("pi_zero")
        not_int_min = self._new_label("pi_notintmin")

        self._emit_mv(val, RESULT_REG)
        self._emit_addi(count, ZERO, 0)
        self._emit_addi(ten, ZERO, 10)
        self._emit_slt(tmp, val, ZERO)
        self._emit_beq(tmp, ZERO, nonneg)
        self._emit_addi(tmp, ZERO, 45)
        self._emit_out(tmp, 1)
        int_min_val = self._alloc_temp()
        self._load_address(int_min_val, self._add_word(0x80000000))
        self._emit_lw(int_min_val, int_min_val, 0)
        is_int_min = self._alloc_temp()
        self._emit_seq(is_int_min, val, int_min_val)
        self._emit_beq(is_int_min, ZERO, not_int_min)
        self._load_address(tmp, self._add_string("2147483648"))
        ptr2 = self._alloc_temp()
        self._emit_mv(ptr2, tmp)
        loop_min = self._new_label("pi_min_loop")
        done_min = self._new_label("pi_min_done")
        self._define_label(loop_min)
        ch = self._alloc_temp()
        self._emit_lbu(ch, ptr2, 0)
        self._emit_beq(ch, ZERO, done_min)
        self._emit_out(ch, 1)
        self._emit_addi(ptr2, ptr2, 1)
        self._emit_jmp(loop_min)
        self._define_label(done_min)
        self._free_temp(ptr2)
        self._free_temp(ch)
        self._free_temp(int_min_val)
        self._free_temp(is_int_min)
        self._emit_jmp(done)
        self._define_label(not_int_min)
        self._emit_sub(val, ZERO, val)
        self._free_temp(int_min_val)
        self._free_temp(is_int_min)
        self._define_label(nonneg)
        self._emit_bne(val, ZERO, loop_div)
        self._define_label(zero_case)
        self._emit_addi(tmp, ZERO, 48)
        self._emit_out(tmp, 1)
        self._emit_jmp(done)
        self._define_label(loop_div)
        self._emit_mod(digit, val, ten)
        self._emit_slt(tmp, digit, ZERO)
        abs_ok = self._new_label("pi_abs")
        self._emit_beq(tmp, ZERO, abs_ok)
        self._emit_sub(digit, ZERO, digit)
        self._define_label(abs_ok)
        self._emit_addi(SP, SP, -4)
        self._emit_sw(digit, SP, 0)
        self._emit_addi(count, count, 1)
        self._emit_div(val, val, ten)
        self._emit_bne(val, ZERO, loop_div)
        loop_out = self._new_label("pi_out")
        self._define_label(loop_out)
        self._emit_lw(digit, SP, 0)
        self._emit_addi(SP, SP, 4)
        self._emit_addi(digit, digit, 48)
        self._emit_out(digit, 1)
        self._emit_addi(count, count, -1)
        self._emit_bne(count, ZERO, loop_out)
        self._define_label(done)
        self._emit_mv(RESULT_REG, ZERO)
        for r in (val, tmp, count, ten, digit):
            self._free_temp(r)
        self._helper_epilogue()

    def _rt_println_int(self: Any) -> None:
        """Выводит целое число и перевод строки."""
        self._helper_prologue("rt_println_int")
        saved = self._save_temps()
        self._emit_jal("rt_print_int")
        self._restore_temps(saved)
        nl = self._alloc_temp()
        self._emit_addi(nl, ZERO, 10)
        self._emit_out(nl, 1)
        self._free_temp(nl)
        self._emit_mv(RESULT_REG, ZERO)
        self._helper_epilogue()

    def _rt_print_bool(self: Any) -> None:
        """Выводит логическое значение."""
        self._helper_prologue("rt_print_bool")
        val = self._alloc_temp()
        is_false = self._alloc_temp()
        ptr = self._alloc_temp()
        true_label = self._new_label("pb_true")
        done = self._new_label("pb_done")
        self._emit_mv(val, RESULT_REG)
        self._emit_seq(is_false, val, ZERO)
        self._emit_beq(is_false, ZERO, true_label)
        self._load_address(ptr, self._add_string("false"))
        saved = self._save_temps()
        self._emit_mv(RESULT_REG, ptr)
        self._emit_jal("rt_print_str")
        self._restore_temps(saved)
        self._emit_jmp(done)
        self._define_label(true_label)
        self._load_address(ptr, self._add_string("true"))
        saved = self._save_temps()
        self._emit_mv(RESULT_REG, ptr)
        self._emit_jal("rt_print_str")
        self._restore_temps(saved)
        self._define_label(done)
        self._emit_mv(RESULT_REG, ZERO)
        self._free_temp(val)
        self._free_temp(is_false)
        self._free_temp(ptr)
        self._helper_epilogue()

    def _rt_println_bool(self: Any) -> None:
        """Выводит логическое значение и перевод строки."""
        self._helper_prologue("rt_println_bool")
        saved = self._save_temps()
        self._emit_jal("rt_print_bool")
        self._restore_temps(saved)
        nl = self._alloc_temp()
        self._emit_addi(nl, ZERO, 10)
        self._emit_out(nl, 1)
        self._free_temp(nl)
        self._emit_mv(RESULT_REG, ZERO)
        self._helper_epilogue()

    def _rt_len(self: Any) -> None:
        """Возвращает длину массива."""
        self._helper_prologue("rt_len")
        self._emit_lw(RESULT_REG, RESULT_REG, 0)
        self._helper_epilogue()

    def _rt_len_str(self: Any) -> None:
        """Возвращает длину нуль-терминированной строки."""
        self._helper_prologue("rt_len_str")
        ptr = self._alloc_temp()
        ch = self._alloc_temp()
        count = self._alloc_temp()
        loop = self._new_label("len_loop")
        done = self._new_label("len_done")
        self._emit_mv(ptr, RESULT_REG)
        self._emit_addi(count, ZERO, 0)
        self._define_label(loop)
        self._emit_lbu(ch, ptr, 0)
        self._emit_beq(ch, ZERO, done)
        self._emit_addi(count, count, 1)
        self._emit_addi(ptr, ptr, 1)
        self._emit_jmp(loop)
        self._define_label(done)
        self._emit_mv(RESULT_REG, count)
        self._free_temp(ptr)
        self._free_temp(ch)
        self._free_temp(count)
        self._helper_epilogue()

    def _rt_input_char(self: Any) -> None:
        """Читает один символ."""
        self._helper_prologue("rt_input_char")
        self._emit_in(RESULT_REG, 0)
        self._helper_epilogue()

    def _rt_input(self: Any) -> None:
        """Читает строку во временный буфер кучи."""
        self._helper_prologue("rt_input")
        buf = self._alloc_temp()
        ptr = self._alloc_temp()
        ch = self._alloc_temp()
        count = self._alloc_temp()
        limit = self._alloc_temp()
        loop = self._new_label("in_loop")
        done = self._new_label("in_done")
        too_long = self._new_label("in_long")

        self._emit_addi(buf, ZERO, INPUT_BUFFER_SIZE)
        self._emit_mv(RESULT_REG, HP)
        self._emit_add(HP, HP, buf)
        self._emit_slt(ch, SP, HP)
        ok = self._new_label("in_mem_ok")
        self._emit_beq(ch, ZERO, ok)
        self._emit_trap(3)
        self._define_label(ok)
        self._emit_mv(ptr, RESULT_REG)
        self._emit_addi(count, ZERO, 0)
        self._emit_addi(limit, ZERO, INPUT_BUFFER_SIZE - 1)
        self._define_label(loop)
        self._emit_in(ch, 0)
        nl = self._alloc_temp()
        self._emit_addi(nl, ZERO, 10)
        self._emit_seq(nl, ch, nl)
        self._emit_bne(nl, ZERO, done)
        self._emit_slt(nl, count, limit)
        self._emit_beq(nl, ZERO, too_long)
        self._free_temp(nl)
        self._emit_sb(ch, ptr, 0)
        self._emit_addi(ptr, ptr, 1)
        self._emit_addi(count, count, 1)
        self._emit_jmp(loop)
        self._define_label(too_long)
        self._emit_trap(8)
        self._define_label(done)
        self._emit_sb(ZERO, ptr, 0)
        for r in (buf, ptr, ch, count, limit):
            self._free_temp(r)
        self._helper_epilogue()

    def _rt_input_int(self: Any) -> None:
        """Читает знаковое целое число."""
        self._helper_prologue("rt_input_int")
        val = self._alloc_temp()
        sign = self._alloc_temp()
        ch = self._alloc_temp()
        ten = self._alloc_temp()
        digit = self._alloc_temp()
        tmp = self._alloc_temp()
        got_digit = self._alloc_temp()
        done = self._new_label("ii_done")
        loop = self._new_label("ii_loop")
        not_neg = self._new_label("ii_notneg")
        bad = self._new_label("ii_bad")
        do_trap = self._new_label("ii_trap")

        self._emit_addi(val, ZERO, 0)
        self._emit_addi(sign, ZERO, 1)
        self._emit_addi(ten, ZERO, 10)
        self._emit_addi(got_digit, ZERO, 0)

        self._emit_in(ch, 0)
        self._emit_addi(tmp, ZERO, 45)
        self._emit_seq(tmp, ch, tmp)
        self._emit_beq(tmp, ZERO, not_neg)
        self._emit_addi(sign, ZERO, -1)
        self._emit_in(ch, 0)
        self._define_label(not_neg)
        self._define_label(loop)
        self._emit_addi(tmp, ZERO, 10)
        self._emit_seq(tmp, ch, tmp)
        self._emit_bne(tmp, ZERO, done)
        self._emit_addi(tmp, ZERO, 13)
        self._emit_seq(tmp, ch, tmp)
        self._emit_bne(tmp, ZERO, done)
        self._emit_addi(tmp, ZERO, 48)
        self._emit_slt(digit, ch, tmp)
        self._emit_bne(digit, ZERO, bad)
        self._emit_addi(tmp, ZERO, 58)
        self._emit_slt(digit, ch, tmp)
        self._emit_beq(digit, ZERO, bad)
        self._emit_addi(got_digit, ZERO, 1)
        self._emit_addi(tmp, ZERO, 48)
        self._emit_sub(digit, ch, tmp)
        self._emit_slt(tmp, val, ZERO)
        self._emit_bne(tmp, ZERO, do_trap)

        limit = self._alloc_temp()
        self._load_address(limit, self._add_word(214748364))
        self._emit_lw(limit, limit, 0)
        self._emit_slt(tmp, limit, val)
        self._emit_bne(tmp, ZERO, do_trap)
        below_limit = self._new_label("ii_below_limit")
        self._emit_seq(tmp, val, limit)
        self._emit_beq(tmp, ZERO, below_limit)
        positive = self._new_label("ii_positive")
        self._emit_addi(tmp, ZERO, 1)
        self._emit_seq(tmp, sign, tmp)
        self._emit_bne(tmp, ZERO, positive)
        self._emit_addi(tmp, ZERO, 8)
        threshold_ready = self._new_label("ii_threshold")
        self._emit_jmp(threshold_ready)
        self._define_label(positive)
        self._emit_addi(tmp, ZERO, 7)
        self._define_label(threshold_ready)
        self._emit_slt(tmp, tmp, digit)
        self._emit_bne(tmp, ZERO, do_trap)
        self._define_label(below_limit)
        self._free_temp(limit)
        self._emit_mul(val, val, ten)
        self._emit_add(val, val, digit)
        self._emit_in(ch, 0)
        self._emit_jmp(loop)
        self._define_label(bad)
        self._emit_jmp(do_trap)
        self._define_label(do_trap)
        self._emit_trap(7)
        self._define_label(done)
        self._emit_beq(got_digit, ZERO, do_trap)
        one = self._new_label("ii_pos")
        self._emit_addi(tmp, ZERO, 1)
        self._emit_seq(tmp, sign, tmp)
        self._emit_bne(tmp, ZERO, one)
        self._emit_sub(val, ZERO, val)
        self._define_label(one)
        self._emit_mv(RESULT_REG, val)
        for r in (val, sign, ch, ten, digit, tmp, got_digit):
            self._free_temp(r)
        self._helper_epilogue()

    def _rt_pow(self: Any) -> None:
        """Вычисляет целую степень."""
        self._helper_prologue("rt_pow")
        base = self._alloc_temp()
        exp = self._alloc_temp()
        res = self._alloc_temp()
        tmp = self._alloc_temp()
        loop = self._new_label("pow_loop")
        done = self._new_label("pow_done")
        ok = self._new_label("pow_ok")

        self._emit_mv(base, RESULT_REG)
        self._emit_mv(exp, ARG_REGS[1])
        self._emit_slt(tmp, exp, ZERO)
        self._emit_beq(tmp, ZERO, ok)
        self._emit_trap(9)
        self._define_label(ok)
        self._emit_addi(res, ZERO, 1)
        self._define_label(loop)
        self._emit_beq(exp, ZERO, done)
        self._emit_mul(res, res, base)
        self._emit_addi(exp, exp, -1)
        self._emit_jmp(loop)
        self._define_label(done)
        self._emit_add(RESULT_REG, res, ZERO)
        for r in (base, exp, res, tmp):
            self._free_temp(r)
        self._helper_epilogue()

    def _rt_concat(self: Any) -> None:
        """Объединяет две строки в куче."""
        self._helper_prologue("rt_concat")
        left = self._alloc_temp()
        right = self._alloc_temp()
        l1 = self._alloc_temp()
        l2 = self._alloc_temp()
        total = self._alloc_temp()
        dst = self._alloc_temp()
        ptr = self._alloc_temp()
        ch = self._alloc_temp()
        tmp = self._alloc_temp()
        rem = self._alloc_temp()
        neg4 = self._alloc_temp()

        self._emit_mv(left, RESULT_REG)
        self._emit_mv(right, ARG_REGS[1])

        self._emit_addi(l1, ZERO, 0)
        self._emit_mv(ptr, left)
        loop1 = self._new_label("cat_l1")
        done1 = self._new_label("cat_d1")
        self._define_label(loop1)
        self._emit_lbu(ch, ptr, 0)
        self._emit_beq(ch, ZERO, done1)
        self._emit_addi(l1, l1, 1)
        self._emit_addi(ptr, ptr, 1)
        self._emit_jmp(loop1)
        self._define_label(done1)

        self._emit_addi(l2, ZERO, 0)
        self._emit_mv(ptr, right)
        loop2 = self._new_label("cat_l2")
        done2 = self._new_label("cat_d2")
        self._define_label(loop2)
        self._emit_lbu(ch, ptr, 0)
        self._emit_beq(ch, ZERO, done2)
        self._emit_addi(l2, l2, 1)
        self._emit_addi(ptr, ptr, 1)
        self._emit_jmp(loop2)
        self._define_label(done2)

        self._emit_add(total, l1, l2)
        self._emit_addi(total, total, 1)
        self._emit_mv(dst, HP)
        self._emit_add(HP, HP, total)


        self._emit_addi(rem, ZERO, 3)
        self._emit_add(HP, HP, rem)
        self._emit_lui(neg4, 0xFFFF)
        self._emit_ori(neg4, neg4, 0xFFFC)
        self._emit_and(HP, HP, neg4)
        self._free_temp(rem)
        self._free_temp(neg4)

        self._emit_slt(tmp, SP, HP)
        ok = self._new_label("cat_ok")
        self._emit_beq(tmp, ZERO, ok)
        self._emit_trap(3)
        self._define_label(ok)

        self._emit_mv(ptr, dst)
        src = self._alloc_temp()
        self._emit_mv(src, left)
        c1 = self._new_label("cat_c1")
        cd1 = self._new_label("cat_cd1")
        self._define_label(c1)
        self._emit_lbu(ch, src, 0)
        self._emit_beq(ch, ZERO, cd1)
        self._emit_sb(ch, ptr, 0)
        self._emit_addi(src, src, 1)
        self._emit_addi(ptr, ptr, 1)
        self._emit_jmp(c1)
        self._define_label(cd1)

        self._emit_mv(src, right)
        c2 = self._new_label("cat_c2")
        cd2 = self._new_label("cat_cd2")
        self._define_label(c2)
        self._emit_lbu(ch, src, 0)
        self._emit_beq(ch, ZERO, cd2)
        self._emit_sb(ch, ptr, 0)
        self._emit_addi(src, src, 1)
        self._emit_addi(ptr, ptr, 1)
        self._emit_jmp(c2)
        self._define_label(cd2)

        self._emit_sb(ZERO, ptr, 0)
        self._emit_mv(RESULT_REG, dst)
        for r in (left, right, l1, l2, total, dst, ptr, ch, tmp, src):
            self._free_temp(r)
        self._helper_epilogue()

    def _rt_str_eq(self: Any) -> None:
        """Сравнивает две строки по содержимому."""
        self._helper_prologue("rt_str_eq")
        left = self._alloc_temp()
        right = self._alloc_temp()
        left_char = self._alloc_temp()
        right_char = self._alloc_temp()
        loop = self._new_label("str_eq_loop")
        different = self._new_label("str_eq_different")
        done = self._new_label("str_eq_done")

        self._emit_mv(left, RESULT_REG)
        self._emit_mv(right, ARG_REGS[1])
        self._define_label(loop)
        self._emit_lbu(left_char, left, 0)
        self._emit_lbu(right_char, right, 0)
        self._emit_bne(left_char, right_char, different)
        self._emit_beq(left_char, ZERO, done)
        self._emit_addi(left, left, 1)
        self._emit_addi(right, right, 1)
        self._emit_jmp(loop)
        self._define_label(different)
        self._emit_mv(RESULT_REG, ZERO)
        self._emit_jmp("str_eq_return")
        self._define_label(done)
        self._emit_mv(RESULT_REG, 1)
        self._define_label("str_eq_return")
        self._free_temp(left)
        self._free_temp(right)
        self._free_temp(left_char)
        self._free_temp(right_char)
        self._helper_epilogue()

    def _rt_int_to_str(self: Any) -> None:
        """Преобразует целое число в строку в куче."""
        """Целое в строку на куче (для конкатенации str + int)."""
        self._helper_prologue("rt_int_to_str")
        val = self._alloc_temp()
        tval = self._alloc_temp()
        tmp = self._alloc_temp()
        count = self._alloc_temp()
        ten = self._alloc_temp()
        digit = self._alloc_temp()
        ptr = self._alloc_temp()
        str_start = self._alloc_temp()
        sign_reg = self._alloc_temp()

        nonneg = self._new_label("its_nonneg")
        count_loop = self._new_label("its_count")
        count_done = self._new_label("its_count_done")
        fill_digits = self._new_label("its_fill_digits")
        fill_loop = self._new_label("its_fill")
        fill_done = self._new_label("its_fill_done")

        self._emit_mv(val, RESULT_REG)
        self._emit_mv(tval, val)
        self._emit_addi(count, ZERO, 0)
        self._emit_addi(ten, ZERO, 10)
        self._emit_addi(sign_reg, ZERO, 0)

        self._emit_slt(tmp, val, ZERO)
        self._emit_beq(tmp, ZERO, nonneg)
        self._emit_addi(sign_reg, ZERO, 1)
        self._emit_sub(val, ZERO, val)
        self._emit_mv(tval, val)

        self._define_label(nonneg)
        self._emit_bne(tval, ZERO, count_loop)
        self._emit_addi(count, count, 1)
        self._emit_jmp(count_done)

        self._define_label(count_loop)
        self._emit_addi(count, count, 1)
        self._emit_div(tval, tval, ten)
        self._emit_bne(tval, ZERO, count_loop)

        self._define_label(count_done)
        sign_present = self._alloc_temp()
        self._emit_addi(sign_present, ZERO, 0)
        self._emit_seq(sign_present, sign_reg, sign_present)
        no_sign = self._new_label("its_no_sign")
        self._emit_beq(sign_present, ZERO, no_sign)
        self._emit_addi(count, count, 1)
        self._define_label(no_sign)
        self._free_temp(sign_present)
        self._emit_addi(tmp, count, 1)
        self._emit_mv(str_start, HP)
        self._emit_add(HP, HP, tmp)

        # '\0' в конце
        self._emit_mv(ptr, str_start)
        self._emit_add(ptr, ptr, count)
        self._emit_sb(ZERO, ptr, 0)

        # Если отрицательное -- записываем '-'
        self._emit_addi(tmp, ZERO, 0)
        self._emit_seq(tmp, sign_reg, tmp)
        self._emit_bne(tmp, ZERO, fill_digits)
        self._emit_addi(tmp, ZERO, 45)
        self._emit_mv(ptr, str_start)
        self._emit_sb(tmp, ptr, 0)

        self._define_label(fill_digits)
        # Заполняем цифры с конца
        self._emit_mv(ptr, str_start)
        self._emit_add(ptr, ptr, count)
        self._emit_addi(ptr, ptr, -1)
        self._emit_addi(tmp, ZERO, 0)
        self._emit_seq(tmp, val, tmp)
        self._emit_beq(tmp, ZERO, fill_loop)
        # val == 0: записываем '0'
        self._emit_addi(tmp, ZERO, 48)
        self._emit_mv(ptr, str_start)
        self._emit_sb(tmp, ptr, 0)
        self._emit_jmp(fill_done)

        self._define_label(fill_loop)
        self._emit_slt(tmp, ZERO, val)
        self._emit_beq(tmp, ZERO, fill_done)
        self._emit_mod(digit, val, ten)
        self._emit_addi(tmp, ZERO, 48)
        self._emit_add(tmp, tmp, digit)
        self._emit_sb(tmp, ptr, 0)
        self._emit_addi(ptr, ptr, -1)
        self._emit_div(val, val, ten)
        self._emit_jmp(fill_loop)

        self._define_label(fill_done)
        self._emit_mv(RESULT_REG, str_start)
        for r in (val, tval, tmp, count, ten, digit, ptr, str_start, sign_reg):
            self._free_temp(r)
        self._helper_epilogue()

    def _rt_bool_to_str(self: Any) -> None:
        """Преобразует логическое значение в статическую строку."""
        """Булево в строку "true"/"false" (статические данные, HP не трогаем)."""
        self._helper_prologue("rt_bool_to_str")
        val = self._alloc_temp()
        tmp = self._alloc_temp()
        str_start = self._alloc_temp()

        is_false = self._new_label("bts_false")
        done = self._new_label("bts_done")

        self._emit_mv(val, RESULT_REG)
        self._emit_addi(tmp, ZERO, 0)
        self._emit_seq(tmp, val, tmp)
        self._emit_beq(tmp, ZERO, is_false)

        self._load_address(str_start, self._add_string("true"))
        self._emit_jmp(done)

        self._define_label(is_false)
        self._load_address(str_start, self._add_string("false"))

        self._define_label(done)
        self._emit_mv(RESULT_REG, str_start)
        for r in (val, tmp, str_start):
            self._free_temp(r)
        self._helper_epilogue()



class RuntimeHelpers:
    """Регистрирует runtime-вызовы и генерирует их зависимости."""

    _DEPENDENCIES: dict[str, frozenset[str]] = {
        "rt_println_str": frozenset({"rt_print_str"}),
        "rt_println_int": frozenset({"rt_print_int"}),
        "rt_print_bool": frozenset({"rt_print_str"}),
        "rt_println_bool": frozenset({"rt_print_bool"}),
    }
    _ORDER = (
        "rt_print_char",
        "rt_print_str",
        "rt_println_str",
        "rt_print_int",
        "rt_println_int",
        "rt_print_bool",
        "rt_println_bool",
        "rt_len",
        "rt_len_str",
        "rt_input_char",
        "rt_input",
        "rt_input_int",
        "rt_pow",
        "rt_concat",
        "rt_str_eq",
        "rt_int_to_str",
        "rt_bool_to_str",
    )

    def __init__(self, emit_helper: Callable[[str], None]) -> None:
        self._emit_helper = emit_helper
        self._needed: set[str] = set()
        self._emitted: set[str] = set()

    @property
    def needed(self) -> frozenset[str]:
        """Возвращает зарегистрированные runtime-вызовы."""
        return frozenset(self._needed)

    def use(self, name: str) -> None:
        """Регистрирует runtime-хелпер без немедленной генерации его тела."""
        if name not in self._ORDER:
            raise ValueError(f"неизвестный runtime-хелпер: {name}")
        self._needed.add(name)

    def emit_needed(self) -> None:
        """Генерирует каждый нужный хелпер и его зависимости один раз."""
        pending = set(self._needed)
        while pending:
            name = pending.pop()
            if name in self._emitted:
                continue
            self._emitted.add(name)
            dependencies = self._DEPENDENCIES.get(name, frozenset())
            pending.update(dependencies)
            self._needed.update(dependencies)

        for name in self._ORDER:
            if name in self._needed:
                self._emit_helper(name)

    def clear(self) -> None:
        """Сбрасывает состояние перед повторной генерацией тем же объектом."""
        self._needed.clear()
        self._emitted.clear()
