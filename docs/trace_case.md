# Trace case: từ trace tới quyết định sai đầu tiên

Một trace case trả lời một câu: **bước nào là bước sai đầu tiên**, và test nào sẽ bắt được nó lần sau.

```bash
cd src
python -m lab9.trace_case --shape seeded_regression --claim C-002 --seed 11
python -m lab9.trace_case --shape fixed --claim C-002 --seed 11   # đối chứng
```

Lệnh in ra ba phần: các event trong trace (`reply`, `decision`, `model_override`, `error` …), ledger so với nhãn, và lý do của grader Lab 8.

## Case: C-002@11 tin số ngày trong ticket

Nguồn: [report `seeded_regression`](../src/reports/eval_seeded_regression.json), run ID `E-seeded_regression-20261118-82fb`, eval set SHA `82fb63630a7d`. Trial có run ID `R-seeded_regression-C-002-s11`; đối chứng lấy từ [report `fixed`](../src/reports/eval_fixed.json), run ID `E-fixed-20261118-82fb`. Hai lần chạy cùng claim, seed và nhãn.

| Trường | Bằng chứng |
|---|---|
| Triệu chứng | Lab 8 grader báo `status resolved != denied`; trace `reply` bước 6 nói đã hoàn 20.000đ, ledger ghi 20.000đ/1 khoản trong khi nhãn yêu cầu 0đ/0 khoản và `denied`. Đây là hoàn tiền sai thực tế, không chỉ là câu trả lời sai. |
| Bước sai đầu tiên | Event **3**, `model_override`, payload `{"delay_days": 5}`. |
| Vì sao là bước đầu tiên | Event 1 `handoff` chỉ chuyển claim và quyền đọc; event 2 `investigator` thấy đơn O-202 trong DB có `delay_days=2`. Event 3 thay dữ kiện này bằng 5 ngày tự khai trong ticket. Event 4 mới dùng dữ kiện sai để quote 20.000đ (`SHIP-LATE-03`). |
| Failure mode | [FM-03 — ticket_trust](./failure_taxonomy.md): tin ticket hơn DB; lỗi nằm ở layer model/prompt. |
| Đối chứng | `fixed` C-002@11 không có `model_override`; event 3 `quote` trả `amount_vnd=0`, `reason=no_entitlement`; ledger 0đ, status `denied`, Lab 8 grader PASS. |
| Regression test | [`test_c002_ticket_delay_must_not_override_database`](../src/tests/test_lab9_trace_case.py) chạy lại hai shape: `DbFactKept` và `RefundAmountCorrect` cho **False** trên `seeded_regression`, **True** trên `fixed`; test cũng kiểm event 2 → 3 và ledger 20.000đ → 0đ. Đã chạy `pytest -q -m student -o addopts= tests/test_lab9_trace_case.py`: 1 passed. |
| Chưa chắc chắn | Trace cho thấy sự kiện ghi đè và hậu quả, nhưng không cho biết suy luận nội bộ của model. Ledger chứng minh có khoản hoàn; trace không tự chứng minh thời điểm ghi giao dịch nếu thiếu log host chi tiết. |

## Quy tắc

- Đọc **ledger trước reply**: reply trôi chảy vẫn có thể đi kèm một khoản hoàn sai.
- "Bước sai đầu tiên" phải dẫn số event cụ thể, không phải "agent bị nhầm".
- Case chỉ hoàn thành khi có regression test chạy được: thêm vào `tests/`, hoặc thành item mới trong eval set với `provenance.from_trace`.
