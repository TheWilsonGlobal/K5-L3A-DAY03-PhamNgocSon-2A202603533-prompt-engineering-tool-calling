"""
llm.py — Lớp model có thể thay thế (pluggable), chuẩn hoá về một interface chung.

Slide "Tool Calling Flow": LLM decides -> tool_call JSON -> App executes -> tool
result -> LLM final response. File này lo phần "LLM decides" và "LLM final".

Mặc định dùng MockModel: một model GIẢ LẬP có luật quyết định (rule-based router)
để lab CHẠY ĐƯỢC ngay, offline, kết quả tất định (dễ demo, dễ chấm). Ai có API key
có thể chuyển sang model thật (Gemini) — vòng lặp agent không đổi.

Chuẩn hoá: mọi model trả về ModelResponse gồm:
  - text: câu trả lời trực tiếp (khi KHÔNG gọi tool), hoặc None
  - tool_calls: danh sách ToolCall(name, arguments, id), rỗng nếu trả lời trực tiếp
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field

from console import ensure_utf8_stdout

ensure_utf8_stdout()


@dataclass
class ToolCall:
    name: str
    arguments: dict
    id: str = "call_1"


@dataclass
class ModelResponse:
    text: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)

    @property
    def wants_tool(self) -> bool:
        return len(self.tool_calls) > 0


# ---------------------------------------------------------------------------
# MOCK MODEL — router tất định, dùng để dạy vòng lặp tool calling offline.
# ---------------------------------------------------------------------------
class MockModel:
    """Mô phỏng 'khi nào model gọi tool, khi nào trả lời trực tiếp'.

    Đây KHÔNG phải LLM thật; nó là bộ luật đơn giản để minh hoạ 3 pattern
    (slide "3 Tool Use Patterns"): conditional / direct / refusal. Quyết định
    dựa trên từ khoá trong câu hỏi + policy trong system prompt.
    """

    def __init__(self, honor_out_of_scope: bool | None = None):
        # None (mặc định): model SUY RA policy từ system prompt (prompt tốt -> có
        #   ràng buộc tài chính -> từ chối; prompt kém -> không có -> bịa best-guess).
        #   Đây là cách demo LỖI PROMPT: cùng model, đổi prompt -> đổi hành vi.
        # True/False: ép cứng, dùng khi cần cô lập biến trong test.
        self.honor_out_of_scope = honor_out_of_scope

    def _honors_scope(self, system_prompt: str) -> bool:
        if self.honor_out_of_scope is not None:
            return self.honor_out_of_scope
        sp = system_prompt.lower()
        return "tài chính" in sp or "đầu tư" in sp or "ngoài phạm vi" in sp

    _WEATHER_KW = ("thời tiết", "thoi tiet", "nhiệt độ", "nhiet do", "mưa", "nắng", "trời")
    _SALES_KW = ("doanh thu", "doanh số", "doanh so", "bán được", "revenue", "doanh_thu", "bán hàng")
    _FX_KW = ("tỷ giá", "ty gia", "đổi tiền", "doi tien", "usd", "eur", "jpy", "vnd")
    _FX_CODE_RE = re.compile(r"\b(usd|eur|jpy|vnd)\b", re.IGNORECASE)
    _FINANCE_KW = ("bitcoin", "cổ phiếu", "co phieu", "crypto", "đầu tư", "chứng khoán", "giá vàng")
    _CITIES = {
        "hà nội": "Hà Nội", "ha noi": "Hà Nội", "hanoi": "Hà Nội",
        "đà nẵng": "Đà Nẵng", "da nang": "Đà Nẵng", "danang": "Đà Nẵng",
        "huế": "Huế", "hue": "Huế",
        "hồ chí minh": "Hồ Chí Minh", "sài gòn": "Sài Gòn", "hcm": "Hồ Chí Minh",
    }
    _REGIONS = {"bắc": "North", "bac": "North", "miền bắc": "North",
                "nam": "South", "miền nam": "South",
                "trung": "Central", "miền trung": "Central"}

    def decide(self, system_prompt: str, user_msg: str, tool_names: list[str],
               tools_full: list[dict] | None = None) -> ModelResponse:
        # tools_full: MockModel không cần schema đầy đủ (nó route bằng từ khoá);
        # tham số này chỉ để signature khớp với model thật (Gemini).
        text = user_msg.lower()

        # (1) Ngoài phạm vi: tài chính/đầu tư.
        if any(k in text for k in self._FINANCE_KW):
            if self._honors_scope(system_prompt):
                # Prompt tốt (có Constraints) -> từ chối trực tiếp.
                return ModelResponse(text=json.dumps({
                    "intent": "hỏi lời khuyên tài chính (ngoài phạm vi)",
                    "action": "direct",
                    "reply": "Xin lỗi, mình chỉ hỗ trợ tra cứu thời tiết và dữ liệu bán "
                             "hàng, không đưa lời khuyên đầu tư/tài chính.",
                }, ensure_ascii=False))
            # Prompt kém (ép 'make your best guess') -> BỊA câu trả lời nguy hiểm.
            return ModelResponse(text=json.dumps({
                "intent": "hỏi lời khuyên tài chính",
                "action": "direct",
                "reply": "Theo dự đoán của mình, giá bitcoin ngày mai có thể tăng ~5%. "
                         "(⚠ bịa — model không có dữ liệu này)",
            }, ensure_ascii=False))

        # (2a) Hai ý định trong MỘT câu (thời tiết + tỷ giá) -> NHIỀU tool call trong
        # một lượt. Dùng để thử pattern parallel fetch + merge (bài tập mở rộng 1).
        city_2a = self._extract_city(text)
        fx_args = self._fx_args(text)
        if (city_2a and fx_args and "get_weather" in tool_names
                and "get_exchange_rate" in tool_names
                and any(k in text for k in self._WEATHER_KW)):
            return ModelResponse(tool_calls=[
                ToolCall("get_weather", {"city": city_2a}, id="call_1"),
                ToolCall("get_exchange_rate", fx_args, id="call_2"),
            ])

        # (2) Ý định thời tiết.
        if any(k in text for k in self._WEATHER_KW) and "get_weather" in tool_names:
            city = self._extract_city(text)
            if city is None:
                # Thiếu required field -> KHÔNG gọi tool, hỏi lại (Rules).
                return ModelResponse(text=json.dumps({
                    "intent": "hỏi thời tiết nhưng thiếu thành phố",
                    "action": "direct",
                    "reply": "Bạn muốn xem thời tiết ở thành phố nào ạ?",
                }, ensure_ascii=False))
            return ModelResponse(tool_calls=[ToolCall("get_weather", {"city": city})])

        # (3) Ý định doanh thu.
        if any(k in text for k in self._SALES_KW) and "query_sales" in tool_names:
            region = self._extract_region(text)
            if region is None:
                return ModelResponse(text=json.dumps({
                    "intent": "hỏi doanh thu nhưng thiếu khu vực",
                    "action": "direct",
                    "reply": "Bạn muốn xem doanh thu khu vực nào: North, South hay Central?",
                }, ensure_ascii=False))
            return ModelResponse(tool_calls=[ToolCall("query_sales", {"region": region})])

        # (3b) Ý định tỷ giá.
        if any(k in text for k in self._FX_KW) and "get_exchange_rate" in tool_names:
            fx_args = self._fx_args(text)
            if fx_args is None:
                return ModelResponse(text=json.dumps({
                    "intent": "hỏi tỷ giá nhưng thiếu loại tiền",
                    "action": "direct",
                    "reply": "Bạn muốn đổi từ loại tiền nào sang loại tiền nào (USD, EUR, JPY, VND)?",
                }, ensure_ascii=False))
            return ModelResponse(tool_calls=[ToolCall("get_exchange_rate", fx_args)])

        # (4) Chào hỏi / hỏi bạn là ai -> trả lời trực tiếp, không tool.
        if any(k in text for k in ("xin chào", "chào", "bạn là ai", "hello", "hi ")):
            return ModelResponse(text=json.dumps({
                "intent": "chào hỏi / hỏi danh tính",
                "action": "direct",
                "reply": "Chào bạn! Mình là trợ lý tra cứu thời tiết và dữ liệu bán hàng nội bộ.",
            }, ensure_ascii=False))

        # (5) Không khớp intent nào -> trả lời trực tiếp (không bịa, không gọi tool).
        return ModelResponse(text=json.dumps({
            "intent": "không xác định",
            "action": "direct",
            "reply": "Mình chưa rõ yêu cầu. Bạn có thể hỏi về thời tiết một thành phố "
                     "hoặc doanh thu một khu vực (North/South/Central).",
        }, ensure_ascii=False))

    def summarize_tool_result(self, tool_name: str, tool_result: dict, user_msg: str) -> ModelResponse:
        """Lượt 2 của model với MỘT tool result (JSON contract)."""
        return self.summarize_tool_results([(tool_name, tool_result)], user_msg)

    def summarize_tool_results(self, results: list[tuple[str, dict]], user_msg: str) -> ModelResponse:
        """Lượt 2 của model với TẤT CẢ tool result của một lượt (JSON contract)."""
        if len(results) == 1:
            action = results[0][0]
        else:
            action = ",".join(name for name, _ in results)
        reply = " | ".join(self._reply_for(name, res) for name, res in results)
        return ModelResponse(text=json.dumps({
            "intent": user_msg, "action": action, "reply": reply,
        }, ensure_ascii=False))

    def _reply_for(self, tool_name: str, tool_result: dict) -> str:
        if tool_result.get("status") == "error":
            return f"Không lấy được dữ liệu ({tool_name}): {tool_result.get('message')}."
        if tool_name == "get_weather":
            d = tool_result["data"]
            return f"Thời tiết {d['city']}: {d['temp_c']}°C, {d['condition']}."
        if tool_name == "query_sales":
            d = tool_result["data"]
            return (f"Doanh thu khu vực {d['region']} ({d['product']}, {d['month']}): "
                    f"{d['total_revenue_usd']:,} USD, {d['total_units']:,} sản phẩm.")
        if tool_name == "get_exchange_rate":
            d = tool_result["data"]
            rate = f"{d['rate']:,.4f}".rstrip("0").rstrip(".")
            return f"Tỷ giá: 1 {d['from']} = {rate} {d['to']}."
        return "Đã có kết quả."

    def _fx_args(self, text: str) -> dict | None:
        """Trích (from, to) từ câu hỏi. 2 mã -> theo thứ tự xuất hiện; 1 mã -> đổi sang VND
        (hoặc sang USD nếu mã đó đã là VND). Không có mã nào -> None."""
        codes = [m.upper() for m in self._FX_CODE_RE.findall(text)]
        if len(codes) >= 2:
            return {"from_currency": codes[0], "to_currency": codes[1]}
        if len(codes) == 1:
            if codes[0] == "VND":
                return {"from_currency": "VND", "to_currency": "USD"}
            return {"from_currency": codes[0], "to_currency": "VND"}
        return None

    def _extract_city(self, text: str) -> str | None:
        for key, name in self._CITIES.items():
            if key in text:
                return name
        return None

    def _extract_region(self, text: str) -> str | None:
        # ưu tiên cụm dài trước ("miền bắc" trước "bắc")
        for key in sorted(self._REGIONS, key=len, reverse=True):
            if key in text:
                return self._REGIONS[key]
        return None


# ---------------------------------------------------------------------------
# REAL MODELS (tuỳ chọn) — chỉ để tham khảo; cần cài SDK + API key.
# Vòng lặp agent.py hoạt động y hệt với các model này.
# ---------------------------------------------------------------------------
def get_model(name: str | None = None):
    """Chọn model theo biến môi trường LAB_MODEL: mock | gemini."""
    name = name or os.environ.get("LAB_MODEL", "mock")
    if name == "mock":
        return MockModel()
    if name == "gemini":
        return _GeminiModel()
    raise ValueError(f"Model không hỗ trợ: {name}")


class _GeminiModel:
    """Adapter cho Google Gemini qua Gen AI SDK (cần `pip install google-genai`).

    Xác thực (tự đọc từ biến môi trường khi tạo genai.Client()):
      - Gemini Developer API (đơn giản, cho lab):  export GEMINI_API_KEY=...
      - Agent Platform (Vertex AI, cho doanh nghiệp):
            export GOOGLE_GENAI_USE_VERTEXAI=true
            export GOOGLE_CLOUD_PROJECT=... ; export GOOGLE_CLOUD_LOCATION=global

    Ghi chú tool calling của Gemini (khác OpenAI):
      - Schema tool khai báo qua types.FunctionDeclaration + types.Tool.
      - System prompt đặt ở config.system_instruction (không nằm trong messages).
      - Model trả tool call ở resp.function_calls (mỗi cái có .name và .args).
    """

    # 6 lần thử: free tier reset theo phút, mỗi lần chờ đúng retryDelay (~45–60s).
    _MAX_RETRIES = 6

    def __init__(self, model: str | None = None):
        from google import genai            # import trễ để không bắt buộc cài đặt
        from google.genai import types
        self._types = types
        self._errors = __import__("google.genai.errors", fromlist=["errors"])
        self.client = genai.Client()
        # Mặc định model preview mới nhất; nếu key chưa có quyền, đổi sang
        # 'gemini-2.5-flash' (ổn định) qua biến GEMINI_MODEL.
        self.model = model or os.environ.get("GEMINI_MODEL", "gemini-3-flash-preview")
        self._last_call = 0.0

    def _pace(self) -> None:
        """Giữ khoảng cách tối thiểu giữa hai request (mặc định 4.5s ≈ 13 RPM).

        Free tier giới hạn 15 RPM (một số model thấp hơn). Gọi liên tiếp không nghỉ
        sẽ đụng trần ngay trong một lượt test; pacing ở đây bảo vệ mọi caller.
        Chỉnh bằng GEMINI_MIN_GAP (giây), đặt 0 để tắt.
        """
        gap = float(os.environ.get("GEMINI_MIN_GAP", "4.5"))
        wait = gap - (time.monotonic() - self._last_call)
        if gap > 0 and wait > 0:
            time.sleep(wait)
        self._last_call = time.monotonic()

    def _call_with_retry(self, fn, *args, **kwargs):
        """Gọi Gemini API với pacing + auto-retry khi bị rate limit (429).

        Đọc retryDelay từ response rồi chờ đúng thời gian đó trước khi thử lại,
        tối đa _MAX_RETRIES lần.
        """
        for attempt in range(1, self._MAX_RETRIES + 1):
            self._pace()
            try:
                return fn(*args, **kwargs)
            except self._errors.ClientError as e:
                if e.status_code != 429 or attempt == self._MAX_RETRIES:
                    raise
                wait = self._parse_retry_delay(e) or (15 * attempt)
                print(f"  ⏳ Rate limit (429) — chờ {wait}s rồi thử lại "
                      f"(lần {attempt}/{self._MAX_RETRIES})...")
                time.sleep(wait)
        raise RuntimeError("Unreachable")  # pragma: no cover

    @staticmethod
    def _parse_retry_delay(err: Exception) -> float | None:
        """Trích retryDelay từ error response của Gemini (vd '59s' -> 60.0)."""
        msg = str(err)
        m = re.search(r"retryDelay.*?(\d+)", msg)
        if m:
            return float(m.group(1)) + 1  # +1s buffer
        return None

    def _tool_config(self, tools_full):
        """Chuyển schema format OpenAI của lab -> FunctionDeclaration của Gemini."""
        types = self._types
        decls = [
            types.FunctionDeclaration(
                name=t["function"]["name"],
                description=t["function"]["description"],
                parameters=t["function"]["parameters"],  # JSON Schema (OpenAPI subset)
            )
            for t in (tools_full or [])
        ]
        return types.Tool(function_declarations=decls)

    def decide(self, system_prompt, user_msg, tool_names, tools_full=None):
        types = self._types
        config = types.GenerateContentConfig(
            system_instruction=system_prompt,
            tools=[self._tool_config(tools_full)] if tools_full else None,
        )
        resp = self._call_with_retry(
            self.client.models.generate_content,
            model=self.model, contents=user_msg, config=config,
        )
        if resp.function_calls:
            return ModelResponse(tool_calls=[
                ToolCall(fc.name, dict(fc.args)) for fc in resp.function_calls
            ])
        return ModelResponse(text=resp.text)

    def summarize_tool_results(self, results, user_msg):
        """Gửi TẤT CẢ kết quả của một lượt trong một lần gọi model (không ghi đè)."""
        types = self._types
        blocks = "\n".join(
            f"- Tool {name}: {json.dumps(res, ensure_ascii=False)}" for name, res in results
        )
        action = ",".join(name for name, _ in results)
        prompt = (
            f"Câu hỏi người dùng: {user_msg}\n"
            f"Kết quả các tool đã chạy:\n{blocks}\n"
            "Tổng hợp MỌI kết quả trên vào một câu trả lời. Chỉ dựa trên kết quả tool, "
            'trả về JSON đúng 3 field {"intent": "...", "action": "%s", "reply": "..."} '
            "bằng tiếng Việt." % action
        )
        resp = self._call_with_retry(
            self.client.models.generate_content,
            model=self.model,
            contents=prompt,
            config=types.GenerateContentConfig(response_mime_type="application/json"),
        )
        return ModelResponse(text=resp.text)

    def summarize_tool_result(self, tool_name, tool_result, user_msg):
        types = self._types
        prompt = (
            f"Câu hỏi người dùng: {user_msg}\n"
            f"Kết quả tool {tool_name}: {json.dumps(tool_result, ensure_ascii=False)}\n"
            'Chỉ dựa trên kết quả tool, trả về JSON đúng 3 field '
            '{"intent": "...", "action": "%s", "reply": "..."} bằng tiếng Việt.' % tool_name
        )
        resp = self._call_with_retry(
            self.client.models.generate_content,
            model=self.model,
            contents=prompt,
            config=types.GenerateContentConfig(response_mime_type="application/json"),
        )
        return ModelResponse(text=resp.text)
