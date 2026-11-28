# Инструментарий PuginScript

## Оглавление

- [Конфигурация](#конфигурация)
- [Python](#python)
  - [Установка зависимостей](#установка-зависимостей)
  - [Python 3.14](#python-314)
  - [pytest](#pytest)
  - [pyright](#pyright)
  - [ruff](#ruff)
- [Не Python](#не-python)
  - [.editorconfig](#editorconfig)
  - [GitHub Actions](#github-actions)

## Конфигурация

Центр настройки -- [pyproject.toml](../pyproject.toml): помимо сборки пакета, он содержит секции всех компонентов проверки -- pytest, pyright и ruff.

Помимо этого:
- [.editorconfig](../.editorconfig) -- конфигурация редактора
- [.github/workflows/](../.github/workflows/) -- конфигурация GitHub Actions

## Python

### Установка зависимостей

> [!note]
> - Использование `python -m` -- страховка от нескольких версий на одной машине
> - Все зависимости -- внутри [pyproject.toml](../pyproject.toml)

Из корня проекта:
```bash
python -m pip install -e ".[dev]"
```
Непонятные флаги:
- `-e` -- editable-режим: вместо копии кода в site-packages pip оставляет ссылку на исходники, поэтому инструменты видят правки без переустановки
- `.` -- источником берётся текущая папка: pip читает её [pyproject.toml](../pyproject.toml) и делает модуль `src` импортируемым из этого окружения
- `[dev]` -- дополнительная группа зависимостей из `[project.optional-dependencies]`: pytest, pyright и ruff

Отдельного файла зависимостей (по типу `requirements.txt`) у проекта нет. `pip` сам читает [pyproject.toml проекта](../pyproject.toml) и осуществляет сборку; подробности -- в [документации pip](https://pip.pypa.io/en/stable/reference/build-system/) и [документации по pyproject.toml](https://packaging.python.org/en/latest/guides/writing-pyproject-toml/).

### Python 3.14

Проект требует Python 3.14.

> Причина -- [PEP 649](https://peps.python.org/pep-0649/). PEP (Python Enhancement Proposal) -- официальный процесс предложений по развитию Python: каждый PEP описывает одно изменение языка или инфраструктуры. PEP 649 предлагает вычислять аннотации отложенно, и с Python 3.14 это поведение стало стандартным: выражения в аннотациях не вычисляются при объявлении класса или функции, а вычисляются только тогда, когда их кто-то запросил. В 3.13 и старше аннотации вычислялись сразу, поэтому ссылка на класс, объявленный ниже по файлу, роняла импорт с `NameError`.

### pytest

Запуск:
```bash
python -m pytest
```

Тесты лежат в [tests/](../tests/):
- [tests/frontend/](../tests/frontend/): лексер, парсер, семантика и golden-тесты AST
- [tests/backend/](../tests/backend/): кодоген и кодирование ISA

> Файлы из [examples/](../examples/) используются одновременно и как примеры, и как входы golden-тестов.

### pyright

За типы отвечает pyright в режиме `strict`.

***Почему pyright?***
- [mypy](https://mypy-lang.org/) -- с его режимом `--strict` проверок довольно мало
- [basedpyright](https://docs.basedpyright.com/) -- форк `pyright`, строже всех; но его режим `recommended` запрещает сам `Any` (а он нужен для [src/translator/runtime_helpers.py](../src/translator/runtime_helpers.py), который работает с [src/translator/codegen.py](../src/translator/codegen.py)), а в режиме `standard` он практически не отличается от `pyright`
- [ty](https://docs.astral.sh/ty/) (авторы ruff) / [pyrefly](https://pyrefly.org) (Meta) -- невероятно быстрые, но слишком "молоды" + слабые проверки
- [pyright](https://microsoft.github.io/pyright/) -- 81 правило вида `report*`, все перечислены в [документации конфигурации](https://microsoft.github.io/pyright/#/configuration), `strict` включает почти все сразу. Среди них есть проверки, которых у mypy нет вовсе: `reportPrivateUsage` запрещает лезть в приватные поля чужих классов, `reportUnnecessaryIsInstance` ловит `isinstance` по типу, который и так известен:
  ```python
  class Codegen:
      def __init__(self) -> None:
          self._labels: list[str] = []

  cg = Codegen()
  print(cg._labels)
  ```

  `mypy --strict` отвечает:
  ```bash
  Success: no issues found in 1 source file
  ```
  `pyright` в том же режиме выдаёт:
  ```bash
  error: "_labels" is protected and used outside of the class in which it is declared (reportPrivateUsage)
  ```
  При этом строгость у `pyright` в меру: как уже было сказано выше, в коде есть применение `Any`. Этот тип он не запрещает -- там, где тип честно неизвестен, значение помечается `Any` руками, и проверка продолжается.

### ruff

Линтер, статический анализатор исходников. Настройки -- в [pyproject.toml](../pyproject.toml).

Запуск:
```bash
python -m ruff check .
python -m ruff check . --fix
```

Набор правил -- `select = ["E", "F", "I", "UP", "B", "W"]`. Каждая буква -- префикс группы правил, унаследованной от классического линтера, который ruff переписал с нуля:

| Префикс | Откуда | Что ловит |
| --- | --- | --- |
| E | [pycodestyle](https://pycodestyle.pycqa.org/) | стиль по PEP 8 |
| W | [pycodestyle](https://pycodestyle.pycqa.org/) | стилевые предупреждения: пробелы в конце строк, лишние пустые строки |
| F | [pyflakes](https://pyflakes.pycqa.org/) | вероятные баги |
| I | [isort](https://pycqa.github.io/isort/) | порядок импортов |
| UP | [pyupgrade](https://github.com/asottile/pyupgrade) | устаревший синтаксис |
| B | [flake8-bugbear](https://github.com/PyCQA/flake8-bugbear) | частые грабли |

Это типовой стартовый набор: F и B ловят баги, E и W держат базовый стиль, I делает импорты одинаковыми, UP тянет синтаксис к целевой версии Python. Недопустимые escape-последовательности в строках ловит сам Python с `SyntaxWarning`, поэтому отдельная группа для них не нужна. Дефолтный набор ruff ещё скромнее -- только E4, E7, E9 и F; расширить наш список -- одна строка в конфиге. Полный каталог правил -- [docs.astral.sh/ruff/rules](https://docs.astral.sh/ruff/rules/).

## Не Python

### .editorconfig

[.editorconfig](../.editorconfig) задаёт базовые соглашения редактора для всех файлов: UTF-8, перевод строки в конце файла, без пробелов в конце строк, в коде отступ в 4 пробела. CI проверяет его отдельным workflow [editorconfig.yml](../.github/workflows/editorconfig.yml).

### GitHub Actions

Workflow [python.yml](../.github/workflows/python.yml) на каждый push и PR ставит Python 3.14 и по порядку запускает три проверки: `ruff check .`, `pytest -q`, `pyright`. Упавшая проверка краснит коммит.
