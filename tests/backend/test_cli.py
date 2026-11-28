"""Тесты консольного интерфейса транслятора."""

from __future__ import annotations

import os
import re
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from src.translator.cli import main

_ROOT = Path(__file__).resolve().parents[2]
_GOLDEN = _ROOT / "tests" / "backend" / "golden" / "listing"
_INSTRUCTION_LINE = re.compile(r"^\d+ - [0-9a-f]{8} - ")


def _golden_layout(text: str) -> tuple[int, int]:
    """Размер статики и число инструкций из golden-файла."""
    static_part, _, listing = text.partition("---\n")
    static_header = static_part.splitlines()[0]
    static_size = int(static_header.removeprefix("static "))
    instructions = sum(
        1 for line in listing.splitlines() if _INSTRUCTION_LINE.match(line)
    )
    return static_size, instructions


def test_cli_writes_bin_and_listing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    outdir = tmp_path / "out"
    source = _ROOT / "examples" / "hello.ps"

    assert main([str(source), "-o", str(outdir), "--listing"]) == 0
    assert capsys.readouterr().out == ""

    assert (outdir / "hello.lst").read_text(encoding="utf-8") == (
        (_GOLDEN / "hello.lst").read_text(encoding="utf-8")
    )
    static_size, instructions = _golden_layout(
        (_GOLDEN / "hello.lst").read_text(encoding="utf-8")
    )
    binary = (outdir / "hello.bin").read_bytes()
    assert int.from_bytes(binary[:4], "little") == static_size
    assert len(binary) == 4 + static_size + 4 * instructions


def test_cli_defaults_to_source_directory(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "tiny.ps"
    source.write_text("int x = 1;", encoding="utf-8")

    assert main([str(source)]) == 0
    assert capsys.readouterr().out == ""

    assert (tmp_path / "tiny.bin").exists()
    assert not (tmp_path / "tiny.lst").exists()


def test_cli_creates_output_directory(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "tiny.ps"
    source.write_text("int x = 1;", encoding="utf-8")
    outdir = tmp_path / "nested" / "out"

    assert main([str(source), "-o", str(outdir)]) == 0
    assert capsys.readouterr().out == ""

    assert (outdir / "tiny.bin").exists()


def test_cli_reports_semantic_errors(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "bad.ps"
    source.write_text("x = 1;", encoding="utf-8")

    assert main([str(source), "-o", str(tmp_path)]) == 1

    captured = capsys.readouterr()
    assert captured.err.count(":1:") == 1
    assert not (tmp_path / "bad.bin").exists()


def test_cli_reports_parse_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "broken.ps"
    source.write_text("int x = ;", encoding="utf-8")

    assert main([str(source), "-o", str(tmp_path)]) == 1

    captured = capsys.readouterr()
    assert ":1:" in captured.err
    assert not (tmp_path / "broken.bin").exists()


def test_cli_reports_missing_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main([str(tmp_path / "nope.ps"), "-o", str(tmp_path)]) == 1

    assert "не удалось открыть файл" in capsys.readouterr().err


def test_cli_rejects_non_ps_source(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "notes.txt"
    source.write_text("int x = 1;", encoding="utf-8")

    assert main([str(source), "-o", str(tmp_path)]) == 1

    assert "ожидался файл с расширением .ps" in capsys.readouterr().err


def test_cli_reports_codegen_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # константы с большими значениями уходят в статику словами: забиваем её до отказа
    # (каждое слово -- 4 байта, 12000 слов > 32764 байт с запасом)
    source = tmp_path / "huge.ps"
    constants = "\n".join(
        f"const int c{i} = {0x10000000 + i};" for i in range(12000)
    )
    source.write_text(constants, encoding="utf-8")

    assert main([str(source), "-o", str(tmp_path)]) == 1

    captured = capsys.readouterr()
    assert "статика превышает" in captured.err
    assert not (tmp_path / "huge.bin").exists()


def test_cli_reports_write_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "tiny.ps"
    source.write_text("int x = 1;", encoding="utf-8")
    outdir = tmp_path / "out"
    outdir.mkdir()
    stale = outdir / "tiny.lst"
    stale.write_text("старый листинг", encoding="utf-8")
    os.chmod(stale, stat.S_IRUSR)

    assert main([str(source), "-o", str(outdir), "--listing"]) == 1

    captured = capsys.readouterr()
    assert "не удалось записать результат" in captured.err
    # bin был записан до падения записи листинга и подчищен при откате
    assert not (outdir / "tiny.bin").exists()
    # на Windows read-only файл неудаляем и переживает откат, на Linux -- нет
    if stale.exists():
        os.chmod(stale, stat.S_IRUSR | stat.S_IWUSR)


def test_python_dash_m_entry_point(tmp_path: Path) -> None:
    outdir = tmp_path / "out"

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "src.translator",
            str(_ROOT / "examples" / "hello.ps"),
            "-o",
            str(outdir),
            "--listing",
        ],
        capture_output=True,
        text=True,
        cwd=_ROOT,
        check=False,
        stdin=subprocess.DEVNULL,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == ""
    assert (outdir / "hello.lst").exists()
    assert (outdir / "hello.bin").exists()
