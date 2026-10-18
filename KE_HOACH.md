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

> **macOS — cách nhanh nhất:** mở Terminal, dán lệnh `cd ~/Downloads; [ -f cw_scanner.zip ] && unzip -oq cw_scanner.zip; bash cw_scanner/chay_web.command` rồi Enter. Lệnh này tự giải nén, tự cài và mở giao diện web. Cần Python 3.10+ từ python.org (Python có sẵn của Apple là 3.9, không dùng được).
>
> **Windows — cách nhanh nhất:** sau khi cài Python, nhấp đúp `chay_web.bat`. File này tự làm Bước 2 (lần đầu) rồi mở giao diện web (Bước 5). Bỏ qua Bước 2–4 nếu dùng cách này.

### Bước 2 — Tạo môi trường ảo và cài vnstock
```bash
cd cw_scanner
python -m venv .venv
# Windows:      .venv\Scripts\activate
# macOS/Linux:  source .venv/bin/activate
pip install -U --extra-index-url https://vnstocks.com/api/packages vnstock
pip show vnstock      # kiểm tra: Version phải >= 5.0 (đã chạy thử với 5.0.3 và 5.1.0)
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

Thị trường đóng cửa 14:45, nên đặt chạy **15:15 từ thứ Hai đến thứ Sáu**. Chương trình dùng đường dẫn tuyệt đối nên chạy từ đâu cũng được.

### Windows — Task Scheduler
1. Mở **Task Scheduler** → **Create Basic Task** → đặt tên "Quet CW".
2. Trigger: **Weekly**, tick Mon–Fri, giờ 15:15.
3. Action: **Start a program**
   - Program: `C:\duong_dan\cw_scanner\.venv\Scripts\python.exe`
   - Arguments: `cw_scanner.py`
   - Start in: `C:\duong_dan\cw_scanner`

### macOS / Linux — cron
Chạy `crontab -e` rồi thêm 1 dòng (giờ theo múi giờ máy, đặt máy về giờ Việt Nam):
```
15 15 * * 1-5  /duong_dan/cw_scanner/.venv/bin/python /duong_dan/cw_scanner/cw_scanner.py >> /duong_dan/cw_scanner/log.txt 2>&1
```
Kết quả mỗi ngày nằm trong `ket_qua/`, nhật ký trong `log.txt`.

---

## Phần 6. Giới hạn của mô hình — BẮT BUỘC đọc

1. **σ lịch sử ≠ biến động tương lai.** Đây là nguồn sai số lớn nhất. Một CW "rẻ 40%" có thể chỉ vì TCPH dùng σ thấp hơn, hoặc năm qua cổ phiếu có biến cố lớn khiến σ lịch sử bị phóng đại.
2. **Bỏ qua cổ tức.** Mô hình hơi đánh giá cao CW khi cổ phiếu sắp trả cổ tức tiền (TCPH sẽ điều chỉnh giá thực hiện/tỷ lệ sau sự kiện).
3. **Giá thanh toán là trung bình 5 phiên**, không phải giá 1 ngày — mô hình bỏ qua chi tiết này (sai số nhỏ).
4. **Chưa tính phí và thuế** (phí môi giới tùy công ty, thuế TNCN 0,1% khi bán) — với CW giá vài trăm đồng, bước giá 10đ và phí ăn mòn lợi nhuận đáng kể.
5. **Thanh khoản chỉ đo trong 1 phiên.** Chạy trước giờ giao dịch thì KL = 0 cho mọi mã, và sổ lệnh có thể trống → giá mua rơi về giá khớp/tham chiếu (cột *Nguồn giá mua* ghi rõ). Giá chào bán có thể cao hơn giá khớp hơn 10% (CTCB2619 ngày 16/10/2026: khớp 980đ, chào bán 1.100đ), nên kết quả từ bản này **không so trực tiếp** với file CSV cũ định giá theo giá khớp.
6. **Dữ liệu từ API không chính thức** (Vietcap, KBS) có thể đổi định dạng hoặc lỗi tạm thời. Khi chạy thử, một số API của Vietcap trả lỗi 500 từ vài phút đến hơn 20 phút. Nếu bảng giá Vietcap lỗi, lần quét đó thất bại và báo lỗi — chờ rồi chạy lại.
7. Đây là **công cụ sàng lọc**, không phải khuyến nghị đầu tư. Luôn kiểm tra lại điều khoản CW trên website TCPH/HOSE trước khi mua.

---

## Phần 7. Hướng mở rộng (khi đã quen)
- ~~**Biến động ngầm định (IV)**~~ — đã làm: cột IV % và IV − HV (giải ngược từ giá mua).
- **Gửi thông báo** qua Telegram/email khi có CW mới đạt "NÊN XEM XÉT".
- **Kiểm chứng lại (backtest):** lưu file kết quả hằng ngày rồi đối chiếu sau 1–3 tháng xem nhóm "NÊN XEM XÉT" có thực sự tốt hơn không.
