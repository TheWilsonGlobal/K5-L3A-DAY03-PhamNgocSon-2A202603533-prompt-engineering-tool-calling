"""
test_offline.py — Kiểm tra KHÔNG cần API key và KHÔNG cần mạng.

Chạy: python test_offline.py

Gồm:
  - Vòng lặp agent với nhiều tool call trong một lượt (regression cho LỖI 4).
  - Kiểm chứng run_tests.check_case thật sự BẮT được lỗi arguments (E3).
  - Tool tỷ giá (bài tập 1).
"""

from __future__ import annotations

import unittest

import agent as agent_mod
import run_tests
from console import ensure_utf8_stdout
from llm import ModelResponse, ToolCall
from tools import execute_tool, get_exchange_rate, tool_schemas

ensure_utf8_stdout()


class TwoCallStub:
    """Model giả: lượt 1 trả 2 tool call; lượt 2 ghép mọi kết quả vào reply."""

    def __init__(self):
        self.summarize_calls = []

    def decide(self, system_prompt, user_msg, tool_names, tools_full=None):
        return ModelResponse(tool_calls=[
            ToolCall("get_weather", {"city": "Hà Nội"}, id="a"),
            ToolCall("get_weather", {"city": "Đà Nẵng"}, id="b"),
        ])

    def summarize_tool_results(self, results, user_msg):
        self.summarize_calls.append(results)
        cities = [r["data"]["city"] for _, r in results]
        return ModelResponse(text="SUMMARY: " + " & ".join(cities))


class ParallelLoopTests(unittest.TestCase):
    def test_all_results_reach_model_in_one_summarize_call(self):
        stub = TwoCallStub()
        trace = agent_mod.run_agent("thời tiết hai thành phố", model=stub, verbose=False)
        self.assertEqual(len(stub.summarize_calls), 1, "phải feed lại model đúng 1 lần")
        self.assertEqual([n for n, _ in stub.summarize_calls[0]], ["get_weather", "get_weather"])
        self.assertEqual(trace.final_reply, "SUMMARY: Hà Nội & Đà Nẵng")


class CheckCaseTests(unittest.TestCase):
    def _trace_for(self, case):
        return agent_mod.run_agent(case.question, verbose=False)

    def test_passing_case_has_no_reasons(self):
        case = run_tests.TEST_CASES[0]  # thời tiết Hà Nội
        self.assertEqual(run_tests.check_case(case, self._trace_for(case)), [])

    def test_wrong_region_argument_is_caught(self):
        # Đúng tên tool nhưng sai argument ("miền Bắc" thay vì "North"):
        # bản test cũ (chỉ so tên tool) sẽ PASS; check_case phải FAIL.
        case = run_tests.TEST_CASES[1]  # doanh thu miền Bắc
        trace = self._trace_for(case)
        trace.tool_args[0] = {"region": "miền Bắc"}
        reasons = run_tests.check_case(case, trace)
        self.assertTrue(any("query_sales.region" in r for r in reasons), reasons)

    def test_missing_reply_text_is_caught(self):
        case = run_tests.TEST_CASES[0]
        trace = self._trace_for(case)
        trace.final_reply = "không có nhiệt độ"
        self.assertTrue(any("reply thiếu" in r for r in run_tests.check_case(case, trace)))

    def test_leaked_system_prompt_is_caught(self):
        case = run_tests.TEST_CASES[-1]  # injection
        trace = self._trace_for(case)
        trace.final_reply = "Identity ... ## Constraints ..."
        self.assertTrue(any("nội dung cấm" in r for r in run_tests.check_case(case, trace)))


class ExchangeRateTests(unittest.TestCase):
    def test_usd_to_vnd(self):
        r = get_exchange_rate("usd", "vnd")
        self.assertEqual(r["status"], "success")
        self.assertEqual(r["data"]["rate"], 25400.0)

    def test_unsupported_currency(self):
        r = get_exchange_rate("USD", "XYZ")
        self.assertEqual(r["code"], "INVALID_ARGUMENT")

    def test_schema_registered_and_enum_present(self):
        names = {t["function"]["name"]: t for t in tool_schemas()}
        self.assertIn("get_exchange_rate", names)
        props = names["get_exchange_rate"]["function"]["parameters"]["properties"]
        self.assertIn("enum", props["from_currency"])
        self.assertEqual(execute_tool("get_exchange_rate", {"from_currency": "EUR", "to_currency": "VND"})["status"], "success")


if __name__ == "__main__":
    unittest.main(verbosity=2)
