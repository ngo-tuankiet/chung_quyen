# Kế hoạch: Định giá chứng quyền (CW) bằng Black-Scholes

Mục tiêu: một chương trình Python **chạy tự động mỗi ngày**, quét **toàn bộ** chứng quyền đang niêm yết trên HOSE, **đánh dấu CW mới phát hành**, tính **giá hợp lý** bằng Black-Scholes và đưa ra kết luận đơn giản: **NÊN XEM XÉT / THEO DÕI / BỎ QUA**, kèm lý do bằng tiếng Việt dễ hiểu.

Thư mục dự án:

```
cw_scanner/
├── KE_HOACH.md          ← tài liệu này
├── .env                 ← nơi bạn dán API key vnstock (KHÔNG chia sẻ file này)
├── cw_scanner.py        ← chương trình chính (~200 dòng, chú thích tiếng Việt từng phần)
├── web.py               ← giao diện web: bấm nút để quét, xem bảng kết quả
├── test_cw_scanner.py   ← kiểm tra công thức có tính đúng không
├── requirements.txt     ← phiên bản vnstock được ghim (đổi số ở đây khi muốn nâng cấp)
├── requirements-dev.txt ← pytest, chỉ cần khi sửa code
├── danh_muc.py          ← danh mục CW đang nắm + cảnh báo Discord (trang 💼 Danh mục trên web)
├── danh_muc.csv         ← (tự sinh, không đưa lên git) các lệnh mua/bán bạn nhập
├── chay_quet_tu_dong.sh, kiem_tra_danh_muc.sh, cai_lich_quet.sh ← chạy tự động bằng launchd (Phần 5)
├── .env.example         ← mẫu file .env (VNSTOCK_API_KEY, DISCORD_WEBHOOK_URL)
├── cw_da_biet.txt       ← (tự sinh) danh sách CW đã thấy, dùng để phát hiện CW mới
└── ket_qua/
    ├── cw_YYYY-MM-DD.csv        ← (tự sinh) kết quả mỗi ngày, mở bằng Excel
    └── gia_dinh_YYYY-MM-DD.json ← (tự sinh) giả định đã dùng: r, số phiên đo σ, 4 ngưỡng, quy tắc chọn giá mua, nguồn dữ liệu, bản vnstock
```

---

## Phần 1. Kiến thức nền (đọc 5 phút)

### Chứng quyền là gì?
Chứng quyền có bảo đảm (CW) do công ty chứng khoán phát hành. Mua CW = mua **quyền** hưởng phần chênh lệch nếu giá cổ phiếu cơ sở **lên cao hơn giá thực hiện** vào ngày đáo hạn. Nếu không lên đủ, CW về 0 — bạn mất toàn bộ tiền mua CW (nhưng không mất thêm).

Ví dụ tên mã `CVPB2615`: **C** = chứng quyền, **VPB** = cổ phiếu cơ sở, **26** = năm phát hành, **15** = số thứ tự.

| Thuật ngữ | Ký hiệu | Ý nghĩa |
|---|---|---|
| Giá cổ phiếu cơ sở | S | Giá hiện tại của cổ phiếu (VPB) |
| Giá thực hiện | K | Mức giá CS phải vượt qua thì CW mới có lãi |
| Tỷ lệ chuyển đổi | n | `2:1` nghĩa là 2 CW tương ứng 1 cổ phiếu |
| Ngày đáo hạn | T | Ngày CW hết hiệu lực; giao dịch cuối cùng trước đó 2 phiên |
| Giá thanh toán | — | Trung bình giá đóng cửa CS 5 phiên trước ngày đáo hạn |

CW ở Việt Nam là **kiểu châu Âu** (chỉ thực hiện lúc đáo hạn) và **thanh toán bằng tiền** — đúng loại mà công thức Black-Scholes mô tả.

**Tiền nhận được lúc đáo hạn cho mỗi CW** = `max(Giá thanh toán − K, 0) / n`

### Black-Scholes nói gì?
Công thức trả lời câu hỏi: *"Với giá CS hiện tại, giá thực hiện, thời gian còn lại, lãi suất và mức dao động thường thấy của cổ phiếu, quyền này **đáng giá** bao nhiêu?"* Cần 5 đầu vào:

| Đầu vào | Lấy ở đâu | Ghi chú |
|---|---|---|
| S | Bảng giá (giá khớp gần nhất) | |
| K | Bảng giá (điều khoản CW) | |
| T | (Ngày đáo hạn − hôm nay) / 365 | tính bằng năm |
| r | Bạn tự đặt trong cấu hình | lãi suất phi rủi ro, ví dụ lợi suất TPCP 1 năm |
| σ | Tự tính từ lịch sử giá 1 năm của CS | **đầu vào quan trọng nhất và khó đoán nhất** |

```
d1 = [ ln(S/K) + (r + σ²/2)·T ] / (σ·√T)
d2 = d1 − σ·√T
Giá quyền (cho 1 cổ phiếu) = S·N(d1) − K·e^(−rT)·N(d2)
Giá hợp lý 1 CW            = Giá quyền / n
```
`N(x)` là hàm phân phối chuẩn (Excel: `NORM.S.DIST(x, TRUE)`).

**σ (biến động lịch sử)** = độ lệch chuẩn của `ln(giá hôm nay / giá hôm qua)` trong 250 phiên gần nhất × √250.

### Ví dụ tính tay (dữ liệu thật ngày 16/10/2026)
`CVPB2615`: S = 24.500, K = 22.605, n = 1,5863, còn 123 ngày, r = 4%, σ(VPB) = 32,8%, giá CW trên thị trường = 1.240đ.

1. T = 123/365 = 0,3370 năm
2. d1 = [ln(24500/22605) + (0,04 + 0,328²/2)·0,337] / (0,328·√0,337) = **0,5888** → N(d1) = 0,7220
3. d2 = 0,5888 − 0,328·√0,337 = **0,3984** → N(d2) = 0,6548
4. Giá quyền = 24500·0,7220 − 22605·e^(−0,04·0,337)·0,6548 ≈ **3.085đ**
5. Giá hợp lý 1 CW = 3.085 / 1,5863 ≈ **1.944đ**
6. So sánh: thị trường 1.240đ → **rẻ hơn mô hình 36%**
7. Điểm hòa vốn lúc đáo hạn = K + giá CW × n = 22.605 + 1.240 × 1,5863 = 24.572đ → VPB chỉ cần tăng **0,3%**

(Bạn có thể nhập đúng các bước trên vào Excel để tự kiểm chứng chương trình.)

---

## Phần 2. Luồng xử lý của chương trình

```
[1] vnstock: danh sách mã CW ──► [2] Bảng giá VCI: điều khoản + giá CW + giá CS
                                          │
[3] vnstock: lịch sử giá 1 năm của CS ──► σ
                                          │
                          [4] Black-Scholes → giá hợp lý
                                          │
                          [5] 4 tiêu chí → NÊN XEM XÉT / THEO DÕI / BỎ QUA
                                          │
              [6] So với cw_da_biet.txt → đánh dấu "MỚI" → lưu CSV + in màn hình
```

| Bước | Hàm trong `cw_scanner.py` | Việc làm |
|---|---|---|
| 0 | `doc_env()` + `login()` | Đọc API key từ file `.env` và đăng nhập vnstock (lỗi thì quét tiếp bằng gói Khách) |
| 1 | `Listing(source="KBS").all_covered_warrant()` | Lấy ~300+ mã CW đang niêm yết |
| 2 | `lay_bang_gia()` | 1 lần gọi lấy giá thực hiện, tỷ lệ, ngày đáo hạn, mã CS, TCPH, giá khớp, khối lượng khớp, khối lượng niêm yết và sổ lệnh 3 giá mua/bán tốt nhất |
| 3 | `bien_dong_lich_su()` | Mỗi mã CS 1 lần gọi (chỉ ~20 mã CS dù có 300+ CW) |
| 4 | `gia_mua()` + `black_scholes_call()` + `bien_dong_ngam_dinh()` | Giá mua = giá chào bán thấp nhất; công thức ở Phần 1; IV giải ngược từ giá mua |
| 5 | `danh_gia()` | Chấm 4 tiêu chí (Phần 4) |
| 6 | `main()` | Phát hiện CW mới, sắp xếp, lưu file |

**Vì sao bước 2 không dùng vnstock?** Hàm `Trading().price_board()` của vnstock (bản 4.0.9) **cố tình xóa** các cột `exercise_price`, `exercise_ratio`, `maturity_date`, `underlying_symbol` — đúng những cột ta cần. Vì vậy chương trình gọi thẳng API bảng giá của Vietcap (chính API mà vnstock dùng bên trong). Lịch sử giá và danh sách mã vẫn lấy qua vnstock, dùng nguồn KBS (nguồn mặc định của vnstock) vì API lịch sử của VCI từng lỗi liên tục hơn 20 phút trong lúc chạy thử.

**Cách phát hiện CW mới:** bảng giá không có ngày phát hành, nên mỗi lần chạy chương trình lưu toàn bộ mã vào `cw_da_biet.txt`. Lần sau, mã nào chưa có trong file = **MỚI**. Lần chạy đầu tiên chỉ lưu danh sách, không đánh dấu gì.

---

## Phần 3. Cài đặt từng bước

### Bước 1 — Cài Python
Tải Python 3.10 trở lên tại python.org. Trên Windows nhớ tick **"Add Python to PATH"**.

> **macOS — cách nhanh nhất:** mở Terminal, dán lệnh `cd ~; [ -f ~/Downloads/cw_scanner.zip ] && unzip -oq ~/Downloads/cw_scanner.zip; bash ~/cw_scanner/chay_web.command` rồi Enter. Lệnh này tự giải nén, tự cài và mở giao diện web. Cần Python 3.10+ từ python.org (Python có sẵn của Apple là 3.9, không dùng được). Thư mục dự án nằm ở `~/cw_scanner` (không để trong Downloads/Documents nếu muốn quét tự động, xem Phần 5).
>
> **Windows — cách nhanh nhất:** sau khi cài Python, nhấp đúp `chay_web.bat`. File này tự làm Bước 2 (lần đầu) rồi mở giao diện web (Bước 5). Bỏ qua Bước 2–4 nếu dùng cách này.

### Bước 2 — Tạo môi trường ảo và cài vnstock
```bash
cd cw_scanner
python -m venv .venv
# Windows:      .venv\Scripts\activate
# macOS/Linux:  source .venv/bin/activate
pip install --extra-index-url https://vnstocks.com/api/packages -r requirements.txt   # vnstock ghim đúng 5.1.0
pip show vnstock      # kiểm tra: Version: 5.1.0
```
Chương trình **không cần thư viện nào khác** (pandas đi kèm vnstock; phần còn lại dùng thư viện có sẵn của Python).

### Bước 2b — Nhập API key vào file `.env`
Mở file `.env` bằng Notepad / TextEdit / VS Code và dán key sau dấu `=`:
```
VNSTOCK_API_KEY=khoa_cua_ban_o_day
```
⚠️ Key phải nằm **ngay sau dấu `=`, trên cùng một dòng**. Dán xuống dòng dưới thì chương trình không đọc được.

Mỗi lần quét, chương trình đọc file này và đăng nhập vnstock (`login`). Mỗi lần quét dùng khoảng 21 lượt gọi.
- **Không có key / đăng nhập lỗi** → gói Khách: 10 lượt/phút, 100/giờ, 300/ngày, 1.000/tháng, lịch sử tối đa 365 ngày. Chương trình tự chờ khi hết lượt trong phút, nên vẫn quét xong, chỉ chậm hơn (2–3 phút).
- **Có key** → hạn mức theo gói tài khoản của bạn (cao hơn gói Khách).
- Nếu thấy **"Đã đạt số thiết bị tối đa của cấp tài khoản"**: gói của bạn giới hạn số máy được dùng key. Vào trang tài khoản trên vnstocks.com để gỡ thiết bị cũ không dùng nữa, rồi quét lại.
File `.gitignore` đã chặn `.env` để không lỡ đưa key lên GitHub. Nếu tệp bị ẩn trên macOS/Linux (tên bắt đầu bằng dấu chấm), nhấn `Cmd+Shift+.` trong Finder để hiện.

> ⚠️ **Lưu ý bảo mật vnstock** (kiểm tra ngày 17/10/2026):
> - Trên PyPI, `vnstock` và `vnai` đang ở trạng thái **"quarantined"** (bị cách ly, `pip install vnstock` thông thường sẽ báo lỗi). Hãy cài theo đúng lệnh ở trên từ trang chính thức vnstocks.com.
> - Theo CHANGELOG chính thức, các bản **trước 4.0.9** mỗi lần `import vnstock` đã tự ghi một khối chỉ dẫn vào file cấu hình của trợ lý AI (`AGENTS.md` của dự án và file toàn cục của Claude Code, Codex, Antigravity). Nếu từng dùng bản cũ: **nâng cấp lên bản mới nhất (5.x)** và mở các file như `~/.claude/CLAUDE.md`, `AGENTS.md` để xóa khối đó nếu còn.

### Bước 3 — Kiểm tra công thức
```bash
python test_cw_scanner.py
```
Thấy `OK - công thức đúng` là được.

#### Dành cho người sửa code
Cài một lần các công cụ (pytest, ruff, black; phiên bản ghim trong `requirements-dev.txt`) và bật kiểm tra trước mỗi commit:
```bash
.venv/bin/python -m pip install -r requirements-dev.txt
git config core.hooksPath .githooks
```
- `python -m pytest -q`: chạy mọi ca kiểm tra (có ca tính tay). `python -m ruff check .`: lỗi code (thêm `--fix` để tự sửa phần an toàn).
  `python -m black .`: định dạng code. Cấu hình (dòng tối đa 120 ký tự, cú pháp phải chạy được từ Python 3.10) nằm trong `pyproject.toml`.
- Hook `.githooks/pre-commit` chặn commit khi: ruff báo lỗi, code chưa định dạng, test trượt, hoặc file đã stage chứa một giá trị trong `.env`
  (key vnstock, webhook Discord) hay chuỗi dạng webhook Discord thật. Chỉ khi khẩn cấp mới bỏ qua: `git commit --no-verify`.

### Bước 4 — Chạy thử
```bash
python cw_scanner.py
```
Đã đăng nhập thì nhanh; gói Khách mất khoảng 2–3 phút vì phải chờ hạn mức 10 lượt/phút (chương trình tự chờ, không cần làm gì).

### Bước 5 — Giao diện web (tùy chọn, dễ dùng hơn)
```bash
python web.py
```
Trình duyệt tự mở `http://localhost:8000`. Trang hiển thị:
- Trạng thái API key (đã nhập trong `.env` hay chưa — không bao giờ hiện key).
- Nút **Quét ngay** (chờ 1–3 phút).
- Mục **Nhật ký lần quét gần nhất**: mọi thông báo của chương trình; tự mở ra khi có cảnh báo `[!]` (ví dụ key bị từ chối).
- Bảng **CW mới phát hành**, bảng **Nên xem xét**, và bảng **Tất cả** có ô tìm kiếm (gõ VPB, SSI…).
- Đường dẫn **❓ Hướng dẫn sử dụng** ở đầu mọi trang: giải thích cho người mới (chứng quyền là gì, cách dùng 5 bước,
  ý nghĩa từng cột, cách đọc trang phân tích, 5 câu tự hỏi trước khi mua, câu hỏi thường gặp). Rê chuột lên tiêu đề cột để xem giải thích ngắn.
- Trang **🆕 CW sắp ra mắt**: các CW HOSE đã chấp thuận niêm yết nhưng chưa giao dịch (lấy từ hsx.vn, lưu lại mỗi lần quét),
  kèm giá hợp lý dự kiến để so sánh khi CW lên sàn.
- **Bấm vào một mã CW** để mở trang phân tích: tóm tắt dễ hiểu, 4 tiêu chí đạt/không đạt, giá trị nội tại / thời gian,
  biểu đồ giá cổ phiếu cơ sở 1 năm kèm đường giá thực hiện và hòa vốn (rê chuột xem giá từng ngày), bảng **lãi/lỗ khi đáo hạn**
  theo từng kịch bản (kèm ví dụ 10 triệu đồng), biến động ngầm định so với lịch sử, và so sánh các CW khác cùng mã cơ sở.
  Trang phân tích **tính lại mọi con số theo giá trực tiếp** lúc mở trang (giá cổ phiếu cơ sở + giá chào bán, chờ tối đa 5 giây; σ và lãi suất
  lấy từ lần quét). Không tải được thì dùng số lúc quét và báo đỏ ở đầu trang. Mục **Rủi ro với số tiền của bạn**: nhập số tiền (triệu đồng)
  để xem số CW mua được, giá trị cổ phiếu cơ sở tương đương đang nắm, mức giảm làm mất toàn bộ tiền, ngày giao dịch cuối, hòa vốn sau phí
  (`PHI_GIAO_DICH` 0,15%) và thuế (`THUE_BAN` 0,1%) - hai mức này là giả định, chỉnh ở đầu `cw_scanner.py` theo công ty chứng khoán của bạn.
  Mục **IV theo thời gian**: biểu đồ IV từng ngày từ lúc CW lên sàn (giá CW tải qua vnstock 1 lần/ngày, giá cổ phiếu đã điều chỉnh quyền) kèm đường HV 1 năm và trung vị IV các CW cùng mã. IV thường cao lúc mới phát hành rồi giảm dần; đáng chú ý khi IV xuống thấp hẳn dưới HV và trung vị cùng mã (ví dụ CVPB2615: khoảng 37% lúc lên sàn tháng 7 → 15,6% ngày 19/10/2026).
- Nếu máy chủ dữ liệu lỗi, thông báo lỗi màu đỏ hiện ngay trên trang — chờ vài phút rồi bấm lại.

Trang chỉ mở cho máy của bạn (127.0.0.1). Tắt bằng `Ctrl+C` trong cửa sổ dòng lệnh. Lịch tự động ở Phần 5 vẫn chạy `cw_scanner.py`; mở web lúc nào cũng thấy kết quả mới nhất.

---

## Phần 4. Đọc kết quả

### Ví dụ màn hình (chạy thật ngày 17/10/2026)
```
Tìm thấy 328 chứng quyền đang niêm yết.

Đã định giá 328 CW: BỎ QUA 233, THEO DÕI 66, NÊN XEM XÉT 29

=== NÊN XEM XÉT ===
   Mã CW Mã CS  Ngày còn lại  Giá CW  Giá hợp lý  Đắt/rẻ %  CS tăng % để hòa vốn  Đòn bẩy  Lý do
CVPB2615   VPB           123    1240        1944     -36.2                   0.3      9.0  đạt cả 4 tiêu chí
CTCB2619   TCB           121     980        1068      -8.2                   5.2      7.3  đạt cả 4 tiêu chí
...
```

### Ý nghĩa từng cột trong file CSV
| Cột | Ý nghĩa | Đọc thế nào |
|---|---|---|
| Mới | `MỚI` nếu lần trước chưa có | Chú ý CW mới — thường có thời gian còn lại dài |
| TCPH | Tổ chức phát hành | Cũng là bên tạo lập thị trường cho CW đó |
| Ngày còn lại | Đến ngày đáo hạn | Càng ít, CW mất giá theo thời gian càng nhanh |
| Giá CW | Giá khớp gần nhất | VND cho 1 CW; chỉ để tham khảo |
| Giá mua / Nguồn giá mua | Giá chào bán thấp nhất trong sổ lệnh lúc quét (`ask`); sổ lệnh trống thì giá `khớp`, chưa khớp thì giá `tham chiếu` | **Mọi chỉ số định giá bên dưới tính theo giá này** — giá bạn thực sự phải trả |
| Giá hợp lý | Giá Black-Scholes | VND cho 1 CW |
| Đắt/rẻ % | (Giá mua / Giá hợp lý − 1) × 100 | **Âm = rẻ hơn mô hình**, dương = đắt hơn. Chỉ để tham khảo, tiêu chí dùng IV − HV |
| CS tăng % để hòa vốn | (K + Giá mua × n) / S − 1 | CS phải tăng bấy nhiêu đến lúc đáo hạn mới hòa vốn |
| Đòn bẩy | delta × S / (Giá mua × n) | CS tăng 1% thì CW tăng khoảng bấy nhiêu % (và giảm cũng vậy) |
| Biến động %/năm | σ lịch sử (HV) của cổ phiếu cơ sở | Càng cao, CW càng "đáng giá" theo mô hình |
| IV % | Biến động ngầm định giải ngược từ Giá mua | Mức dao động mà giá CW đang "giả định" |
| IV − HV | (IV − σ lịch sử) × 100, điểm % | **Âm = rẻ**, dương = đắt. So sánh được giữa CW gần và xa giá thực hiện; bảng xếp theo cột này và đây là tiêu chí 2 (≤ +3 điểm) |
| Ghi chú IV | Lý do không giải được IV | Thường là *giá mua dưới mức tối thiểu S − K·e^(−rT)*: chữ "rẻ" khi đó chủ yếu đến từ giả định r và σ, không chắc là món hời |
| r % / Số phiên σ | Lãi suất và số phiên thực tế đã dùng đo σ | Đủ để tự tính lại từng dòng trong Excel |
| Ngày GD cuối | Ngày giao dịch cuối cùng (từ bảng giá) | Sau ngày này không bán được nữa, chỉ chờ nhận tiền theo giá trung bình 5 phiên |
| IV cùng mã % / Cảnh báo | Trung vị IV các CW khác cùng mã CS; cảnh báo khi IV < 50% trung vị đó (`MIN_IV_SO_VOI_CUNG_MA`, cần ≥ 3 CW) | Chỉ cảnh báo, không đổi kết luận. Ví dụ CVPB2608/CVPB2615 (ACBS) ngày 19/10/2026: IV 14-16% so với trung vị 47% - giá do tổ chức phát hành tự bán ra (kể cả đợt phát hành bổ sung 5 triệu CVPB2608 giá 760 đ ngày 02-06/10), không chắc là món hời |
| KL khớp | Khối lượng khớp trong phiên | Thấp = khó mua/bán đúng giá |
| Đánh giá / Lý do | Kết luận + tiêu chí bị trượt | |

### 4 tiêu chí đánh giá (chỉnh ở đầu file `cw_scanner.py`)
| Tiêu chí | Mặc định | Vì sao |
|---|---|---|
| `MIN_NGAY_CON_LAI` | ≥ 60 ngày | Gần đáo hạn, giá trị thời gian mất rất nhanh |
| `MAX_IV_TRU_HV` | IV − HV ≤ +3 điểm (0,03) | Không trả cho mức dao động cao hơn hẳn 1 năm qua (xem bên dưới) |
| `MAX_TANG_DE_HOA_VON` | CS tăng ≤ 15% | Mục tiêu hòa vốn phải thực tế |
| `MIN_KHOI_LUONG` | ≥ 10.000 CW/phiên | Đủ thanh khoản để thoát lệnh |

- Đạt cả 4 → **NÊN XEM XÉT** (vẫn phải tự phân tích cổ phiếu cơ sở!)
- Trượt 1 → **THEO DÕI**
- Trượt từ 2 → **BỎ QUA**

**Vì sao tiêu chí 2 dùng IV − HV thay cho "đắt hơn giá hợp lý ≤ 10%"** (đổi ngày 18/10/2026). Cùng mức đắt 10% về giá tương đương những mức IV rất khác nhau tùy CW nằm trong hay ngoài tiền. Số liệu từ lần quét thật ngày 18/10/2026 (sổ lệnh cuối phiên 16/10), 68 CW đạt 3 tiêu chí còn lại:

| Nhóm theo giá CS / giá thực hiện | "Đắt 10%" tương đương (điểm IV), trung vị | Khoảng |
|---|---|---|
| Ngoài tiền (< 0,95) | +1,6 | +0,9 … +2,5 |
| Quanh tiền (0,95–1,05) | +3,3 | +1,6 … +5,1 |
| Trong tiền (1,05–1,15) | +6,0 | +4,4 … +9,5 |
| Sâu trong tiền (> 1,15) | +14,3 | +10,8 … +26,2 |

- Quy tắc cũ khắt khe với CW ngoài tiền nhưng thả lỏng với CW sâu trong tiền (vd CHDB2608: IV − HV = +23 điểm nhưng chỉ "đắt 8,4%" nên vẫn được NÊN XEM XÉT).
- **+3 điểm** giữ đúng mức chặt cũ ở CW quanh tiền. Kiểm tra tay: S = K = 30.000, 120 ngày, σ = 30% → giá × 1,1 cho IV ≈ 33,3% (vì giá CW quanh tiền ≈ 0,4 × S × σ × √T, tỉ lệ thuận với σ). Có trong `test_cw_scanner.py`.
- Trên dữ liệu trên, NÊN XEM XÉT giảm 25 → 20: loại CHDB2608, CVHM2604, CHDB2615, CMWG2627, CTCB2621 (IV − HV từ +3,4 đến +23 điểm), không thêm mã nào.
- CW có giá mua dưới mức tối thiểu S − K·e^(−rT) (không giải được IV) được tính là **đạt** tiêu chí 2 (rẻ hơn mọi mức dao động) nhưng luôn kèm cảnh báo; giá cao bất thường (không giải được IV) tính là trượt.
- Ngưỡng chọn từ dữ liệu 1 ngày: nên xem lại sau 2–4 tuần dữ liệu. Thị trường thường định giá CW cao hơn HV (trung vị IV − HV của 68 CW trên là +8,8 điểm), nên +3 điểm chỉ giữ khoảng 30% CW rẻ nhất về biến động.

---

## Phần 5. Tự động hóa

Thị trường đóng cửa 14:45, nên đặt chạy **14:00 từ thứ Hai đến thứ Sáu**. Chương trình dùng đường dẫn tuyệt đối nên chạy từ đâu cũng được.

### Windows — Task Scheduler
1. Mở **Task Scheduler** → **Create Basic Task** → đặt tên "Quet CW".
2. Trigger: **Weekly**, tick Mon–Fri, giờ 14:00.
3. Action: **Start a program**
   - Program: `C:\duong_dan\cw_scanner\.venv\Scripts\python.exe`
   - Arguments: `cw_scanner.py`
   - Start in: `C:\duong_dan\cw_scanner`

### macOS — launchd (khuyên dùng)
Đặt thư mục dự án **ngoài** `~/Downloads`, `~/Documents`, `~/Desktop` (ví dụ `~/cw_scanner`): macOS chặn tác vụ chạy nền đọc các thư mục đó
(lỗi "Operation not permitted", launchd báo mã thoát 78). Rồi chạy một lần:
```bash
bash ~/cw_scanner/cai_lich_quet.sh
```
- Quét lúc 14:00 thứ Hai–Sáu theo giờ của máy (trước phiên ATC: giá trong phiên, chưa phải giá đóng cửa) (đặt máy về giờ Việt Nam). Máy ngủ lúc 14:00 thì launchd chạy bù khi máy thức dậy.
- Mỗi lần chạy `chay_quet_tu_dong.sh` quét xong thì sao lưu `ket_qua/` và `cw_da_biet.txt` sang `~/cw_scanner_sao_luu/` (không bao giờ xóa bản cũ).
- Nhật ký trong `log.txt`. Ngày nghỉ lễ / Tết (bảng giá Vietcap vẫn ghi `tradingDate` của phiên trước) thì bỏ qua, không quét, không gửi báo cáo.
- Quét lỗi (vd máy chủ vnstock không phản hồi) thì tự thử lại tối đa 2 lần, cách nhau 5 phút. Vẫn lỗi thì báo cáo 14:00 vẫn gửi, dòng đầu ghi
  "⚠ Quét hôm nay lỗi (lý do); số liệu bên dưới là của lần quét dd/mm HH:MM" (file `ket_qua/` mới nhất).
- Gỡ lịch: `bash ~/cw_scanner/cai_lich_quet.sh go`.

### Linux — cron
Chạy `crontab -e` rồi thêm 1 dòng (giờ theo múi giờ máy, đặt máy về giờ Việt Nam):
```
15 15 * * 1-5  /bin/bash /duong_dan/cw_scanner/chay_quet_tu_dong.sh >> /duong_dan/cw_scanner/log.txt 2>&1
```
Kết quả mỗi ngày nằm trong `ket_qua/` (bản sao lưu trong `~/cw_scanner_sao_luu/`), nhật ký trong `log.txt`.

### Danh mục và cảnh báo Discord
1. Trang **💼 Danh mục** trên web: nhập từng lệnh mua/bán (mã, ngày, số lượng, giá khớp; chốt lời/cắt lỗ riêng nếu muốn). Lệnh lưu trong
   `danh_muc.csv` (ghi an toàn: file tạm rồi đổi tên, bản trước ở `danh_muc.csv.bak`; mỗi ngày sao lưu 1 bản vào `~/cw_scanner_sao_luu/`).
   Giá vốn bình quân (đã gồm phí mua) như app công ty chứng khoán; lãi/lỗ tính **nếu bán ngay** ở giá chờ mua tốt nhất sau phí và thuế.
2. Tạo webhook: Discord → Server Settings → Integrations → Webhooks → New Webhook → Copy Webhook URL, dán vào `.env`:
   `DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...` (xem `.env.example`). Không có dòng này thì cảnh báo chỉ hiện trên web.
3. `bash ~/cw_scanner/cai_lich_quet.sh` cài cả lịch kiểm tra danh mục **mỗi 5 phút** (chỉ trong giờ khớp lệnh 9:15–11:30, 13:00–14:45 thứ Hai–Sáu,
   ngoài giờ thoát ngay, không gọi mạng; ngày nghỉ lễ cũng không gửi gì) và một lần sau lần quét 14:00.

Cảnh báo (ngưỡng ở đầu `danh_muc.py`): còn ≤ 20 ngày tới ngày giao dịch cuối; cổ phiếu cơ sở cao hơn giá thực hiện ≤ 3% hoặc đã dưới;
lãi nếu bán ngay ≥ +50% / lỗ ≥ 30% (đặt riêng được cho từng lệnh mua); sổ lệnh không có giá chờ mua; IV < 50% trung vị CW cùng mã;
khối lượng niêm yết tăng (tổ chức phát hành bán thêm); CW lệch ≥ ±15% so với mức lẽ ra theo cổ phiếu cơ sở (từ lệnh mua gần nhất); **CW đắt, cân nhắc chuyển sang cổ phiếu**: bán ngay ≥ giá trị theo mô hình × 1,15 và IV theo giá chờ mua > trung vị IV các CW cùng mã (tin này có ghi tiền thu về và vốn mua cổ phiếu đủ số / theo delta, lô 100; cổ phiếu không có giới hạn lỗ như CW). **Chỉ gửi khi cảnh báo vừa xuất hiện**, và mỗi loại cảnh báo của mỗi mã **tối đa 1 tin/ngày**
(giá dao động quanh ngưỡng thì không gửi lặp; trạng thái trong `canh_bao_da_gui.json`). Tin cảnh báo chỉ có mã, %, giá và lý do (trừ cảnh báo "CW đắt" và báo cáo 14:00 có số tiền, theo yêu cầu dùng riêng).

---

## Phần 6. Giới hạn của mô hình — BẮT BUỘC đọc

1. **σ lịch sử ≠ biến động tương lai.** Đây là nguồn sai số lớn nhất. Một CW "rẻ 40%" có thể chỉ vì TCPH dùng σ thấp hơn, hoặc năm qua cổ phiếu có biến cố lớn khiến σ lịch sử bị phóng đại.
2. **Cổ tức không cần đưa vào mô hình.** Khi cổ phiếu cơ sở trả cổ tức tiền, cổ tức bằng cổ phiếu hay thưởng cổ phiếu, TCPH điều chỉnh giá thực hiện và tỷ lệ chuyển đổi theo hệ số giá tham chiếu tại ngày GDKHQ (TT 107/2016 Điều 10, nay là TT 122/2025). Ví dụ VPB năm 2026: cổ tức tiền 500 đ (GDKHQ 15/05, hệ số 0,982548) và cổ tức cổ phiếu 26,04% (GDKHQ 24/09, hệ số 0,793165) đưa CVPB2608 từ 30.000 đ, tỷ lệ 2:1 về 23.379 đ, tỷ lệ 1,5586:1. Lịch sử giá lấy từ KBS cũng đã được điều chỉnh theo các sự kiện này, nên σ không bị phóng đại bởi khoảng trống giá.
3. **Giá thanh toán là trung bình 5 phiên**, không phải giá 1 ngày — mô hình bỏ qua chi tiết này (sai số nhỏ). CW đáo hạn giữa tháng 2/2027 có 5 phiên này nằm sát kỳ nghỉ Tết Nguyên đán (mùng 1 Tết ≈ 06/02/2027): xem lịch nghỉ của HOSE.
4. **4 tiêu chí chưa tính phí và thuế** (phí môi giới tùy công ty, thuế TNCN 0,1% khi bán). Mục "Rủi ro với số tiền của bạn" ở trang phân tích có tính, theo `PHI_GIAO_DICH` và `THUE_BAN` ở đầu `cw_scanner.py` (giả định, chỉnh theo công ty chứng khoán của bạn). Với CW giá vài trăm đồng, bước giá 10đ và phí ăn mòn lợi nhuận đáng kể.
5. **Thanh khoản chỉ đo trong 1 phiên.** Chạy trước giờ giao dịch thì KL = 0 cho mọi mã, và sổ lệnh có thể trống → giá mua rơi về giá khớp/tham chiếu (cột *Nguồn giá mua* ghi rõ). Giá chào bán có thể cao hơn giá khớp hơn 10% (CTCB2619 ngày 16/10/2026: khớp 980đ, chào bán 1.100đ), nên kết quả từ bản này **không so trực tiếp** với file CSV cũ định giá theo giá khớp.
6. **Dữ liệu từ API không chính thức** (Vietcap, KBS) có thể đổi định dạng hoặc lỗi tạm thời. Khi chạy thử, một số API của Vietcap trả lỗi 500 từ vài phút đến hơn 20 phút. Nếu bảng giá Vietcap lỗi, lần quét đó thất bại và báo lỗi — chờ rồi chạy lại.
7. **Giá CW do tổ chức phát hành chi phối.** TCPH là bên bán chính và không bắt buộc yết giá theo giá trị lý thuyết; Việt Nam lại không cho bán khống nên không ai kéo giá về giá hợp lý. Giá có thể nằm dưới giá hợp lý rất lâu, ví dụ ACBS với CVPB2608/CVPB2615: IV từ khoảng 41% lúc lên sàn xuống 12–14% vào tháng 10/2026, kể cả khi ACBS phát hành bổ sung 5 triệu CVPB2608 giá 760 đ. Phần "rẻ" chỉ chắc thu về được nếu giữ đến đáo hạn.
8. Đây là **công cụ sàng lọc**, không phải khuyến nghị đầu tư. Luôn kiểm tra lại điều khoản CW trên website TCPH/HOSE trước khi mua.

---

## Phần 7. Hướng mở rộng (khi đã quen)
- ~~**Biến động ngầm định (IV)**~~ — đã làm: cột IV % và IV − HV (giải ngược từ giá mua).
- **Gửi thông báo** qua Telegram/email khi có CW mới đạt "NÊN XEM XÉT".
- **Kiểm chứng lại (backtest):** lưu file kết quả hằng ngày rồi đối chiếu sau 1–3 tháng xem nhóm "NÊN XEM XÉT" có thực sự tốt hơn không.

---

## Phần 8. Theo dõi quỹ ETF (`etf.py`, `chiet_khau.py`)

**Mục tiêu** (chốt 22/10/2026): tìm ETF đang **giao dịch dưới NAV** để lướt vài ngày–vài tuần, mỗi lệnh dưới 50 triệu. So theo
(a) chiết khấu so với NAV, (b) cùng một chỉ số thì quỹ nào rẻ hơn, (d) quỹ tụt so với chỉ số — tách phần do quỹ bám kém và phần do giá rời NAV.
"Rẻ" chỉ có nghĩa khi so với NAV của chính quỹ: giá mỗi CCQ (9.360 đ hay 33.980 đ) không nói gì về đắt/rẻ.

**Vì sao nến ETF giật và gap** (điều tra 22/10/2026, chi tiết + nguồn: `ket_qua/bao_cao_nen_etf_2026-10-22.md`)
1. Sổ lệnh mỏng: giá mở/đóng cửa thường do 1–2 lô 100 CCQ quyết định, kể cả ở ATO/ATC (vd FUEKIVFS 01/10 −6,5%, 02/10 +6,9%, mỗi lần 100 CCQ,
   chỉ số chỉ −0,9% và −1,7%). Thanh khoản càng thấp càng gap nhiều (tương quan hạng −0,92); độ lệch thường tự đảo chiều phiên sau.
   Giá đóng cửa của quỹ mỏng hay bằng đúng giá chào bán tốt nhất → bị lệch lên.
2. Nhiều phiên không khớp: giá tham chiếu giữ giá cũ, lần khớp sau chỉ đi tối đa ±7% → 1 cây nến gánh biến động nhiều tuần.
3. Giá rời NAV (premium/discount) rồi quay lại. 4. Lỗi dữ liệu KBS (thiếu phiên thật, vd 20/06 và 26/09/2025 ở 14 quỹ) — nhỏ, ~1% nến lạ.
Không phải do chia cổ tức (21 quỹ không có sự kiện nào; E1VFVN30 tái đầu tư và mô phỏng VN30-TRI).

**Chạy**
- `.venv/bin/python etf.py --no-discord`: tính, lưu `ket_qua/etf_YYYY-MM-DD.csv` và lịch sử NAV `ket_qua/nav_etf_YYYY-MM-DD.csv.gz`,
  in báo cáo (bỏ `--no-discord` để gửi Discord). Báo cáo mở đầu bằng mục **💰 Chiết khấu so với NAV** và **📉 Quỹ tụt so với chỉ số**.
- Tự động: `bash cai_lich_quet.sh` cài lịch `vn.cw-scanner.etf` (`chay_etf_tu_dong.sh`, **15:30 thứ Hai–Sáu**, ngày nghỉ bỏ qua, lỗi thì thử lại
  2 lần rồi báo lỗi lên Discord) và `vn.cw-scanner.chiet-khau` (`kiem_tra_chiet_khau.sh`, **mỗi 5 phút trong giờ khớp lệnh**).
- Lần chạy 5 phút ghi iNAV, giá chào bán, giá khớp của 21 quỹ vào `ket_qua/inav_YYYY-MM-DD.csv` (không nguồn nào lưu sẵn lịch sử iNAV).
  **Cảnh báo Discord trong phiên đang tắt** (`BAT_CANH_BAO_TRONG_PHIEN = False` trong `chiet_khau.py`): chỉ bật sau khi file iNAV của phiên đầu
  tiên cho thấy iNAV của SSI thực sự cập nhật trong phiên — iNAV đứng yên mà giá chạy thì "chiết khấu" là ảo. Khi bật: mỗi quỹ tối đa 1 tin/ngày
  (trạng thái trong `canh_bao_chiet_khau.json`).
- Web: trang **📊 ETF** (`/etf`): bảng chiết khấu (xếp theo lãi ròng), bảng chỉ số, bảng toàn bộ quỹ; bấm một quỹ để xem chênh lệch giá/NAV 1 năm
  và giá + MA50/MA200.

**Nguồn dữ liệu** (đều là API không chính thức; nguồn từng quỹ, giờ công bố NAV: `ket_qua/bao_cao_nguon_nav_etf_2026-10-22.md`)
- **SSI iBoard** (`iboard-query.ssi.com.vn`, 1 lần gọi cả rổ): iNAV (NAV ước tính trong phiên), NAV T-1 chính thức (`prevINAV`), 3 bước giá mua/bán.
- **Vietcap IQ** (`iq.vietcap.com.vn`): NAV/CCQ hằng ngày từ 09/2024 của 20 quỹ (thiếu FUEPHVNS), trễ ~2 phiên. Nhãn ngày lỗi, làm sạch thế này:
  - `lam_sach_nav`: NAV thứ Sáu ghi vào Chủ nhật (dòng thứ Sáu lặp số thứ Năm) → dòng Chủ nhật thay thứ Sáu; một ngày có 2 số khác nhau
    (số sau thường là NAV phiên kế tiếp, vd FUEMAV30 07/10/2026) → bỏ hẳn ngày đó, không đoán.
  - `bo_nav_loi`: tỷ lệ NAV / chỉ số ngày đó lệch trung vị 5 phiên quanh nó > 0,5% → bỏ (vd FUESSVFL 07/04/2026 thật ra là NAV 08/04,
    E1VFVN30 dòng 16/11/2025 là NAV thứ Hai). Đo trên NAV thật 19 quỹ: bắt đủ lỗi đã biết, chỉ bỏ ~20/9.000 ngày. Ngày cuối chuỗi lệch
    thì bỏ tạm tới khi có phiên sau.
  - NAV một quỹ dừng cập nhật quá 5 phiên → cảnh báo "NAV Vietcap IQ dừng ở ...".
- vnstock (nguồn **VCI**): danh sách ETF, giá ngày của quỹ và chỉ số. Giá quỹ dùng VCI thay KBS vì KBS thiếu phiên thật. Giá chỉ số: điểm chia 1.000,
  **phải lấy `floating=6`** (mặc định làm tròn 2 số lẻ: VN30 1.892,98 chỉ còn 1,89 → sai lợi nhuận ngày). VNMID trong vnstock tên là VNMIDCAP.
- Bảng giá Vietcap: giá, giá trị giao dịch, khối ngoại, số CCQ lưu hành hôm nay.
- vnstock và VNDirect không có NAV của ETF; văn bản NAV gốc trên HOSE phần lớn là ảnh scan (cần OCR) nên chưa dùng.

**Chiết khấu (chiet_khau.py)**
- **CK (chiết khấu mua được)** = giá chào bán tốt nhất / iNAV − 1. Dùng giá chào bán (mua được ngay), không dùng giá khớp cuối: quỹ ít giao dịch có giá
  khớp cũ nhiều tuần (cột **Phiên chưa khớp**), "chiết khấu" theo giá khớp đó là ảo (22/10/2026: FUEBFVND −6,6%, FUEKIVFS −3,1% đều ảo).
- **Lãi ròng nếu về NAV** = iNAV × (1 − phí − thuế) / (giá chào bán × (1 + phí)) − 1, phí 0,15%, thuế bán 0,1% (`PHI_GIAO_DICH`, `THUE_BAN`).
  Ví dụ tính tay: chào bán 9.700, iNAV 10.000 → 9.975 / 9.714,55 − 1 = +2,68%. Chiết khấu 2% chỉ cho lãi ròng +1,63%.
- **Đạt ngưỡng** (🟢): lãi ròng ≥ 2% (`NGUONG_LAI_RONG`) và tổng giá trị chào bán ở các mức giá đạt lãi ròng đó ≥ 5 triệu (`MIN_GIA_TRI_CHAO_BAN`).
- **Thường lệch (TV 1N)** = trung vị (giá đóng cửa / NAV − 1) 1 năm của chính quỹ, chỉ các phiên có khớp; **Sâu nhất 1N** = mức thấp nhất.
  Quỹ lúc nào cũng chiết khấu thì CK âm chưa chắc là rẻ bất thường: 22/10/2026 FUEIP100 đạt ngưỡng (CK −5,6%, lãi ròng +5,5%) nhưng thường lệch −4,6%.
  Chỉ có lời khi giá quay về sát NAV; người kéo giá về NAV là thành viên lập quỹ (lô 100.000 CCQ), họ không bị buộc làm, nên quỹ mỏng có thể chiết khấu rất lâu.
- **NAV−CS 1N** = lợi nhuận NAV 1 năm − của chỉ số mô phỏng (điểm %), cùng ngày gốc (hôm nay − 12 tháng) và tới hôm nay bằng iNAV
  (không có iNAV thì tới ngày NAV cuối): âm nhiều = quỹ bám chỉ số kém (điểm xấu, không phải cơ hội).
- **Quỹ tụt so với chỉ số** (d): mức tụt của giá ≈ NAV−CS + thay đổi của giá/NAV (giá/NAV đầu kỳ lấy đúng mốc của lợi nhuận giá). Ví dụ 22/10/2026
  FUEVN100 giá −9,4 điểm so VN100 nhưng NAV +0,8 điểm: quỹ bám chỉ số tốt, giá tụt vì 1 năm trước cao hơn NAV 11,2% nay về −0,4% — không phải
  cơ hội. Quỹ có giá khớp cũ thì không in giá/NAV hiện tại ("—") và ghi số phiên chưa khớp.

**Các chỉ số kỹ thuật** (ngưỡng ở đầu `etf.py`)
- **1T / 3T / 6T / 1N**: lợi nhuận theo giá từ phiên gần nhất trước mốc (hôm nay lùi 1/3/6/12 tháng lịch) tới phiên cuối. Quỹ niêm yết sau mốc: "—".
- **so CS 1N** (web): lợi nhuận giá 1 năm của quỹ − của chỉ số. Chỉ số VN30, VNDIAMOND… là chỉ số **giá** (không cộng cổ tức) còn quỹ nhận cổ tức,
  nên quỹ bám tốt thường cao hơn chỉ số một chút. E1VFVN30 mô phỏng VN30-TRI (có cổ tức) nên số này của nó lệch dương.
- **Xu hướng**: Tăng khi giá và MA50 cùng trên MA200, Giảm khi cùng dưới, còn lại Đi ngang. MA tính trên các phiên có khớp lệnh; chưa đủ 200 phiên: trống.
- **RSI14**: RSI của Wilder (trung bình tăng/giảm 14 phiên, làm mượt (TB cũ × 13 + phiên mới) / 14). Trên 70: tăng nóng; dưới 30: bị bán quá mức.
- **Biến động năm**: độ lệch chuẩn lợi suất log ngày × √250 (như HV của CW). **Sâu nhất 1N / Cách đỉnh**: mức giảm lớn nhất từ đỉnh và khoảng cách tới đỉnh trong 1 năm.
- **GTGD TB20**: giá trị giao dịch trung bình 20 phiên gần nhất (tỷ đồng), phiên không khớp tính 0. **Khối ngoại**: mua − bán trong phiên (tỷ đồng).
- **CCQ lưu hành**: số chứng chỉ quỹ. Tăng = nhà đầu tư lớn góp rổ cổ phiếu lấy CCQ (tiền vào quỹ), giảm = hoàn mua (tiền ra).
- **Phiên khớp**: số phiên có khớp lệnh trong 1 năm. Dưới 200 thì cảnh báo: RSI/MA/biến động kém tin cậy. Với quỹ mỏng, đừng dùng giá mở cửa và
  râu nến làm tín hiệu "chạm đáy" — thường chỉ là 1 lô nhỏ.

**Cấu hình**: `QUY_THEO_CHI_SO` (quỹ → chỉ số; FUEVN50G mô phỏng VN50 GROWTH của HOSE nhưng vnstock chưa có lịch sử chỉ số này nên đang so tạm
với VNINDEX và có cảnh báo); `PHI_QUAN_LY` (phí quản lý %/năm theo website / bản cáo bạch, tra 22/10/2026; FUEFCV50, FUEIP100, FUEABVND chưa có số chắc chắn).

**Giới hạn**: API không chính thức, có thể đổi bất cứ lúc nào; NAV Vietcap trễ ~2 phiên; sổ lệnh sau 14:45 là lệnh còn lại sau ATC (chênh lệch giá
mua–bán có thể rộng hơn trong phiên); chênh lệch giá/NAV trong quá khứ tính bằng giá đóng cửa (quỹ mỏng: bị lệch lên, nhiễu).

**Kiểm chứng ngưỡng 2% với lịch sử** (`kiem_chung_chiet_khau.py`, chạy 22/10/2026; chỉ đọc dữ liệu, không gửi Discord, không đổi ngưỡng đang chạy)
- Chạy: `.venv/bin/python kiem_chung_chiet_khau.py` → `ket_qua/kiem_chung_chiet_khau_YYYY-MM-DD.md` (bảng theo nhóm thanh khoản và theo quỹ,
  giả định, giới hạn) và `ket_qua/kiem_chung_chiet_khau_su_kien_YYYY-MM-DD.csv` (từng lệnh: ngày, giá, chênh lệch, lãi — truy lại được từng số).
- Dữ liệu: NAV Vietcap IQ 10/09/2024–21/10/2026 làm sạch bằng `lam_sach_nav` + `bo_nav_loi` (chỉ số VCI `floating=6`), giá ngày VCI chỉ phiên có
  khớp, 20 quỹ (FUEPHVNS không có NAV). Danh sách quỹ là quỹ đang niêm yết hôm nay (quỹ đã hủy niêm yết không có trong mẫu).
- Tín hiệu phiên T: `lai_rong_neu_ve_nav(giá đóng cửa T, NAV T) ≥ 2%`. Mua rồi bán ở giá đóng cửa sau N = 1/5/10/20 phiên (quỹ không khớp: chờ phiên
  khớp kế tiếp, giá cũ không mua/bán được), lãi sau phí 0,15% × 2 và thuế bán 0,1%. Lệnh độc lập: mỗi quỹ giữ 1 vị thế mỗi lúc.
  - Kịch bản **A** (mua ngay ở giá đóng cửa T, coi iNAV lúc ATC ≈ NAV T): cận lạc quan. Kịch bản **B** (mua phiên có khớp kế tiếp; lúc đó NAV T
    đã công bố — NAV T-1 trên SSI — nên không cần iNAV, không lookahead): kịch bản chính.
  - **Vượt NAV** = (1 + lãi) / (1 + lợi nhuận NAV cùng kỳ) − 1: phần lãi nhờ chênh lệch thu hẹp, sau phí, bỏ phần thị trường lên/xuống.
    Nền (mua ở mọi phiên) có vượt NAV −0,4% ở mọi quỹ = đúng chi phí khứ hồi (kiểm chéo công thức).
- Kết quả (trung vị; n = số lệnh độc lập):

  | Nhóm (GTGD TB cả kỳ) | B, N=5: n · lãi · vượt NAV | B, N=20: n · lãi · vượt NAV | A, N=20: vượt NAV |
  |---|---|---|---|
  | Cao ≥ 1 tỷ (có tín hiệu: FUEVN100, FUEMAV30, FUEVFVND) | 12 · +1,5% · −0,2% | 7 · +6,1% · +0,7% | +3,0% |
  | Vừa 0,1–1 tỷ (7 quỹ) | 37 · +1,0% · −0,2% | 21 · +6,2% · +0,6% | +2,6% |
  | Mỏng < 0,1 tỷ (5 quỹ, chủ yếu FUEFCV50, FUEIP100) | 143 · +0,1% · −0,1% | 54 · +0,6% · +0,1% | +2,0% |

- **Kết luận: không nên tin ngưỡng 2% tuyệt đối như một tín hiệu mua.**
  1. Lãi danh nghĩa đẹp của quỹ thanh khoản cao/vừa (+6%/20 phiên) gần hết là do thị trường: tín hiệu dồn vào 04–07/2025 (đợt hồi sau cú sập
     tháng 4, quỹ giao dịch dưới NAV trong khi NAV tăng): ở N ≥ 5 chỉ có 6 (nhóm cao) và 9 (nhóm vừa) tháng khác nhau có lệnh. Bỏ phần thị trường thì kịch bản B chỉ còn
     −0,2%…+0,7% — xấp xỉ 0 sau phí. Ví dụ tính tay FUEVN100 16/07/2025: lãi +17,6% nhưng NAV +14,1%, phần nhờ chiết khấu thu hẹp chỉ +3,1%.
  2. Quỹ mỏng chiết khấu thường trực (FUEFCV50 trung vị −8,4%, FUEIP100 −7,2%): 95% và 80% số phiên "đạt ngưỡng", vượt NAV ≈ 0 hoặc âm —
     ngưỡng tuyệt đối vô nghĩa với 2 quỹ này, và chúng chiếm ~3/4 số lệnh.
  3. Chênh lệch giữa A và B cho thấy phần lớn độ lệch ở giá đóng cửa tự đảo chiều ngay phiên sau: chỉ có lời nếu mua được **đúng lúc** đang chiết
     khấu, ở giá chào bán thật. Lịch sử không có sổ lệnh/iNAV nên chưa biết lúc đó có đủ hàng (≥ 5 triệu) hay không; giá đóng cửa quỹ mỏng thường
     chỉ là 1 lô 100 CCQ, và bán ở giá đóng cửa là lạc quan.
  4. Mẫu nhỏ: chỉ FUEVN100, FUESSV30, FUESSV50, FUEDCMID, FUEFCV50, FUEIP100 có ≥ 10 lệnh độc lập ở một kỳ N nào đó (chủ yếu N=1); các quỹ còn
     lại (FUEABVND, FUEKIVFS… với vượt NAV +2…+8%) chỉ 1–7 lệnh, giá 1 lô — không đủ kết luận.
- **Thử ngưỡng tương đối** (22/10/2026, `.venv/bin/python kiem_chung_chiet_khau.py tuong_doi` → `ket_qua/kiem_chung_chiet_khau_tuong_doi_*.md/.csv`,
  cùng dữ liệu và cách mua/bán; công thức người dùng chốt trước khi xem kết quả):
  - Tín hiệu phiên T: `lai_rong_neu_ve_nav(giá đóng cửa T, NAV T × (1 + m))` ≥ 2%, m = trung vị chênh lệch giá/NAV của 60 phiên có giá và NAV
    gần nhất **trước T** (`CUA_SO_TRUNG_VI`; chưa đủ 60 phiên → không tín hiệu, mất ~3 tháng đầu). Tức là "về mức thường lệch của chính quỹ" thay
    "về NAV"; đã bao hàm điều kiện lệch dưới m ≥ ~2,2–2,4 điểm nên không thêm ngưỡng X riêng.
  - Kết quả kịch bản B (trung vị; n lệnh độc lập · số tháng · vượt NAV; nền vượt NAV −0,4% = chi phí khứ hồi):

    | Nhóm | B, N=5: tuyệt đối → tương đối | B, N=20: tuyệt đối → tương đối | A, N=5 tương đối |
    |---|---|---|---|
    | Cao ≥ 1 tỷ | 12 · 6 · −0,2% → 18 · 10 · −0,2% | 7 · 6 · +0,7% → 8 · 7 · +0,1% | +0,1% |
    | Vừa 0,1–1 tỷ | 37 · 9 · −0,2% → 54 · 16 · −0,2% | 21 · 9 · +0,6% → 31 · 14 · +0,2% | +1,1% |
    | Mỏng < 0,1 tỷ | 143 · 26 · −0,1% → 64 · 20 · −0,5% | 54 · 24 · +0,1% → 30 · 18 · −0,8% | +2,2% |
    | FUEFCV50 (CL TV kỳ −8,4%) | 72 · 26 · −0,6% → 30 · 17 · −0,6% | 23 · 23 · −0,8% → 14 · 14 · −0,7% | +0,8% |
    | FUEIP100 (CL TV kỳ −7,2%) | 61 · 26 · −0,1% → 29 · 15 · −1,4% | 21 · 21 · −0,1% → 12 · 12 · −1,4% | +3,6% |

  - **Kết luận: ngưỡng tương đối không tốt hơn — không thay ngưỡng 2% tuyệt đối bằng nó.**
    1. Kịch bản B (không lookahead): vượt NAV vẫn ≈ 0 sau phí (−0,2%…+0,2% nhóm cao/vừa ở N ≥ 5), N=20 còn kém tuyệt đối. Tín hiệu trải ra nhiều tháng hơn
       (nhóm cao 10 tháng, vừa 16 tháng; ~40% lệnh còn ở 04–07/2025) nên lãi danh nghĩa giảm (vừa, N=20: +6,2% → +2,1%) — khẳng định lãi của ngưỡng
       tuyệt đối chủ yếu là thị trường.
    2. FUEFCV50/FUEIP100: tín hiệu tương đối bỏ được khoảng một nửa số lệnh "chiết khấu thường trực", nhưng lệnh còn lại vẫn lỗ so với NAV ở B
       (−0,6%, −1,4%) trong khi A dương (+0,8%, +3,6%): độ lệch thêm so với mức thường là giá đóng cửa 1 lô, tự đảo chiều ngay phiên sau
       (FUEIP100 trung vị CL tín hiệu −8,8% → CL lúc mua −8,1%) — không mua được ở đó nếu chờ NAV chính thức.
    3. Khoảng cách A–B lặp lại ở mọi nhóm: phần lời (nếu có) chỉ nằm ở việc mua **đúng lúc trong phiên** với giá chào bán thật — cần
       `ket_qua/inav_*.csv` mới kiểm được. Mẫu nhóm cao vẫn nhỏ (8–18 lệnh).
- Việc tiếp (chưa làm, cần người dùng chọn): giữ `BAT_CANH_BAO_TRONG_PHIEN = False` và ngưỡng 2%; để `ket_qua/inav_*.csv` tích lũy vài tuần rồi
  kiểm kịch bản A bằng giá chào bán và iNAV thật trong phiên (cả ngưỡng tuyệt đối lẫn tương đối).

Chấm điểm theo P/E chỉ số đã bỏ (người dùng không chọn tiêu chí "chỉ số rẻ"); P/E, P/B của 10 chỉ số có ở VNDirect
(dữ liệu trước 2024 có dấu hiệu lookahead).
