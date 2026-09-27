#!/usr/bin/env python3
"""
Синтаксическая проверка миграций настоящим парсером PostgreSQL.

    pip install pglast
    python3 supabase/check_migrations.py

Зачем это нужно. Миграции применяются руками в Supabase Studio, по одной,
в порядке номеров. Опечатка в двухсотой строке обнаруживается только
тогда, когда до неё дойдёт выполнение, — а к этому моменту половина
файла уже применилась. Дальше надо руками разбираться, что успело
создаться, а что нет.

`pglast` содержит настоящий парсер PostgreSQL, тот же, что в самой базе.
Проверяются обе грамматики:

  * SQL — команды целиком;
  * PL/pgSQL — тела функций внутри $$…$$. Без второй проверки тело
    функции остаётся для парсера обычной строкой, и `end if`, забытый в
    середине, проходит незамеченным.

ЧЕГО ЭТА ПРОВЕРКА НЕ ЛОВИТ. Только синтаксис. Несуществующая колонка,
неверный тип, ошибка в политике доступа, неоднозначная ссылка на имя —
всё это синтаксически безупречно. Проверка говорит «база это прочтёт»,
а не «это работает правильно».
"""

from __future__ import annotations

import sys
from pathlib import Path

try:
    from pglast.parser import parse_plpgsql_json, parse_sql
except ImportError:
    print("Нет модуля pglast. Установите:  pip install pglast")
    raise SystemExit(2)

MIGRATIONS = Path(__file__).resolve().parent / "migrations"


def main() -> int:
    files = sorted(MIGRATIONS.glob("*.sql"))
    if not files:
        print(f"В {MIGRATIONS} нет ни одного .sql")
        return 2

    problems: list[str] = []

    for path in files:
        sql = path.read_text(encoding="utf-8")

        try:
            parse_sql(sql)
        except Exception as exc:
            problems.append(f"{path.name}: {exc}")
            # Дальше не идём: тела функций разбирать в файле, который и
            # так не читается, бессмысленно
            continue

        try:
            parse_plpgsql_json(sql)
        except Exception as exc:
            problems.append(f"{path.name}: в теле функции — {exc}")

    if problems:
        print(f"Ошибок: {len(problems)}\n")
        for line in problems:
            print(f"  ✗ {line}")
        return 1

    print(f"✓ {len(files)} миграций читаются без ошибок")
    print("  Проверен только синтаксис: имена колонок и политики доступа "
          "проверяются лишь применением к настоящей базе.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
