# PuginScript

* **Автор**: Пугин Сергей Евгеньевич
* **Группа**: `P3219`
* **Вариант**: `alg | risc | harv | mc | stream | port | cstr | pipeline | alg3`


## Оглавление
1. [Описание языка](#описание-языка)
2. [Синтаксис (EBNF)](#синтаксис-ebnf)
3. [RISC ISA](#risc-isa)
4. [Микропрограммное управление](#микропрограммное-управление)
5. [Транслятор](#транслятор)
6. [Модель процессора](#модель-процессора)
7. [Тестирование](#тестирование)

## Описание языка

PuginScript -- императивный, строго типизированный, компилируемый язык программирования.

Язык представляет собой гибрид концепций, заимствованных из классических и современных языков:
- **C:** использование фигурных скобок `{}` для блоков кода, обязательных символов `;`, семантика передачи аргументов по значению, реализация строк как null-terminated последовательностей байт и соглашение об использовании `snake_case`
- **Python:** функция `input()`, использование ключевого слова `def` для объявления функций и модель исполнения кода верхнего уровня без необходимости функции `main`. Отсюда же заимствован оператор возведения в степень `**`
- **Java:** имена и семантика функций вывода `print` и `println`, а также ссылочная семантика для массивов (передача в функции по ссылке, создание через `new`)
- **TypeScript:** строгая статическая типизация данных и синтаксис объявления переменных

### Ключевые особенности
- **Типы данных:**
  - `int` -- 32-битное знаковое целое
  - `bool` -- логическое значение
  - `str` -- указатель на null-terminated строку в памяти
- **Ветвления:** `if / else`
- **циклы:** единственный тип цикла -- `while`. Отсутствие `for`, `break`, `continue` и `goto` упрощает транслятор и гарантирует соблюдение принципа *SESE -- Single Entry, Single Exit*, что делает логику программы предсказуемее и легче для анализа
- **Функции:** объявление через ключевое слово `def`, поддержка рекурсивных вызовов
- **Ввод-вывод:** PMIO (Port Mapped I/O) и встроенные функции `input()`, `input_int()`, `input_char()`, `print()`, `println()`, `print_char()`, `len()`

### Модель исполнения и точка входа

PuginScript поддерживает гибкую модель исполнения (top-level и функция `main`):

- **при наличии функции `main`**: транслятор автоматически делает её точкой входа. Программа начинает выполнение с вызова `main()`, а значение, возвращаемое из `main()` становится **кодом завершения программы** (`exit code`)
- **при отсутствии `main`**: программа исполняется как скрипт сверху вниз с первой инструкции верхнего уровня (по адресу `0` в памяти команд)
- `return` на верхнем уровне завершает программу с переданным значением (или с кодом 0 по умолчанию)

### Ввод-вывод

Обмен с внешним миром идёт через PMIO (Port Mapped I/O): ввод -- чтение из порта, вывод -- запись байта в порт. Встроенные функции: `print(x)` и `println(x)` -- вывод без и с переводом строки (семантика из Java), `print_char(int)` -- вывод одного байта, `input()`, `input_int()`, `input_char()` -- ввод строки, числа и символа. Полная семантика, включая поведение при EOF, -- в [docs/README.md](docs/README.md#ввод-вывод)

### Препроцессор и импорты

Для модульной организации кода используется директива импорта:

```python
import "relative/path/to/file.ps";
```

- **механизм работы**: препроцессор считывает указанный файл по относительному пути и вставляет его текст на место директивы `import` до начала лексического анализа
- **защита от повторного включения**: препроцессор отслеживает импортированные пути, исключая дублирование кода и циклические зависимости
- **пространство имён**: все импортированные файлы попадают в единое глобальное пространство имён. Повторное объявление одинаковых имён (включая две функции `main`) является ошибкой компиляции

## Синтаксис (EBNF)

```javascript
program = { import_stmt | statement | function_decl } ;

import_stmt = "import" string_literal ";" ;

function_decl = "def" identifier "(" [ param_list ] ")" [ "->" type ] block ;
param_list = param { "," param } ;
param = type identifier ;

block = "{" { statement } "}" ;

statement = var_decl ";"
          | assignment ";"
          | if_stmt
          | while_stmt
          | return_stmt ";"
          | expression ";"
          | block ;

var_decl = type identifier [ "=" expression ] ;
assignment = lvalue ( "=" | "+=" | "-=" | "*=" | "/=" | "%=" ) expression ;
lvalue = identifier [ "[" expression "]" ] ;

if_stmt = "if" "(" expression ")" block [ "else" ( if_stmt | block ) ] ;
while_stmt = "while" "(" expression ")" block ;
return_stmt = "return" [ expression ] ;

expression = logical_or ;
logical_or = logical_and { "|" logical_and } ;
logical_and = comparison { "&" comparison } ;
comparison = term [ ( "==" | "!=" | "<" | "<=" | ">" | ">=" ) term ] ;
term = factor { ( "+" | "-" ) factor } ;
factor = unary { ( "*" | "/" | "%" ) unary } ;
unary = ( "!" | "-" ) unary | power ;
power = primary [ "**" power ] ;

primary = identifier "(" [ arg_list ] ")"
        | identifier "[" expression "]"
        | "new" base_type "[" expression "]"
        | identifier
        | integer_literal
        | string_literal
        | char_literal
        | "true" | "false"
        | "(" expression ")" ;

arg_list = expression { "," expression } ;
type = base_type [ "[]" ] ;
base_type = "int" | "str" | "bool" ;

identifier = ( letter | "_" ) { letter | digit | "_" } ;
integer_literal = digit { digit | "_" digit } ;
string_literal = '"' { printable_char | escape_sequence } '"' ;
char_literal = "'" ( printable_char | escape_sequence ) "'" ;
escape_sequence = "\\" ( "n" | "r" | "t" | "0" | "\\" | "'" | '"' ) ;

comment = line_comment | block_comment ;
line_comment = "//" { printable_char } ;
block_comment = "/*" { any_char } "*/" ;
```
> [!note]
> - **letter** -- латинские a-z и A-Z
> - **digit** -- цифры 0-9
> - **printable_char** -- любой печатный ASCII кроме служебного '\\' и перевода строки
> - **any_char** -- любой символ, включая перевод строки
> - **comment** -- `//` до конца строки или `/* ... */`, вырезается лексером и не участвует в разборе

> [!note]
> Если тип возвращаемого значения `-> type` в объявлении функции опущен, функция считается процедурой (не возвращает значения)

## RISC ISA



## Микропрограммное управление



## Транслятор



## Модель процессора



## Тестирование
