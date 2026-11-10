"""
consistency_eval.py — Bài tập mở rộng 3: đo ĐỘ ỔN ĐỊNH của agent qua nhiều lần chạy.

Mỗi case trong run_tests.TEST_CASES được chạy N lần. Ghi tỷ lệ PASS từng case và
tổng; kết quả thô lưu vào results/consistency-<model>-<ngày>.json để có bằng chứng.

Ngưỡng (SELF_REVIEW.md): dưới 90% thì cần lặp lại prompt/schema.

Cách chạy:
    python consistency_eval.py                       # mock, 10 lượt — kiểm tra harness
    LAB_MODEL=gemini GEMINI_API_KEY=... python consistency_eval.py --runs 10 --sleep 13

Lưu ý:
  - MockModel là tất định, nên kết quả mock luôn 100%. Kết quả đó chỉ chứng minh
    harness chạy đúng, KHÔNG phải độ ổn định của model thật (file ghi nhãn "mock").
  - Free tier Gemini: 5 RPM -> --sleep >= 13 giây giữa các lượt gọi.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import time
from pathlib import Path

from agent import run_agent
from console import ensure_utf8_stdout
from llm import get_model
from run_tests import TEST_CASES, check_case
from system_prompt import SYSTEM_PROMPT

ensure_utf8_stdout()

PASS_THRESHOLD = 0.90
RESULTS_DIR = Path(__file__).parent / "results"


def _label() -> str:
    return os.environ.get("LAB_MODEL", "mock").lower()


def _model_name(label: str) -> str:
    if label == "gemini":
        return os.environ.get("GEMINI_MODEL", "gemini-3-flash-preview")
    return label


def _precheck(label: str) -> None:
    """Dừng sớm với thông báo rõ ràng (in ra stdout để giữ UTF-8 trên Windows)."""
    missing = None
    if label == "gemini" and not os.environ.get("GEMINI_API_KEY"):
        missing = "GEMINI_API_KEY"
    if missing:
        print(f"Thiếu {missing}. Đặt biến môi trường rồi chạy lại "
              f"(hoặc bỏ LAB_MODEL để chạy mock).")
        sys.exit(2)


def evaluate(runs: int, sleep_s: float) -> dict:
    label = _label()
    _precheck(label)
    model = get_model(label)

    total_calls = runs * len(TEST_CASES)
    done = 0
    cases_out = []
    for idx, case in enumerate(TEST_CASES, 1):
        passes = 0
        failures: list[dict] = []
        for run_no in range(1, runs + 1):
            try:
                trace = run_agent(case.question, model=model, system_prompt=SYSTEM_PROMPT, verbose=False)
                reasons = check_case(case, trace)
                reply = trace.final_reply
            except Exception as e:  # lỗi mạng/API cũng là một lần FAIL, không dừng cả bài đo
                reasons = [f"exception: {type(e).__name__}: {e}"]
                reply = ""
            if reasons:
                failures.append({"run": run_no, "reasons": reasons, "reply": reply[:300]})
            else:
                passes += 1

            done += 1
            print(f"[{done}/{total_calls}] case {idx} run {run_no}: "
                  f"{'PASS' if not reasons else 'FAIL'}", flush=True)
            if sleep_s and done < total_calls:
                time.sleep(sleep_s)

        rate = passes / runs
        cases_out.append({
            "case": idx,
            "question": case.question,
            "note": case.note,
            "runs": runs,
            "passes": passes,
            "pass_rate": round(rate, 4),
            "meets_threshold": rate >= PASS_THRESHOLD,
            "failures": failures,
        })

    total_passes = sum(c["passes"] for c in cases_out)
    overall = total_passes / total_calls
    return {
        "model_label": label,
        "model": _model_name(label),
        "is_real_model": label not in ("mock",),
        "date": dt.date.today().isoformat(),
        "runs_per_case": runs,
        "sleep_seconds": sleep_s,
        "threshold": PASS_THRESHOLD,
        "overall_pass_rate": round(overall, 4),
        "overall_meets_threshold": overall >= PASS_THRESHOLD,
        "cases": cases_out,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--runs", type=int, default=10, help="số lượt cho mỗi case (mặc định 10)")
    ap.add_argument("--sleep", type=float, default=None,
                    help="giây nghỉ giữa các lượt gọi (mặc định: 13 với gemini, 0 với mock)")
    args = ap.parse_args()

    label = _label()
    sleep_s = args.sleep if args.sleep is not None else (13.0 if label == "gemini" else 0.0)
    report = evaluate(args.runs, sleep_s)

    RESULTS_DIR.mkdir(exist_ok=True)
    out = RESULTS_DIR / f"consistency-{label}-{report['date']}.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n{'='*70}")
    print(f"MODEL: {report['model']}  ({'MODEL THẬT' if report['is_real_model'] else 'MOCK — chỉ kiểm harness'})")
    for c in report["cases"]:
        flag = "OK " if c["meets_threshold"] else "DƯỚI NGƯỠNG"
        print(f"  case {c['case']}: {c['passes']}/{c['runs']} = {c['pass_rate']:.0%}  [{flag}]")
    print(f"TỔNG: {report['overall_pass_rate']:.0%} "
          f"({'đạt' if report['overall_meets_threshold'] else 'KHÔNG đạt'} ngưỡng {PASS_THRESHOLD:.0%})")
    print(f"Đã lưu: {out}")


if __name__ == "__main__":
    main()
