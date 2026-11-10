"""
console.py — Đảm bảo stdout dùng UTF-8.

Trên Windows, console mặc định dùng cp1252 nên in tiếng Việt sẽ crash với
UnicodeEncodeError. Các module có in tiếng Việt gọi ensure_utf8_stdout() một lần
khi import để chạy được mà không cần đặt PYTHONUTF8=1.
"""

import sys


def ensure_utf8_stdout() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except (OSError, ValueError):
            pass  # stdout không reconfigure được (vd bị redirect) -> bỏ qua
