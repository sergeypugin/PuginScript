"""Консольный интерфейс транслятора: программа .ps на входе, .bin на выходе."""

import argparse
import sys
from pathlib import Path

from src.translator.codegen import CodegenError, Translation, codegen, listing
from src.translator.errors import TranslatorError
from src.translator.parser import parse
from src.translator.semantic import check


def _translate(source: Path) -> Translation | None:
    """Прогоняет полный пайплайн; диагностика печатается в stderr."""
    try:
        program = parse(str(source))
    except TranslatorError as error:
        print(error, file=sys.stderr)
        return None

    result = check(program)
    if result.errors:
        for error in result.errors:
            print(error, file=sys.stderr)
        return None

    try:
        return codegen(program, result)
    except CodegenError as error:
        print(error, file=sys.stderr)
        return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="puginscript",
        description="Транслятор PuginScript: программа .ps -> .bin",
    )
    parser.add_argument("source", type=Path, help="транслируемая программа (.ps)")
    parser.add_argument(
        "-o",
        "--outdir",
        type=Path,
        help="каталог вывода (по умолчанию -- рядом с исходником)",
    )
    parser.add_argument(
        "--listing",
        action="store_true",
        help="дополнительно записать .lst: листинг с именами меток и статикой",
    )
    options = parser.parse_args(argv)

    if options.source.suffix.lower() != ".ps":
        print(f"ожидался файл с расширением .ps: {options.source}", file=sys.stderr)
        return 1

    translation = _translate(options.source)
    if translation is None:
        return 1

    outdir = options.outdir if options.outdir is not None else options.source.parent
    stem = options.source.stem
    outputs = [outdir / f"{stem}.bin"]
    if options.listing:
        outputs.append(outdir / f"{stem}.lst")

    try:
        outdir.mkdir(parents=True, exist_ok=True)
        outputs[0].write_bytes(translation.binary)
        if options.listing:
            outputs[1].write_text(
                listing(translation) + "\n", encoding="utf-8", newline="\n"
            )
    except OSError as error:
        # чистка частичного вывода: неполный набор артефактов опаснее их отсутствия;
        # неудаляемый файл чистке не мешает -- диагностике важнее дойти до пользователя
        for output in outputs:
            try:
                output.unlink(missing_ok=True)
            except OSError:
                pass
        print(f"не удалось записать результат: {error}", file=sys.stderr)
        return 1
    return 0
