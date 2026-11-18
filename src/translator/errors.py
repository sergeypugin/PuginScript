"""Общая ошибка трансляции с привязкой к месту в исходнике"""

from __future__ import annotations

from .syntax_tree import SourceLocation


class TranslatorError(Exception):
    """Ошибка лексера, парсера или семантики; трансляция останавливается на первой"""

    def __init__(self, location: SourceLocation, message: str) -> None:
        super().__init__(f"{location.file}:{location.line}:{location.column}: {message}")
        self.location = location
        self.message = message
