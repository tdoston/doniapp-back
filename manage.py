#!/usr/bin/env python3
import os
import sys


def main() -> None:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "swiftbookings.settings")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Django topilmadi. `pip install -r requirements.txt` ni django_backend papkasida bajaring."
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
