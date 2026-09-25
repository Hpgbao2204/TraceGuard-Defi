# Kế hoạch: mở rộng TraceGuard-DeFi sang tấn công thứ tự giao dịch (MEV sandwich)

Tài liệu giao việc cho phiên Claude Code trên cloud. Đọc hết trước khi code.
Đọc thêm `CLAUDE.md` ở gốc repo để nắm cấu trúc và các lỗi đã biết.

## 1. Bối cảnh và quyết định

**Vấn đề của hướng hiện tại (khai thác lỗ hổng giao thức):**
- Bộ 20 case bị góp ý là "cherry-pick": tự chọn những case chạy được.
- Nhiều case không thể xử lý triệt để: code bị obfuscate, proxy upgrade, luồng off-chain (lộ key, multisig), hoặc chính giao thức có backdoor hay tham gia vào vụ tấn công.
- Hệ quả là phần lớn verdict ra INCONCLUSIVE.

**Hướng mới:** áp dụng chính 2 lớp của hệ thống cho tấn công dựa trên *thứ tự giao dịch*, trước hết là sandwich. Lý do hướng này hợp:
- **Victim rõ ràng.** Victim là một swap của người dùng vào AMM có mã nguồn công khai, không có phần off-chain. Thiệt hại đo trực tiếp được: số token victim nhận thiếu đi.
- **Can thiệp tự nhiên, dùng lại được engine.** Can thiệp tự nhiên nhất là *bỏ giao dịch front-run khỏi prefix của block* rồi replay lại swap của victim. Engine Go đã replay sẵn prefix `0..k-1` từ state có xác thực Merkle tại `b-1`, nên chỉ cần thêm thao tác bỏ hoặc đổi thứ tự giao dịch.
- **Giải đúng điểm yếu của Stage 1.** Stage 1 không phân biệt được arbitrage/backrun vô hại với tấn công (FPR lên 16.77% trên near-negative). Counterfactual phân biệt được: bỏ một backrun thì victim không đổi (NO_EFFECT), bỏ một front-run thì victim nhận nhiều hơn (CAUSE).
- **Vẫn có một bài toán "confound" để giữ tính mới.** Khi bỏ front-run, các giao dịch nằm giữa front-run và victim (của người khác, của bot khác) chạy trên state khác, có thể revert hoặc đổi kết quả. Đây là **"ordering confound"**, tương tự revert confound ở hướng cũ. Các cổng hợp lệ đã có (revert-origin, isolation, sham, fail-closed khi thiếu state) áp dụng lại được.

**Những gì KHÔNG claim:**
- **Không claim "prevent/chặn MEV realtime".** Replay trung vị khoảng 515 giây/case, nên hệ thống là công cụ *đo và quy trách nhiệm sau sự việc* (post-hoc attribution), không chặn được trong mempool.
- **Không dùng Zombienet (Polkadot) hay Hyperledger.** Chúng không có EVM, AMM hay mempool MEV kiểu Ethereum, nên kết quả không chuyển sang Ethereum được.
- **Không dùng mô phỏng làm đánh giá chính.** Tự dựng tấn công rồi tự chặn là vòng luẩn quẩn, reviewer sẽ coi nặng hơn cả cherry-pick. Mô phỏng chỉ dùng để *kiểm chứng tính đúng* với ground truth biết trước (xem M3). Đánh giá chính phải trên sandwich thật trên mainnet, lấy mẫu ngẫu nhiên và đăng ký trước (xem M5).

**Tính mới cần làm rõ so với công trình trước.** Phát hiện và ước lượng thiệt hại sandwich đã có nhiều bài: Qin et al. S&P 2022, Torres et al. USENIX Security 2021, Züst 2021, Wang et al. 2022, Heimbach & Wattenhofer 2022. Các bài này ước lượng thiệt hại bằng heuristic hoặc công thức AMM. Điểm mới của mình nằm ở 3 chỗ:
1. Đo counterfactual bằng *replay có xác thực*, không phụ thuộc route: aggregator, multi-hop, Uniswap V3 tick, token có phí chuyển.
2. Có cổng hợp lệ và fail-closed cho ordering confound.
3. Cùng một khung verdict dùng chung cho cả exploit lẫn MEV.

## 2. Giới hạn môi trường cloud (quan trọng)

- Repo là **public**. Không commit tên hay email tác giả, đường dẫn máy cá nhân, RPC key, dữ liệu, hay bản thảo paper.
- Cloud **không có** dữ liệu local (`eval/results/`, `data/`, trace cache, context replay) và **không có** RPC archive. Việc gì cần RPC thì chỉ viết script và test bằng dữ liệu giả; chủ repo sẽ tự chạy script đó trên máy local.
- Việc tự làm trọn được trên cloud: code Go và Python, unit test, và mô phỏng trên chain local không fork (anvil không cần RPC).
- Ngân sách khoảng 100 USD credit. Làm theo từng milestone. Cuối mỗi milestone phải có commit, test pass, rồi dừng lại tóm tắt. Không lan man thăm dò.

## 3. Milestones

### M1: Can thiệp thứ tự trong engine Go

File: `tools/geth-replay/main.go`, vòng `for i, tx := range txs[:*targetIndex+1]`.

- Thêm cờ `-drop-tx <index>` (dùng lặp lại được): bỏ qua giao dịch prefix có index đó.
- Thêm cờ `-order <i,j,...>` (tuỳ chọn, làm sau): đổi thứ tự prefix.
- Mọi giao dịch còn lại giữ nguyên calldata. Đây chính là "giữ cố định input của bên thứ ba", cho khớp với CDE trong paper.
- Nếu replay chạm vào account hoặc slot không có trong proof, phải **fail-closed** và ghi lý do. Engine đã có `-replay-mode discovery` và `-extra-footprint` để lấy thêm state về sau.
- Output bổ sung:
  - `dropped_indices`
  - trạng thái của từng giao dịch prefix sau can thiệp: status, gas, và cờ "khác baseline"
  - danh sách các giao dịch trung gian bị revert hoặc đổi kết quả (ordering confound)
- Test Go: tạo fixture nhỏ tổng hợp gồm 3 giao dịch trên 1 pool giả lập, kiểm tra bỏ giao dịch 0 thì kết quả giao dịch 2 thay đổi đúng.

**Xong khi:** `go test ./...` pass và có test cho các trường hợp drop, fail-closed và confound.

### M2: Sổ thiệt hại cho sandwich (Python)

- Module mới `core/mev/sandwich_harm.py`:
  - Thiệt hại của victim bằng `amountOut_cf - amountOut_obs`, tính theo token đầu ra, lấy từ log `Transfer` gửi tới recipient của victim.
  - Quy đổi USD theo giá tại `b-1`, dùng lại cơ chế định giá có sẵn trong `core/harm/` nếu phù hợp.
- Hàm verdict theo đúng taxonomy hiện có:

  | Kết quả | Điều kiện |
  |---|---|
  | CAUSE | bỏ front-run làm victim nhận thêm ≥ ngưỡng |
  | NO_EFFECT | bỏ giao dịch làm victim không đổi |
  | INCONCLUSIVE(reason) | ordering confound, thiếu state, victim revert vì lý do khác |

- Thêm control:
  - **Placebo:** bỏ một giao dịch prefix không liên quan tới pool đó, phải ra NO_EFFECT.
  - **Backrun-only:** bỏ giao dịch nằm *sau* victim, phải ra NO_EFFECT theo cấu trúc.
- Unit test bằng dữ liệu JSON giả, cùng định dạng output của geth-replay.

**Xong khi:** pytest pass cho mọi nhánh verdict.

### M3: Mô phỏng có ground truth, chạy được hoàn toàn trên cloud

- Dựng chain local bằng anvil không fork, deploy Uniswap V2 (factory, pair, 2 token ERC-20). Cài Foundry nếu cần.
- Sinh tự động N kịch bản có tham số, seed cố định:
  - sandwich cổ điển với độ lớn front-run và slippage của victim thay đổi
  - backrun arbitrage vô hại
  - swap bình thường không bị tấn công
  - sandwich có giao dịch bên thứ ba chen giữa, để tạo ordering confound
- Ground truth: thiệt hại của victim tính bằng công thức `x*y=k`, có phí 0.3%.
- Chạy pipeline (can thiệp drop cộng sổ thiệt hại), so thiệt hại counterfactual với công thức. Sai số phải bằng 0 hoặc chỉ do làm tròn.
- Output: `eval/mev_sim/results.json` (git-ignored) và một bảng tóm tắt.

**Xong khi:** trên toàn bộ kịch bản sandwich ra CAUSE với thiệt hại khớp công thức; backrun và swap thường ra NO_EFFECT; các kịch bản confound được gắn cờ đúng.
**Lưu ý:** đây là kiểm chứng tính đúng, *không phải* kết quả đánh giá chính.

### M4: Lấy dữ liệu sandwich thật (viết script cho máy local chạy)

- Script `eval/mev/acquire_sandwiches.py`, nhận RPC qua biến môi trường, không hard-code:
  - Nguồn nhãn công khai: heuristic kiểu mev-inspect-py (cùng searcher hoặc cùng contract ở 2 phía, cùng pool, victim nằm giữa, hướng swap ngược nhau), hoặc API công khai như ZeroMEV hay EigenPhi nếu truy cập được.
  - Kèm kiểm tra chéo bằng heuristic của chính mình.
- Xuất manifest ứng viên gồm `block`, `frontrun_idx`, `victim_idx`, `backrun_idx`, `pool`, `source`.
- Script dựng context replay cho từng ứng viên, dùng lại pipeline dựng context B2 có sẵn: proof `eth_getProof` tại `b-1` cho prefix `0..victim_idx`. Sandwich thường nằm ở đầu block nên prefix ngắn và proof ít.
- Test bằng dữ liệu RPC giả lập (mock). Không gọi mạng trong test.

### M5: Giao thức chống cherry-pick (viết code và tài liệu, chạy ở local)

- **Lấy mẫu:** chọn ngẫu nhiên K block trong một khoảng thời gian cố định, seed cố định. Lấy *tất cả* sandwich phát hiện được, rồi lấy mẫu N (ví dụ 50–100). **Ghi hash của manifest vào commit trước khi chạy replay.**
- **Báo cáo đủ mẫu số:** số ứng viên, số dựng được context, số replay khớp baseline, số ra verdict, số INCONCLUSIVE theo từng lý do. Tuyệt đối không bỏ case nào.
- **Control đi kèm:** cùng số lượng backrun-arbitrage và swap thường lấy từ chính các block đó.
- **Đo:**
  - coverage, tức tỉ lệ có verdict
  - tỉ lệ CAUSE trên sandwich thật
  - tỉ lệ NO_EFFECT trên control (specificity)
  - thiệt hại USD của victim, so với ước lượng bằng công thức AMM và với nhãn của nguồn công khai
  - tần suất ordering confound
- Script tổng hợp `eval/mev/evaluate.py` xuất JSON, với Wilson CI cho mọi tỉ lệ.

### M6: Kết nối với Stage 1 (tuỳ chọn, nếu còn credit)

- Chấm điểm các sandwich và backrun bằng screener đã đóng băng.
- Cho thấy Stage 1 báo động cả hai loại, còn Stage 2 tách được: sandwich ra CAUSE, backrun ra NO_EFFECT.
- Đây là câu chuyện "phễu 2 lớp" mà paper cần.

## 4. Các lỗi hiện có phải sửa trước hoặc song song (ảnh hưởng mọi hướng)

1. `tools/geth-replay/scoping.go` đang coi `balanceOf(address)` là price selector. Tách nó thành factor riêng hoặc bỏ khỏi danh sách giá.
2. Frame-local chạy lại cả giao dịch từ đầu nhưng không kiểm tra calldata attacker gửi victim có giống baseline không. Phải thêm kiểm tra này. Không khớp thì ra INCONCLUSIVE.
3. Sham control phải thay bằng một giá trị *khác thật* nhưng không liên quan. Isolation phải so hash của log, không chỉ so số lượng log.
4. Trong frame-local, CAUSE_BLOCKED phải kiểm tra frame gây revert thuộc victim chứ không phải token hay bên thứ ba.

## 5. Quy tắc làm việc

- Mỗi milestone đi trên một branch, mở PR, mô tả rõ đã test gì.
- Không sửa kết quả hay số liệu cũ để "cho khớp". Số nào chưa đo thì ghi là chưa đo.
- Test phải chạy được khi không có dữ liệu local. Test nào cần dữ liệu thì `skip` kèm lý do.
- Kết thúc mỗi phiên: cập nhật mục "Trạng thái" bên dưới.

## 6. Trạng thái

| Milestone | Trạng thái | Ghi chú |
|---|---|---|
| M1 | chưa bắt đầu | |
| M2 | chưa bắt đầu | |
| M3 | chưa bắt đầu | |
| M4 | chưa bắt đầu | |
| M5 | chưa bắt đầu | cần RPC, chạy ở local |
| M6 | chưa bắt đầu | tuỳ chọn |
| Sửa lỗi mục 4 | chưa bắt đầu | |
