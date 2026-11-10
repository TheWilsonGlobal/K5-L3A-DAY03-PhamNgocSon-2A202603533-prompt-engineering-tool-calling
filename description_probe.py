"""
description_probe.py — Bài tập mở rộng 2: làm hỏng tool description rồi quan sát.

So sánh hai biến thể của description `get_weather`:
  - ORIGINAL: có phần "KHÔNG dùng cho câu hỏi chung chung, dự báo nhiều ngày, ...".
  - BROKEN:   bỏ phần "KHÔNG dùng ..." (đúng yêu cầu bài tập).

Biến thể BROKEN được áp dụng TRONG BỘ NHỚ (monkeypatch) rồi khôi phục; file tools.py
không bị sửa. Mỗi probe chạy RUNS lần cho mỗi biến thể; ghi có/không gọi get_weather
và city được truyền vào.

Chỉ có ý nghĩa với model thật (MockModel không đọc description):
    LAB_MODEL=gemini GEMINI_API_KEY=... python description_probe.py
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import time
from collections import defaultdict
from pathlib import Path

import tools
from agent import run_agent
from console import ensure_utf8_stdout
from llm import get_model
from system_prompt import SYSTEM_PROMPT

ensure_utf8_stdout()

RESULTS_DIR = Path(__file__).parent / "results"

# Probe: câu hỏi mà phần "KHÔNG dùng" của description ĐÁNG LẼ phải chặn.
# expect_call = hành vi đúng theo description ORIGINAL.
PROBES = [
    ("P1 dự báo nhiều ngày",  "Dự báo thời tiết Đà Nẵng cả tuần tới thế nào?", False),
    ("P2 thiếu thành phố",     "Thời tiết thế nào nhỉ?", False),
    ("P3 chung chung",         "Hôm nay trời có đẹp để đi chơi không?", False),
    ("P4 đủ thông tin",        "Hà Nội hôm nay có nên mang ô không?", True),
]


def make_variants() -> dict[str, str]:
    original = tools.GET_WEATHER_SCHEMA["function"]["description"]
    if " KHÔNG dùng" not in original:
        sys.exit("Không tìm thấy cụm ' KHÔNG dùng' trong description gốc — kiểm tra tools.py.")
    broken = original.split(" KHÔNG dùng")[0]
    assert broken != original
    return {"ORIGINAL": original, "BROKEN": broken}


def run_probes(runs: int, sleep_s: float) -> list[dict]:
    model = get_model()
    variants = make_variants()
    schema = tools.GET_WEATHER_SCHEMA["function"]
    saved = schema["description"]
    rows = []
    try:
        for vname, desc in variants.items():
            schema["description"] = desc          # áp dụng biến thể trong bộ nhớ
            for label, question, expect_call in PROBES:
                for run_no in range(1, runs + 1):
                    try:
                        trace = run_agent(question, model=model, system_prompt=SYSTEM_PROMPT, verbose=False)
                        cities = [a.get("city") for n, a in zip(trace.tool_calls, trace.tool_args)
                                  if n == "get_weather"]
                        err = None
                    except Exception as e:
                        cities, err = [], f"{type(e).__name__}: {e}"
                    rows.append({
                        "variant": vname, "probe": label, "question": question,
                        "expect_call": expect_call, "run": run_no,
                        "called": bool(cities), "cities": cities, "error": err,
                    })
                    print(f"[{vname}] {label} run {run_no}: "
                          f"{'GỌI ' + str(cities) if cities else 'không gọi'}"
                          f"{' (lỗi)' if err else ''}", flush=True)
                    if sleep_s:
                        time.sleep(sleep_s)
    finally:
        schema["description"] = saved             # khôi phục dù có lỗi
    return rows


def summarise(rows: list[dict]) -> dict:
    table = defaultdict(lambda: {"calls": 0, "runs": 0, "matches_expect": 0})
    for r in rows:
        key = (r["probe"], r["variant"])
        table[key]["runs"] += 1
        table[key]["calls"] += int(r["called"])
        table[key]["matches_expect"] += int(r["called"] == r["expect_call"])
    return {f"{p} | {v}": dict(d) for (p, v), d in table.items()}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--sleep", type=float, default=None,
                    help="giây nghỉ giữa các lượt (mặc định 13 với gemini, 0 với mock)")
    args = ap.parse_args()
    label = os.environ.get("LAB_MODEL", "mock").lower()
    sleep_s = args.sleep if args.sleep is not None else (13.0 if label == "gemini" else 0.0)

    rows = run_probes(args.runs, sleep_s)
    summary = summarise(rows)

    print(f"\n{'='*70}\nMODEL: {label}\n")
    for key, d in summary.items():
        print(f"  {key:50s} gọi {d['calls']}/{d['runs']}   đúng kỳ vọng {d['matches_expect']}/{d['runs']}")

    RESULTS_DIR.mkdir(exist_ok=True)
    date = dt.date.today().isoformat()
    out = RESULTS_DIR / f"description-probe-{label}-{date}.json"
    out.write_text(json.dumps({
        "model_label": label, "model": os.environ.get("GEMINI_MODEL") if label == "gemini" else label,
        "is_real_model": label != "mock", "date": date, "runs": args.runs,
        "summary": summary, "rows": rows,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nĐã lưu: {out}")


if __name__ == "__main__":
    main()
