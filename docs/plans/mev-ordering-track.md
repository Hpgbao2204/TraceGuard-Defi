# Kế hoạch: TraceGuard-DeFi, phát hiện và ngăn chặn sandwich attack ở tầng builder

Tài liệu giao việc cho phiên Claude Code trên cloud. Đọc hết trước khi code.
Đọc thêm `CLAUDE.md` ở gốc repo để nắm cấu trúc và các lỗi đã biết.

## 1. Câu chuyện của bài (framing)

**Vấn đề.** Sandwich attack lấy giá trị của người dùng thường mỗi ngày. Các detector dựa trên hình dạng trace (mỗi giao dịch có bao nhiêu swap, pool nào, ai gửi) không phân biệt được sandwich với backrun arbitrage vô hại, nên:
- chặn theo heuristic thì chặn nhầm luồng arbitrage hợp lệ, vốn giúp thị trường cân bằng giá;
- không chặn thì người dùng mất tiền.

**Luận điểm chính.** Một giao dịch có hại hay không nằm ở *hệ quả nhân quả lên victim*, không nằm ở hình dạng của nó. Câu hỏi đúng là:

> "Nếu bỏ giao dịch X khỏi block, victim có nhận thêm tiền không?"

Hệ thống trả lời câu hỏi đó bằng replay counterfactual trên state có xác thực, ngay tại thời điểm xây block.

**Hệ thống 2 lớp (phễu):**

1. **Lớp 1: screener nhanh (phát hiện).** Chạy trên mọi bundle hay giao dịch builder nhận được và gắn cờ ứng viên nghi là sandwich. Recall cao, chấp nhận báo động nhầm.
2. **Lớp 2: kiểm tra thứ tự bằng counterfactual (xác nhận và ngăn chặn).** Với mỗi ứng viên, bỏ phần front-run rồi replay lại giao dịch của victim trên state hiện tại của block đang xây:
   - victim nhận thêm ≥ ngưỡng → CAUSE → **loại bundle tấn công khỏi block** (ngăn chặn);
   - victim không đổi → NO_EFFECT → giữ lại (không chặn nhầm arbitrage);
   - không so sánh được → INCONCLUSIVE(lý do) → áp chính sách mặc định do builder chọn, và báo cáo riêng.

**Vị trí triển khai (phải ghi rõ trong bài):** trong builder hoặc private RPC/order-flow (giống MEV-Blocker, Flashbots Protect), là nơi *có quyền quyết định* đưa giao dịch nào vào block. Không claim chặn trên public mempool.

**Claim chính xác (câu dùng trong abstract):**

> "TraceGuard prevents sandwich attacks in blocks assembled by a participating builder, while preserving benign backrun arbitrage, within the builder's per-slot latency budget."

Mỗi vế của câu này đều phải có thí nghiệm chứng minh (mục 4). Vế nào chưa đo được thì bỏ khỏi câu, không để nguyên.

**Tính mới so với công trình trước.** Phát hiện và đo thiệt hại sandwich đã có (Qin et al. S&P 2022, Torres et al. USENIX Security 2021, Züst 2021, Wang et al. 2022, Heimbach & Wattenhofer 2022); MEV-Blocker và Flashbots Protect bảo vệ bằng cách giấu giao dịch. Điểm khác của mình:
1. **Quyết định chặn dựa trên hệ quả nhân quả đo được** (replay counterfactual), không dựa trên heuristic hình dạng. Nhờ vậy dùng được cho mọi route: aggregator, multi-hop, Uniswap V3, token có phí chuyển.
2. **Ordering confound và fail-closed.** Bỏ front-run thì các giao dịch nằm giữa cũng đổi theo. Hệ thống phát hiện và báo cáo trường hợp này thay vì đoán.
3. **Phễu 2 lớp có số liệu:** lớp 1 rẻ nhưng nhầm nhiều, lớp 2 đắt nhưng chính xác. Đo được cả trade-off.

## 2. Giới hạn môi trường cloud (quan trọng)

- Repo là **public**. Không commit tên hay email tác giả, đường dẫn máy cá nhân, RPC key, dữ liệu, hay bản thảo paper.
- Cloud **không có** dữ liệu local và **không có** RPC archive. Việc gì cần RPC thì chỉ viết script và test bằng dữ liệu giả; chủ repo tự chạy script đó ở máy local.
- Việc tự làm trọn được trên cloud: code Go và Python, unit test, mô phỏng trên chain local (anvil không fork, không cần RPC).
- Ngân sách khoảng 100 USD credit. Mỗi phiên làm một milestone. Cuối milestone: commit, test pass, mở PR, dừng lại tóm tắt.

## 3. Milestones

### M1: Can thiệp thứ tự trong engine Go

File: `tools/geth-replay/main.go`, vòng `for i, tx := range txs[:*targetIndex+1]`.

- Thêm cờ `-drop-tx <index>` (lặp lại được): bỏ giao dịch prefix có index đó. Các giao dịch còn lại giữ nguyên calldata.
- Chạm vào account hoặc slot không có trong proof thì **fail-closed** và ghi lý do. Engine đã có `-replay-mode discovery` và `-extra-footprint` để lấy thêm state về sau.
- Output bổ sung:
  - `dropped_indices`
  - status và gas của từng giao dịch prefix sau can thiệp, kèm cờ "khác baseline"
  - danh sách giao dịch trung gian bị revert hoặc đổi kết quả (ordering confound)
- **Đo thời gian thực thi** tách riêng khỏi thời gian tải context: chỉ tính phần EVM replay trong bộ nhớ. Ghi ra `timing_ms`. Số này là bằng chứng cho vế "latency budget".
- Test Go bằng fixture tổng hợp: 3 giao dịch trên 1 pool.

**Xong khi:** `go test ./...` pass, có test cho các trường hợp drop, fail-closed, confound, và output có `timing_ms`.

### M2: Sổ thiệt hại và quyết định chặn (Python)

- `core/mev/sandwich_harm.py`:
  - Thiệt hại victim bằng `amountOut_cf - amountOut_obs`, lấy từ log `Transfer` gửi tới recipient của victim.
  - Quy đổi USD theo giá tại `b-1`.
- `core/mev/policy.py`: hàm quyết định `INCLUDE / EXCLUDE / DEFAULT(reason)` theo verdict CAUSE / NO_EFFECT / INCONCLUSIVE, ngưỡng cấu hình được.
- Control:
  - **Placebo:** bỏ một giao dịch không liên quan tới pool, phải ra NO_EFFECT.
  - **Backrun-only:** bỏ giao dịch nằm sau victim, phải ra NO_EFFECT.
- Unit test bằng JSON giả cùng định dạng output của geth-replay.

**Xong khi:** pytest pass cho mọi nhánh verdict và mọi nhánh policy.

### M3: Mô phỏng builder và mempool end-to-end (chạy được trên cloud)

Đây là phần demo "ngăn chặn" chạy thật, có ground truth.

- anvil không fork, deploy Uniswap V2 (factory, pair, 2 token ERC-20), có thể thêm một pool V3.
- **Mempool giả lập:** một hàng đợi giao dịch có timestamp. Gồm người dùng thường, bot arbitrage vô hại, và bot sandwich. Seed cố định.
- **Builder giả lập:** mỗi slot lấy giao dịch từ mempool, xây block ứng viên, chạy lớp 1 rồi lớp 2, loại bundle bị EXCLUDE, và ghi lại quyết định cùng thời gian xử lý.
- **Ground truth:** thiệt hại victim tính bằng công thức `x*y=k` (phí 0.3%); nhãn sandwich hay vô hại biết trước vì do mình sinh.
- **Kẻ tấn công thích nghi** (bắt buộc có, reviewer sẽ hỏi):
  - chia nhỏ front-run
  - đổi địa chỉ giữa front-run và back-run
  - đi qua router hoặc aggregator
  - sandwich multi-pool
  - chèn giao dịch mồi để tạo ordering confound
- **Đo:**
  - tỉ lệ sandwich bị chặn
  - tổng thiệt hại người dùng tránh được, so với builder không có filter
  - tỉ lệ arbitrage vô hại bị chặn nhầm
  - latency lớp 1 và lớp 2 mỗi slot, so với ngân sách slot 12 giây (và một ngân sách chặt hơn, ví dụ 500 ms)
  - so sánh với baseline chỉ dùng heuristic hình dạng (chặn mọi mẫu "front-victim-back")
- Output: `eval/mev_sim/results.json` (git-ignored) và bảng tóm tắt.

**Xong khi:** chạy trọn một lệnh, ra đủ các số trên, test pass.

### M4: Lấy dữ liệu sandwich thật (viết script, máy local chạy)

- `eval/mev/acquire_sandwiches.py`, nhận RPC qua biến môi trường:
  - Phát hiện theo heuristic kiểu mev-inspect-py (cùng searcher hoặc contract ở 2 phía, cùng pool, victim nằm giữa, hướng swap ngược nhau).
  - Kiểm tra chéo với nguồn nhãn công khai (ZeroMEV, EigenPhi) nếu truy cập được.
  - Lấy thêm backrun arbitrage và swap thường *trong cùng các block đó* làm control.
- Script dựng context replay: proof `eth_getProof` tại `b-1` cho prefix `0..victim_idx`, dùng lại pipeline dựng context B2 có sẵn.
- Test bằng RPC giả lập (mock). Không gọi mạng trong test.

### M5: Đánh giá "shadow mode" trên mainnet (code trên cloud, chạy ở local)

Câu hỏi: *"Nếu một builder đã dùng TraceGuard trong khoảng thời gian X, nó sẽ chặn được gì và chặn nhầm gì?"*

- **Lấy mẫu chống cherry-pick:** chọn ngẫu nhiên K block trong khoảng thời gian cố định, seed cố định; lấy *tất cả* sandwich và control trong các block đó. **Ghi hash của manifest vào commit trước khi chạy replay.**
- **Báo cáo đủ mẫu số:** số ứng viên, số dựng được context, số replay khớp baseline, số ra verdict, số INCONCLUSIVE theo từng lý do. Không bỏ case nào.
- **Đo:**
  - recall chặn trên sandwich thật
  - tỉ lệ chặn nhầm trên arbitrage và swap thường
  - thiệt hại USD tránh được, so với nhãn và ước lượng công thức AMM của nguồn công khai
  - tần suất ordering confound
  - latency lớp 2 đo ở M1, cộng giả định builder đã có sẵn state
  - Wilson CI cho mọi tỉ lệ
- `eval/mev/evaluate.py` xuất JSON.

### M6: Phễu 2 lớp

- Chấm cùng tập dữ liệu M5 bằng screener lớp 1.
- Cho thấy: lớp 1 một mình chặn nhầm nhiều arbitrage; thêm lớp 2 giảm chặn nhầm mà vẫn giữ recall; chi phí latency tăng bao nhiêu.
- Vẽ đường trade-off theo ngưỡng của lớp 1.

## 4. Bảng đối chiếu claim với bằng chứng (dùng khi viết paper)

| Claim trong bài | Bằng chứng bắt buộc | Nếu chưa có |
|---|---|---|
| Phát hiện sandwich | Recall lớp 1 và lớp 2 trên mainnet (M5, M6) | Chỉ nói "trên mô phỏng" |
| Ngăn chặn | Builder giả lập loại bundle, đo thiệt hại tránh được (M3); shadow mode trên mainnet (M5) | Đổi thành "cho phép builder ngăn chặn" |
| Không chặn nhầm arbitrage | Tỉ lệ chặn nhầm có CI (M3, M5) | Không claim |
| Trong ngân sách latency | `timing_ms` thực đo (M1, M3) | Bỏ vế latency khỏi abstract |
| Chống được kẻ tấn công thích nghi | Các kịch bản thích nghi ở M3 | Ghi là limitation |
| Không cherry-pick | Hash manifest commit trước khi chạy, đủ mẫu số (M5) | Không nộp |

## 5. Các lỗi hiện có phải sửa trước hoặc song song

1. `tools/geth-replay/scoping.go` đang coi `balanceOf(address)` là price selector. Tách thành factor riêng hoặc bỏ.
2. Frame-local không kiểm tra calldata attacker gửi victim có giống baseline không. Thêm kiểm tra; không khớp thì ra INCONCLUSIVE.
3. Sham phải thay bằng giá trị *khác thật* nhưng không liên quan. Isolation phải so hash log, không chỉ so số lượng.
4. CAUSE_BLOCKED phải kiểm tra frame gây revert thuộc victim.

## 6. Quy tắc làm việc

- Mỗi milestone đi trên một branch, mở PR, mô tả rõ đã test gì.
- Không sửa số liệu cũ để "cho khớp". Số nào chưa đo thì ghi là chưa đo.
- Test phải chạy được khi không có dữ liệu local; test nào cần dữ liệu thì `skip` kèm lý do.
- Cuối mỗi phiên: cập nhật bảng "Trạng thái" bên dưới.

## 7. Trạng thái

| Milestone | Trạng thái | Ghi chú |
|---|---|---|
| M1 | xong (chờ review PR) | `-drop-tx`, fail-closed, `ordering_intervention`, `timing_ms`; test tổng hợp 1 pool 3 giao dịch trong `tools/geth-replay/ordering_test.go`. Chưa chạy trên context mainnet thật. |
| M2 | chưa bắt đầu | |
| M3 | chưa bắt đầu | demo ngăn chặn, làm được hoàn toàn trên cloud |
| M4 | chưa bắt đầu | cần RPC, chạy ở local |
| M5 | chưa bắt đầu | cần RPC, chạy ở local |
| M6 | chưa bắt đầu | |
| Sửa lỗi mục 5 | chưa bắt đầu | |
