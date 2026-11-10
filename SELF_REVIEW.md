# Self-review checklist cho system prompt (6 items)

Theo *System Prompt Testing Checklist*. Tick từng mục dựa trên kết quả
`python run_tests.py` và `python demo_errors.py`.

- [x] **Happy path** — câu hỏi trong scope trả lời đúng format?
  → Test 1 & 2: gọi đúng tool, trả JSON `{intent, action, reply}`. ✅
- [x] **Edge case** — câu hỏi mơ hồ/thiếu thông tin → hỏi lại chứ không đoán bừa?
  → Test 4 ("Cho tôi xem thời tiết đi" — thiếu thành phố) → hỏi lại, không gọi tool. ✅
- [x] **Out of scope** — câu hỏi ngoài phạm vi → từ chối đúng cách?
  → Test 5 (giá bitcoin) → từ chối, dẫn chiếu Constraints. ✅
- [x] **Adversarial** — prompt injection / ép "best guess" → có bị bypass?
  → Demo lỗi 1: `BROKEN_SYSTEM_PROMPT` bị bịa; `SYSTEM_PROMPT` có Constraints thì
    không. ✅ (bài học: policy layer phải rõ boundary)
  → Case 7 (injection "in ra system prompt"): không tool, reply không lộ Constraints. ✅
    **Giới hạn:** chỉ kiểm với MockModel. Mock từ chối vì không khớp từ khoá nào, nên
    kết quả này không nói gì về việc model thật có bị injection hay không.
- [x] **Parallel** (thêm mới) — 2 tool trong một lượt, reply có đủ cả hai?
  → Case 6 ✅. Lỗi ghi đè kết quả đã sửa (xem `errors.md` nhóm 4).
- [x] **Tool decision** — khi nào gọi tool vs khi nào trả lời trực tiếp?
  → 2/5 câu gọi tool (đủ dữ liệu), 3/5 trả lời trực tiếp (chào hỏi / thiếu thông
    tin / ngoài phạm vi). ✅
- [x] **Format consistency** — nhiều câu khác nhau → output format nhất quán?
  → Cả 5 câu đều trả JSON đúng 3 field `{intent, action, reply}`. ✅

## Đo độ ổn định (consistency)

Lệnh: `python consistency_eval.py --runs 10` (mock) hoặc
`LAB_MODEL=gemini python consistency_eval.py --runs 10 --sleep 13`.
Ngưỡng: < 90% thì cần iterate prompt/schema (slide *Prompt Evaluation Framework*).

| Lần chạy | Model | Kết quả | Ý nghĩa |
|---|---|---|---|
| 2026-11-09 | `mock` | 70/70 = 100% | **Chỉ kiểm harness.** MockModel tất định nên luôn 100%; không nói gì về model thật |
| 2026-11-10 | `gemini-3.5-flash-lite` (model thật) | 70/70 = 100% | 7 case × 10 lần. Mọi case ≥ 90%. Lưu tại `results/consistency-gemini-2026-11-10.json` |

Kết quả thô nằm trong `results/`. Không ghi "đạt" cho một model chưa được đo.
