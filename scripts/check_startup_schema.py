"""Rehearse experimental migration on a memory snapshot; never migrate the source."""
import argparse
import json
import sys

from storage.startup_rehearsal import RehearsalError, rehearse


def main():
    parser = argparse.ArgumentParser(description='Пробная миграция в памяти; исходная база не изменяется.')
    parser.add_argument('database', help='Путь к доверенной локальной базе SQLite')
    parser.add_argument('--guard-source', action='store_true', help='Удержать имя файла базы (только Windows NTFS)')
    args = parser.parse_args()
    try:
        result = rehearse(args.database, guard_source=args.guard_source)
    except RehearsalError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
