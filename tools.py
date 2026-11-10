"""
tools.py — Task 2: Hai custom tools.

  Tool 1 (API wrapper):  get_weather(city)      -> bọc một API thời tiết bên ngoài.
  Tool 2 (data query):   query_sales(region...) -> truy vấn dữ liệu bán hàng nội bộ.

Bám sát "Tool Schema Anatomy" và "Tool Return Format Best Practices":
  - description = tài liệu cho model: (1) chức năng, (2) KHI NÀO dùng, (3) khi nào KHÔNG dùng.
  - parameters mô tả bằng JSON Schema, có `required`, dùng `enum` + ví dụ để giảm lỗi arguments.
  - Mọi tool TRẢ VỀ JSON có cấu trúc:
        success -> {"status": "success", "data": {...}, "source": "..."}
        error   -> {"status": "error", "message": "...", "code": "..."}
    (Model xử lý structured JSON tốt hơn nhiều so với raw text/HTML.)

Nguyên tắc thiết kế tool: Single Responsibility, Idempotency, Granularity hợp lý,
Test độc lập. Mỗi tool ở đây làm ĐÚNG một việc nghiệp vụ và test được mà không cần agent.
"""

from __future__ import annotations

import csv
import json
import os
import urllib.error
import urllib.request
from pathlib import Path

from console import ensure_utf8_stdout

ensure_utf8_stdout()

DATA_DIR = Path(__file__).parent / "data"


# ---------------------------------------------------------------------------
# TOOL 1 — API WRAPPER: get_weather(city)
# ---------------------------------------------------------------------------
# Đây là ví dụ "API wrapper đơn giản": nhận input của model -> gọi API bên ngoài
# -> chuẩn hoá kết quả về JSON có cấu trúc + xử lý lỗi (timeout, not found).
#
# Mặc định tool chạy OFFLINE bằng một "backend giả lập" để lab luôn chạy được
# trong lớp (không cần mạng, không cần API key). Đặt biến môi trường
#     USE_REAL_WEATHER_API=1
# để thử gọi API thật open-meteo (miễn phí, không cần key).

# "Backend" giả lập của một API thời tiết bên ngoài (đơn vị: độ C).
# `name` = tên hiển thị đẹp; key = dạng đã chuẩn hoá.
_FAKE_WEATHER_BACKEND = {
    "hanoi": {"name": "Hà Nội", "temp_c": 33, "condition": "nắng"},
    "ho chi minh": {"name": "Hồ Chí Minh", "temp_c": 31, "condition": "mưa rào"},
    "da nang": {"name": "Đà Nẵng", "temp_c": 30, "condition": "nhiều mây"},
    "hue": {"name": "Huế", "temp_c": 29, "condition": "mưa"},
}

# Bảng toạ độ tối thiểu cho nhánh gọi API thật (open-meteo cần lat/lon).
_CITY_COORDS = {
    "hanoi": (21.03, 105.85),
    "ho chi minh": (10.82, 106.63),
    "da nang": (16.05, 108.22),
    "hue": (16.46, 107.59),
}


def _normalize_city(city: str) -> str:
    """Chuẩn hoá tên thành phố: bỏ dấu cách thừa, lowercase, gộp vài alias."""
    c = " ".join(city.strip().lower().split())
    aliases = {
        "ha noi": "hanoi",
        "hà nội": "hanoi",
        "hanoi": "hanoi",
        "sài gòn": "ho chi minh",
        "saigon": "ho chi minh",
        "tphcm": "ho chi minh",
        "hcm": "ho chi minh",
        "hồ chí minh": "ho chi minh",
        "đà nẵng": "da nang",
        "danang": "da nang",
        "huế": "hue",
    }
    return aliases.get(c, c)


def _get_weather_real(city_key: str, timeout: float) -> dict:
    """Gọi API thật open-meteo. Ném exception nếu lỗi -> caller sẽ fallback."""
    lat, lon = _CITY_COORDS[city_key]
    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={lat}&longitude={lon}&current=temperature_2m"
    )
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        payload = json.loads(resp.read().decode())
    temp = payload["current"]["temperature_2m"]
    return {"temp_c": round(temp), "condition": "(theo open-meteo)"}


def get_weather(city: str, timeout: float = 3.0) -> dict:
    """Trả về thời tiết hiện tại của một thành phố dưới dạng JSON có cấu trúc.

    Đây là phần IMPLEMENTATION mà Developer viết (Developer
    định nghĩa schema + viết implementation + handle errors).
    """
    if not city or not city.strip():
        # required field bị thiếu -> báo lỗi rõ ràng, không đoán bừa.
        return {
            "status": "error",
            "message": "Thiếu tham số 'city'.",
            "code": "MISSING_ARGUMENT",
        }

    key = _normalize_city(city)

    # Nhánh gọi API thật (tùy chọn). Có xử lý timeout + fallback ("Xử lý Tool Errors").
    if os.environ.get("USE_REAL_WEATHER_API") == "1" and key in _CITY_COORDS:
        try:
            data = _get_weather_real(key, timeout)
            return {
                "status": "success",
                "data": {"city": key, **data},
                "source": "open-meteo.com",
            }
        except (urllib.error.URLError, TimeoutError, KeyError, ValueError):
            # Không "retry silently" mãi — fallback sang backend giả lập.
            pass

    # Nhánh offline (mặc định).
    if key not in _FAKE_WEATHER_BACKEND:
        return {
            "status": "error",
            "message": f"Không có dữ liệu thời tiết cho '{city}'.",
            "code": "CITY_NOT_FOUND",
        }
    entry = _FAKE_WEATHER_BACKEND[key]
    return {
        "status": "success",
        "data": {"city": entry["name"], "temp_c": entry["temp_c"], "condition": entry["condition"]},
        "source": "fake-weather-backend (offline)",
    }


GET_WEATHER_SCHEMA = {  # Format OpenAI; Gemini adapter convert ở llm.py
    "type": "function",
    "function": {
        "name": "get_weather",
        # description tốt = chức năng + KHI NÀO dùng + khi nào KHÔNG dùng.
        "description": (
            "Lấy thời tiết hiện tại (nhiệt độ, tình trạng) của MỘT thành phố. "
            "Dùng KHI người dùng hỏi về thời tiết/nhiệt độ/trời mưa-nắng của một "
            "thành phố cụ thể. KHÔNG dùng cho câu hỏi chung chung, dự báo nhiều "
            "ngày, hay khi người dùng chưa nói rõ thành phố nào."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "city": {
                    "type": "string",
                    "description": "Tên thành phố, ví dụ: 'Hà Nội', 'Đà Nẵng'.",
                }
            },
            "required": ["city"],
        },
    },
}


# ---------------------------------------------------------------------------
# TOOL 2 — DATA QUERY: query_sales(region, product, month)
# ---------------------------------------------------------------------------
# Ví dụ "data query đơn giản": đọc dữ liệu nội bộ (data/sales.csv), lọc, tổng hợp,
# rồi trả JSON có cấu trúc. Không gọi mạng -> luôn chạy được, dễ test độc lập.

_VALID_REGIONS = {"North", "South", "Central"}
_VALID_PRODUCTS = {"laptop", "phone"}


def _load_sales_rows() -> list[dict]:
    with open(DATA_DIR / "sales.csv", newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def query_sales(region: str, product: str | None = None, month: str | None = None) -> dict:
    """Tổng hợp doanh thu & số lượng bán theo region (+ tuỳ chọn product, month)."""
    if region not in _VALID_REGIONS:
        return {
            "status": "error",
            "message": f"region không hợp lệ. Chọn một trong {sorted(_VALID_REGIONS)}.",
            "code": "INVALID_ARGUMENT",
        }
    if product is not None and product not in _VALID_PRODUCTS:
        return {
            "status": "error",
            "message": f"product không hợp lệ. Chọn một trong {sorted(_VALID_PRODUCTS)}.",
            "code": "INVALID_ARGUMENT",
        }

    rows = _load_sales_rows()
    matched = [
        r
        for r in rows
        if r["region"] == region
        and (product is None or r["product"] == product)
        and (month is None or r["month"] == month)
    ]

    if not matched:
        return {
            "status": "error",
            "message": "Không có dữ liệu khớp với truy vấn.",
            "code": "NO_DATA",
        }

    total_revenue = sum(int(r["revenue_usd"]) for r in matched)
    total_units = sum(int(r["units"]) for r in matched)
    return {
        "status": "success",
        "data": {
            "region": region,
            "product": product or "all",
            "month": month or "all",
            "total_revenue_usd": total_revenue,
            "total_units": total_units,
            "rows_matched": len(matched),
        },
        "source": "data/sales.csv",
    }


QUERY_SALES_SCHEMA = {  # Format OpenAI; Gemini adapter convert ở llm.py
    "type": "function",
    "function": {
        "name": "query_sales",
        "description": (
            "Truy vấn dữ liệu bán hàng nội bộ và tổng hợp doanh thu (USD) + số "
            "lượng bán theo khu vực. Dùng KHI người dùng hỏi về doanh thu/doanh "
            "số/số lượng bán của một khu vực. KHÔNG dùng cho câu hỏi ngoài phạm "
            "vi bán hàng (thời tiết, tin tức, ý kiến cá nhân)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "region": {
                    "type": "string",
                    "description": "Khu vực cần tra cứu.",
                    "enum": ["North", "South", "Central"],
                },
                "product": {
                    "type": "string",
                    "description": "Lọc theo sản phẩm (tuỳ chọn).",
                    "enum": ["laptop", "phone"],
                },
                "month": {
                    "type": "string",
                    "description": "Lọc theo tháng, định dạng YYYY-MM, ví dụ '2026-07' (tuỳ chọn).",
                },
            },
            "required": ["region"],
        },
    },
}


# ---------------------------------------------------------------------------
# TOOL 3 — EXCHANGE RATE: get_exchange_rate(from_currency, to_currency)
# ---------------------------------------------------------------------------
# Bài tập mở rộng số 1 (README): tool thứ 3, dùng để thử pattern parallel
# fetch + merge (gọi cùng lúc với get_weather trong một lượt).
# Bảng tỷ giá OFFLINE, cố định để test tất định. Đơn vị: VND cho 1 đơn vị ngoại tệ.
_FX_TO_VND = {"USD": 25400, "EUR": 27600, "JPY": 165, "VND": 1}


def get_exchange_rate(from_currency: str, to_currency: str) -> dict:
    """Tỷ giá: 1 đơn vị `from_currency` = bao nhiêu `to_currency`."""
    f = (from_currency or "").strip().upper()
    t = (to_currency or "").strip().upper()
    if not f or not t:
        return {
            "status": "error",
            "message": "Thiếu tham số 'from_currency' hoặc 'to_currency'.",
            "code": "MISSING_ARGUMENT",
        }
    for code in (f, t):
        if code not in _FX_TO_VND:
            return {
                "status": "error",
                "message": f"Mã tiền tệ '{code}' không hỗ trợ. Chọn một trong {sorted(_FX_TO_VND)}.",
                "code": "INVALID_ARGUMENT",
            }
    rate = _FX_TO_VND[f] / _FX_TO_VND[t]
    return {
        "status": "success",
        "data": {"from": f, "to": t, "rate": round(rate, 6)},
        "source": "fx-offline-table",
    }


GET_EXCHANGE_RATE_SCHEMA = {
    "type": "function",
    "function": {
        "name": "get_exchange_rate",
        "description": (
            "Lấy tỷ giá giữa hai đơn vị tiền tệ (USD, EUR, JPY, VND). Dùng KHI người "
            "dùng hỏi tỷ giá hoặc muốn đổi từ loại tiền này sang loại tiền khác. "
            "KHÔNG dùng cho giá tiền điện tử, dự báo tỷ giá, hay lời khuyên đầu tư."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "from_currency": {
                    "type": "string",
                    "description": "Mã tiền tệ nguồn, ví dụ 'USD'.",
                    "enum": ["USD", "EUR", "JPY", "VND"],
                },
                "to_currency": {
                    "type": "string",
                    "description": "Mã tiền tệ đích, ví dụ 'VND'.",
                    "enum": ["USD", "EUR", "JPY", "VND"],
                },
            },
            "required": ["from_currency", "to_currency"],
        },
    },
}


# ---------------------------------------------------------------------------
# TOOL REGISTRY — nối tên tool -> (schema, hàm thực thi)
# ---------------------------------------------------------------------------
TOOLS = {
    "get_weather": {"schema": GET_WEATHER_SCHEMA, "fn": get_weather},
    "query_sales": {"schema": QUERY_SALES_SCHEMA, "fn": query_sales},
    "get_exchange_rate": {"schema": GET_EXCHANGE_RATE_SCHEMA, "fn": get_exchange_rate},
}


def tool_schemas() -> list[dict]:
    """Danh sách schema để truyền cho model qua tham số `tools`."""
    return [t["schema"] for t in TOOLS.values()]


def execute_tool(name: str, arguments: dict) -> dict:
    """Application thực thi tool call và trả về JSON kết quả."""
    if name not in TOOLS:
        # "Xử lý Tool Errors": tool not found -> log + return error JSON.
        return {"status": "error", "message": f"Tool '{name}' không tồn tại.", "code": "TOOL_NOT_FOUND"}
    try:
        return TOOLS[name]["fn"](**arguments)
    except TypeError as e:
        # arguments sai/thiếu so với chữ ký hàm -> lỗi thuộc loại TOOL SCHEMA.
        return {"status": "error", "message": f"Arguments không hợp lệ: {e}", "code": "BAD_ARGUMENTS"}


if __name__ == "__main__":
    # Test độc lập từng tool TRƯỚC khi gắn vào agent (nguyên tắc 'Test độc lập').
    print("get_weather('Hà Nội')   ->", json.dumps(get_weather("Hà Nội"), ensure_ascii=False))
    print("get_weather('Paris')    ->", json.dumps(get_weather("Paris"), ensure_ascii=False))
    print("get_weather('')         ->", json.dumps(get_weather(""), ensure_ascii=False))
    print("query_sales('North')    ->", json.dumps(query_sales("North"), ensure_ascii=False))
    print("query_sales('North','phone','2026-07') ->",
          json.dumps(query_sales("North", "phone", "2026-07"), ensure_ascii=False))
    print("query_sales('Mars')     ->", json.dumps(query_sales("Mars"), ensure_ascii=False))
