# Kế hoạch: TraceGuard-DeFi, một khung counterfactual cho exploit và tấn công thứ tự

Tài liệu giao việc cho phiên Claude Code trên cloud. Đọc hết trước khi code.
Đọc thêm `CLAUDE.md` ở gốc repo để nắm cấu trúc và các lỗi đã biết.

> **Thay đổi so với bản trước:** MEV/sandwich **không còn là trọng tâm**, mà là *phần mở rộng* của core idea gốc.
> Bài có đúng **4 RQ**. Ưu tiên cao nhất bây giờ là **RQ3**: sửa các lỗi frame-local rồi chạy lại fixed-20.

## 1. Câu chuyện của bài

**Tên bài:** *TraceGuard-DeFi: Validity-Aware Screening and Counterfactual Replay for DeFi Exploits and Ordering Attacks*

**Core idea (giữ nguyên từ bản thảo gốc).** Việc một giao dịch có hại hay không được quyết định bởi *thiệt hại counterfactual lên victim*, đo bằng replay trên state có xác thực EIP-1186. Không dựa vào hình dạng trace. Có hai thành phần:

- **Stage 1: screener 3 view** (call structure, token flow, economic action), đã hiệu chỉnh, ngưỡng đóng băng theo ngân sách FPR. Dùng để xếp hạng ứng viên.
- **Stage 2: replay counterfactual có cổng hợp lệ.** Chỉ đưa ra verdict khi so sánh được với baseline; không so sánh được thì fail-closed ra INCONCLUSIVE(lý do).

**Khái niệm hợp nhất: comparability confound.** Can thiệp làm thay đổi phần thực thi *không thuộc victim*, khiến thiệt hại counterfactual không quan sát được hoặc không so sánh được. Có hai dạng:

| | Exploit giao thức (bản gốc) | Tấn công thứ tự / sandwich (mở rộng) |
|---|---|---|
| Can thiệp | Cố định giá trị victim đọc: `do_V(F:=v0)` (price pinning, flash suppression, guard restoration) | Bỏ giao dịch khỏi prefix của block: `do(drop tx)` |
| Confound | **Revert confound:** script attacker revert và rollback toàn bộ | **Ordering confound:** giao dịch trung gian đổi kết quả hoặc revert, nonce bị hụt |
| Cơ chế xử lý | Revert-origin attribution, frame-local replay | Báo cáo từng giao dịch trung gian, fail-closed khi thiếu state |
| Điểm triển khai | Triage sau sự cố (chậm được) | Builder trước khi đưa vào block (cần nhanh) |
| Claim | Quy trách nhiệm theo factor | Phát hiện và ngăn chặn **trong block do builder tham gia xây** |

**Không claim:** chặn trên public mempool; chống được mọi kẻ tấn công thích nghi; độ chính xác quy trách nhiệm trên toàn bộ corpus.

## 2. Bốn câu hỏi nghiên cứu

| RQ | Câu hỏi | Nguồn số liệu | Trạng thái |
|---|---|---|---|
| **RQ1** | Screener có xếp hạng được tấn công dưới FPR đóng băng không, và hình dạng trace bị giới hạn tới đâu? (split chuẩn, dịch chuyển thời gian và family, near-negative, ablation) | `eval/e1_*`, đã có trong bản thảo | Có số |
| **RQ2** | Replay có xác thực có tái hiện đúng lịch sử và đủ nhanh cho builder không? | Fidelity: Nethermind 20/20 (đã có). Latency: `geth-replay -lean` | Có số lean (W1) |
| **RQ3** | Dưới revert confound, can thiệp có phạm vi, revert-origin và frame-local cho ra bao nhiêu verdict hợp lệ trên fixed-20? | `tools/geth-replay/cmd/framelocal`, `eval/rq3/fixed20_cases.json` | **Phải sửa lỗi và chạy lại** |
| **RQ4** | Can thiệp thứ tự có phát hiện và ngăn được sandwich mà không chặn nhầm arbitrage không? | Mô phỏng `eval/mev_sim/` (ground truth), cộng 10–30 case mainnet (shadow mode) | Mô phỏng có kết quả sơ bộ |

## 3. Giới hạn môi trường cloud (quan trọng)

- Repo là **public**. Không commit tên hay email tác giả, đường dẫn máy cá nhân, RPC key, dữ liệu, hay bản thảo paper.
- Cloud **không có** dữ liệu local (`eval/results/`, context replay) và **không có** RPC. Việc gì cần dữ liệu thì viết code, test bằng fixture tổng hợp, rồi **đưa lệnh PowerShell** để chủ repo chạy trên Windows và dán output lại.
- Lệnh cho chủ repo phải chạy từ gốc repo, xuất output vào `.cache/` (git-ignored), và in ra một bảng tóm tắt ngắn để dán lại.
- Context replay trên máy chủ repo nằm ở `eval/results/m4/b2-contexts-fresh/<case>/`.
- Ngân sách khoảng 100 USD credit. Mỗi phiên một work item. Cuối phiên: commit, test pass, mở PR, cập nhật bảng trạng thái, dừng lại tóm tắt.

## 4. Work items (theo thứ tự ưu tiên)

### W1: RQ2, chế độ `-lean` và latency (PR #2)

- Đã có `-lean`. Việc còn lại là chủ repo chạy lệnh đo.
- **Xong khi:** base-lean có `acceptance_gate=true` trên cả 3 context, output < 1 MB, có số `target_evm` ở chế độ lean.

### W2: RQ3, sửa frame-local rồi chạy lại fixed-20 (ưu tiên cao nhất)

Runner chuẩn là `tools/geth-replay/cmd/framelocal` (bản đã bỏ `balanceOf` khỏi selector giá). Các file frame-local ở `tools/geth-replay/*.go` cấp trên và `tools/geth-replay-framelocal/` là bản cũ. Hợp nhất lại, hoặc ghi rõ là legacy và không dùng cho RQ3.

Sửa trong `cmd/framelocal`:
1. **Giữ cố định input của attacker:** so calldata, value và caller của frame victim đích với baseline. Khác nhau thì ra `INCONCLUSIVE(attacker_input_changed)`.
2. **Sham thật:** thay bằng giá trị *khác* giá trị quan sát, nhưng ở một read không liên quan (ví dụ getter giá của pool không nằm trong harm frame). Thiệt hại phải không đổi.
3. **Isolation:** so hash của log (address, topics, data), không chỉ so số lượng log.
4. **CAUSE_BLOCKED** chỉ khi frame gốc gây revert thuộc victim `V` và xảy ra *sau* lần đọc bị can thiệp (theo thứ tự thời gian, không theo độ sâu).
5. **Consumption:** lần đọc bị can thiệp phải nằm *bên trong* harm frame đích.
6. **Ngưỡng verdict** khớp paper: `CAUSE` khi `L' <= L_min`; `PARTIAL` khi `L_min < L' <= (1-ρ)L` với ρ = 0.1; ngược lại `NO_EFFECT`. Ghi rõ thiệt hại theo từng token; không cộng lượng thô của các token khác nhau.

Runner mới `eval/rq3/run_fixed20.py`:
- Đọc `eval/rq3/fixed20_cases.json` (victim/attacker đã đóng băng).
- Với mỗi case chạy: whole-tx có read-site scoping, frame-local, isolation, sham. Dùng chế độ output gọn.
- Ghi SHA-256 của manifest đầu vào vào output trước khi chạy.
- Xuất `.cache/rq3/summary.json` gồm verdict từng case, lý do INCONCLUSIVE, phân bố revert-origin, tỉ lệ pass của isolation/sham, kèm Wilson CI. In bảng tóm tắt.
- Unit test bằng fixture tổng hợp.

**Xong khi:** `go test ./...` và pytest pass; có lệnh PowerShell để chủ repo chạy fixed-20 và dán bảng tóm tắt.

### W3: RQ4 phần mô phỏng (PR #3, `eval/mev_sim/`)

Đã có: seed 7, 200 slot, chặn 227/227 sandwich, chặn nhầm 7/409 benign. Việc còn lại:
1. Rebase PR #3 lên `main` mới. Giải quyết conflict ở bảng trạng thái trong tài liệu này.
2. **Phân tích 7 ca chặn nhầm:** victim revert khi bỏ front-run. Theo taxonomy, đây phải là ordering confound, ra DEFAULT, *không phải* EXCLUDE. Sửa policy nếu đang coi là EXCLUDE, báo cáo lại số.
3. **Kẻ tấn công thích nghi**, mỗi kiểu báo tỉ lệ chặn riêng: chia nhỏ front-run, đổi địa chỉ, đi qua router, multi-pool, chèn giao dịch mồi.
4. **Baseline heuristic hình dạng:** chặn mọi mẫu front-victim-back. So tỉ lệ chặn nhầm với TraceGuard.
5. Chạy nhiều seed (ví dụ 5 seed), báo trung bình và CI.
6. Latency trong mô phỏng là thời gian RPC của anvil, **không dùng cho claim latency**. Claim latency lấy từ W1.

### W4: RQ4 phần mainnet nhỏ (cloud viết code, chủ repo chạy)

- `eval/mev/acquire_sandwiches.py`: heuristic kiểu mev-inspect trên K block chọn ngẫu nhiên, seed cố định. Kèm backrun-arbitrage và swap thường trong cùng block làm control.
- Dựng context `eth_getProof` cho prefix `0..victim_idx`, dùng lại pipeline dựng context B2.
- **Commit hash manifest trước khi replay.** Mục tiêu 10–30 sandwich. Báo cáo đủ mẫu số.
- `eval/mev/evaluate.py`: verdict, USD tránh được, tỉ lệ chặn nhầm trên control, tần suất ordering confound, Wilson CI.

### W5: Script vẽ hình

`eval/plots/` sinh mọi hình trong paper từ JSON kết quả. Mỗi hình một hàm, xuất PDF vector, font 8–9 pt, rộng 0.48 hoặc 0.95 `\textwidth`:

1. `fig_prcurve.pdf` (RQ1): đã có, giữ.
2. `fig_latency.pdf` (RQ2): so sánh latency full-trace và lean (bar hoặc CDF).
3. `fig_rq3_verdicts.pdf` (RQ3): verdict whole-tx và frame-local xếp chồng, kèm lý do INCONCLUSIVE.
4. `fig_rq4_sim.pdf` (RQ4): tỉ lệ chặn và chặn nhầm theo kiểu tấn công, so TraceGuard với heuristic hình dạng.

## 5. Bảng đối chiếu claim với bằng chứng

| Claim | Bằng chứng bắt buộc | Nếu chưa có |
|---|---|---|
| Screener xếp hạng dưới FPR đóng băng | RQ1 (đã có) | — |
| Replay tái hiện đúng lịch sử | RQ2 fidelity (đã có) | — |
| Đủ nhanh cho builder | `target_evm` ở chế độ lean (W1) | Bỏ khỏi abstract |
| Frame-local tăng số verdict hợp lệ | RQ3 sau khi sửa (W2) | Báo cáo coverage thấp một cách trung thực |
| Ngăn sandwich, không chặn nhầm arbitrage | W3 mô phỏng cộng W4 mainnet | Chỉ nói "trên mô phỏng" |
| Chống kẻ tấn công thích nghi | W3 mục 3 | Ghi là limitation |
| Không cherry-pick | Hash manifest commit trước khi chạy (W2, W4) | Không nộp số đó |

## 6. Quy tắc làm việc

- Mỗi work item một branch, mở PR, mô tả rõ đã test gì.
- Không sửa số liệu cũ để "cho khớp". Số nào chưa đo thì ghi là chưa đo.
- Test phải chạy được khi không có dữ liệu local; test nào cần dữ liệu thì `skip` kèm lý do.
- Cuối mỗi phiên: cập nhật bảng trạng thái bên dưới.

## 7. Trạng thái

| Work item | Trạng thái | Ghi chú |
|---|---|---|
| M1 `-drop-tx` | xong, đã merge (PR #1) | Chạy trên 3 context thật: comparable đúng; exchangeissuance bị nonce gap nên ra incomparable, đúng mong đợi |
| W1 `-lean` | xong (PR #2) | Đo trên 3 context thật (Windows): base-lean `acceptance_gate=true` 3/3; output 0.07–0.15 MB (full-trace 490–662 MB); `target_evm` lean 6.1–10.6 ms, `evm_replay` 12.9–17.7 ms (full-trace 1543–1625 ms); `context_load` 27–50 ms đo riêng. Số latency giả định builder đã có state trong bộ nhớ. |
| W2 RQ3 sửa frame-local | chưa bắt đầu | **ưu tiên cao nhất** |
| W3 RQ4 mô phỏng | PR #3, kết quả sơ bộ | seed 7, 200 slot: chặn 227/227 sandwich, chặn nhầm 7/409 benign (victim revert khi bỏ front-run); latency là thời gian RPC của anvil; chưa có pool V3 |
| W4 RQ4 mainnet | chưa bắt đầu | cần RPC, chạy ở local |
| W5 hình | chưa bắt đầu | |
