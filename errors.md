# Ghi chú lỗi — Prompt / Tool schema / Control flow (Task 5)

> Câu hỏi mở đầu buổi học: *"Cùng một agent, đôi khi gọi tool đúng, đôi khi sai —
> do prompt hay do tool?"*
> Phân loại đúng **nhóm lỗi** mới sửa đúng chỗ. Chạy `python demo_errors.py` để
> tái hiện cả 4 lỗi dưới đây (mỗi lỗi: SYMPTOM → DIAGNOSIS → FIX).

| # | Nhóm lỗi | Dấu hiệu (symptom) | Nguyên nhân gốc | Cách sửa |
|---|----------|--------------------|-----------------|----------|
| 1 | **PROMPT** | Hỏi giá bitcoin → agent **bịa** "tăng ~5%" thay vì từ chối | System prompt mơ hồ, thiếu `Constraints`, còn ép *"make your best guess"* | Thêm ràng buộc `NEVER: lời khuyên tài chính` + quy tắc từ chối khi ngoài phạm vi |
| 2 | **TOOL SCHEMA** | `query_sales(region="miền Bắc")` → `INVALID_ARGUMENT` | Schema `region` **thiếu `enum`/ví dụ** → model đoán giá trị theo ngôn ngữ người dùng | Khai báo `"enum": ["North","South","Central"]` để model buộc truyền đúng mã |
| 3 | **CONTROL FLOW** | Gọi tool xong nhưng câu trả lời **rỗng** | Vòng lặp agent **quên bước 4** (feed tool result trở lại model) | Sau khi execute tool, luôn gọi lại model với kết quả rồi mới trả lời |
| 4 | **CONTROL FLOW** (biến thể) | Model gọi **2 tool trong một lượt**, câu trả lời chỉ phản ánh **tool cuối** | Vòng `for` ghi đè `resp` bằng kết quả summarize của từng tool → kết quả các tool trước bị mất | Gom kết quả của cả lượt, feed lại model **một lần** (`summarize_tool_results`) |

## Chi tiết & cách phân biệt

### 1. Lỗi PROMPT
- **Bằng chứng:** giữ nguyên tool + vòng lặp, chỉ đổi `BROKEN_SYSTEM_PROMPT`
  ↔ `SYSTEM_PROMPT`. Prompt kém → bịa; prompt tốt → từ chối. ⇒ lỗi nằm ở **prompt**.
- **Bám slide:** *System Prompt Anti-Patterns* (mơ hồ, thiếu boundary) và
  *Negative Prompting* (phải nói rõ nên làm gì thay vì chỉ nói "đừng").
- **Cách nhận diện chung:** hành vi sai nhưng tool chạy đúng khi test độc lập, và
  đổi câu chữ prompt là hành vi đổi theo.

### 2. Lỗi TOOL SCHEMA
- **Bằng chứng:** hàm `query_sales("North")` chạy đúng khi test độc lập; chỉ hỏng
  khi **arguments** sai giá trị. Root cause là mô tả schema, không phải logic hàm.
- **Bám slide:** *Tool Schema Anatomy*, *Parameter Design Best Practices*
  (dùng `enum`, ví dụ trong description để giảm lỗi arguments) và
  *Good vs Bad Tool Description*.
- **Các biến thể thường gặp:** description quá ngắn ("gets weather") → model không
  biết khi nào dùng; thiếu `required` → model gọi khi chưa đủ dữ liệu; enum thiếu →
  sai giá trị; hai tool mô tả chồng lấn → model chọn nhầm tool.

### 3. Lỗi CONTROL FLOW
- **Bằng chứng:** `run_agent_broken()` gọi đúng tool, nhận đúng kết quả, nhưng
  **không feed lại** cho model ⇒ câu trả lời rỗng. `run_agent()` chuẩn thì đúng.
- **Bám slide:** *Tool Calling Flow* (4 bước) và *Tool calling là bài toán control
  flow*: khi nào gọi, gọi cái gì, theo thứ tự nào, và làm gì khi tool fail.
- **Các biến thể thường gặp:** quên feed result; thiếu `max_steps` → loop vô hạn;
  không xử lý `status="error"` từ tool → agent treo hoặc trả lời sai;
  retry im lặng quá nhiều lần (slide *Xử lý Tool Errors*: không retry quá 2 lần).

### 4. Lỗi CONTROL FLOW — biến thể: nhiều tool call trong một lượt
- **Bằng chứng:** `run_agent_overwrite_broken()` trong `demo_errors.py` (bản cũ). Với câu
  "Thời tiết Hà Nội và tỷ giá USD sang VND", model gọi **cả hai** tool, cả hai chạy đúng,
  nhưng reply cuối chỉ là `"Tỷ giá: 1 USD = 25,400 VND."`. Thông tin thời tiết bị mất.
  Bản hiện tại trả về cả hai (`"Thời tiết Hà Nội: 33°C, nắng. | Tỷ giá: …"`).
- **Vì sao khó thấy:** với một tool mỗi lượt, bản cũ và bản đúng cho ra cùng kết quả.
  Lỗi chỉ lộ ra khi có parallel tool call, nên test một-tool-mỗi-câu không bắt được.
- **Phát hiện:** chạy stub model trả 2 tool call (Hà Nội + Đà Nẵng); reply chỉ còn
  "Đà Nẵng". Test `test_offline.py::ParallelLoopTests` là hồi quy cho lỗi này.
- **Bám slide:** *Tool Use Patterns* — pattern *parallel fetch + merge*.
- **Nguyên tắc:** kết quả của cả lượt phải đi vào model **cùng lúc** (một lượt
  `summarize`), không được xử lý từng tool rồi ghi đè trạng thái chung.

## Lỗi phát hiện khi kiểm tra test (không phải lỗi agent)

- **Test chỉ so tên tool** (trước đây): `run_tests.py` không kiểm `arguments` và nội
  dung reply, nên `query_sales(region="miền Bắc")` vẫn PASS. Đã sửa: `Case` có
  `expect_args` và `expect_in_reply`; `test_offline.py` chứng minh lỗi này bị bắt.
- **Encoding Windows:** script in tiếng Việt crash với `UnicodeEncodeError` trên console
  cp1252. Đã sửa bằng `console.py` (đặt stdout UTF-8).

## Bảng chẩn đoán nhanh "do prompt hay do tool?"

```
Tool chạy đúng khi test độc lập?
├─ KHÔNG → sửa implementation của tool (bug code, không thuộc 3 nhóm trên)
└─ CÓ → Model truyền arguments đúng không?
        ├─ SAI arguments / gọi nhầm tool   → LỖI TOOL SCHEMA (sửa description/enum/required)
        └─ ĐÚNG → Kết quả có được đưa lại model & trả lời cuối không?
                  ├─ KHÔNG → LỖI CONTROL FLOW (sửa vòng lặp)
                  └─ CÓ nhưng nội dung/ hành vi sai → LỖI PROMPT (sửa rules/constraints/format)
```
