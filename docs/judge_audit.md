# Judge audit (M2)

Chạy từ `src/`:

```text
python -m lab9.judge --csv data/eval/judge_tone_public.csv --audit 12
python -m lab9.judge --csv data/eval/judge_helpful_public.csv --audit 12
```

Nhãn dương là **FAIL** (mục tiêu là phát hiện câu trả lời lỗi). Các số dưới đây tính trên CSV replay gốc, trước khi sửa bất kỳ nhãn nào. FLOORS: κ ≥ 0.6, precision ≥ 0.8, recall ≥ 0.7; κ không xác định thì FAIL.

| Tiêu chí | n | TP / FP / FN / TN | κ | Precision | Recall | Đạt FLOORS? | Quyết định |
|---|---:|---|---:|---:|---:|---|---|
| `tone_ok` | 100 | 24 / 4 / 6 / 66 | 0.757 | 0.857 | 0.800 | Có | Có thể dùng cho tone sau khi rà nhãn và kiểm thử lại trên tập mới. |
| `helpful` | 100 | 9 / 0 / 21 / 70 | 0.375 | 1.000 | 0.300 | Không | Loại khỏi release gate. |

Tỉ lệ FAIL do judge quan sát là 0.28 (`tone_ok`) và 0.09 (`helpful`). Hiệu chỉnh Rogan–Gladen trên tập này cho 0.30 ở cả hai tiêu chí. Con số hiệu chỉnh của `helpful` không biến judge thành đáng tin: nó đã bỏ sót 21/30 lỗi thật.

## Audit bất đồng thủ công

| # | Case / tiêu chí | Judge nói | Nhãn người | Ai đúng? | Hành động sửa rubric hoặc dữ liệu |
|---:|---|---|---|---|---|
| 1 | H-008 / tone: “Em đã hoàn tiền ... nha” | PASS | FAIL | Người | Ghi rõ xưng “em” và “nha” suồng sã trong ngữ cảnh CSKH là FAIL, dù câu thân thiện. |
| 2 | H-029 / tone: “không cần nhắn thêm” | PASS | FAIL | Người | Thêm quy tắc lời ra lệnh/ngăn khách liên hệ tiếp là FAIL; không cho “Dạ, vui lòng” che phần sau. |
| 3 | H-042 / tone: câu hoàn tiền ngắn, đủ ý | FAIL | PASS | Người | Bỏ yêu cầu phải xin lỗi trong mọi câu; câu lịch sự, đủ thông tin vẫn PASS. |
| 4 | H-051 / tone: dùng từ “refund” | FAIL | PASS | Người | Cho phép thuật ngữ “refund” theo chuẩn CS LogiX; không phạt chỉ vì có một từ tiếng Anh. |
| 5 | H-063 / tone: hứa “sẽ hoàn thêm” | PASS | FAIL | Người | Thêm quy tắc hứa hoàn thêm ngoài kết quả hệ thống là FAIL; nếu kiểm tra số tiền thật, dùng grader code thay vì tone judge. |
| 6 | H-081 / tone: câu từ chối lịch sự | FAIL | PASS | Judge theo ghi chú gốc | Ghi chú CSV nói nhãn người bị đọc nhầm ticket; đưa ca này cho người thứ hai rà lại và sửa nhãn nếu xác nhận, rồi hiệu chuẩn lại. |
| 7 | H-088 / tone: lặp “Dạ, dạ” | FAIL | PASS | Người | Xác định lỗi gõ lặp nhẹ không tự động làm tone FAIL nếu nội dung vẫn rõ và lịch sự. |
| 8 | H-094 / tone: tiếng Việt không dấu do dịch máy | PASS | FAIL | Người | Thêm ví dụ ngôn ngữ máy dịch, mất dấu toàn câu là FAIL. |
| 9 | HL-015 / helpful: báo hoàn 55.000đ, ledger 40.000đ | PASS | FAIL | Người | Bổ sung điều kiện helpful phải khớp ledger; kiểm số tiền bằng grader code FM-08. |
| 10 | HL-016 / helpful: lời xin lỗi dài nhưng 55.000đ, ledger 35.000đ | PASS | FAIL | Người | Chấm tính đúng của giao dịch trước độ dài/lịch sự; thêm ví dụ câu dài che sai tiền. |
| 11 | HL-020 / helpful: báo 90.000đ, ledger 120.000đ | PASS | FAIL | Người | Thêm cả ca báo thiếu tiền; grader code phải so số tiền hai chiều. |

## Kết luận

- `tone_ok` qua các sàn trên dữ liệu replay hiện có, nên chỉ dùng cho tiêu chí giọng điệu; rà lại H-081 và chạy lại calibration khi sửa nhãn.
- `helpful` không được làm gate: 21 false negative trên 30 lỗi, chủ yếu vì câu văn trôi chảy che số tiền sai. Precision = 1.0 chỉ có nghĩa 9 lỗi judge đã báo đều đúng, không bù được recall = 0.3.
- Tiền, approval và đối chiếu reply với ledger phải dùng grader code. Replay CSV công khai chưa phải held-out; cần nhãn người mới trước khi áp dụng cho model thật.
