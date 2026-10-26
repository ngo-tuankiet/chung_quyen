---
name: financial-data-integrity
description: Các bẫy dữ liệu ĐÃ GẶP THẬT trong cw_scanner (vnstock KBS/VCI, bảng giá Vietcap, NAV Vietcap IQ, iNAV SSI, giá thô HOSE), kèm cách phát hiện và cách code đang xử lý. Đọc TRƯỚC khi lấy, làm sạch, ghép hay so sánh dữ liệu giá/NAV/chỉ số/điều khoản CW, viết backtest hoặc script kiem_chung_*, thêm nguồn dữ liệu mới, đổi nguồn (KBS ↔ VCI), hoặc khi một con số trông lạ (lợi nhuận ngày nhảy vọt, chiết khấu sâu bất thường, K/giá CS lệch, gap giả). Dùng cả khi người dùng chỉ hỏi "sao số này kỳ vậy" về CW hay ETF.
---

# Toàn vẹn dữ liệu tài chính — cw_scanner

Mỗi mục dưới đây là lỗi đã gặp trên dữ liệu thật, không phải lý thuyết. Gặp triệu chứng giống thì dùng lại cách xử lý đã có,
đừng viết cách mới. Gặp lỗi mới thì **dừng và báo người dùng** (AGENTS.md mục 8), rồi thêm vào đây sau khi đã xử lý.
Số liệu chi tiết: `KE_HOACH.md` Phần 6, 7b, 8 và các báo cáo `ket_qua/*.md` được nhắc ở từng mục.
Bẫy chung cho mọi dự án tài chính Việt Nam (BCTC, ghi DB, đồng thuận CTCK…): skill toàn máy `vn-finance-data`.

Nguyên tắc chung khi làm sạch: **bỏ dòng nghi ngờ, không đoán số thay thế**, và ghi lại đã bỏ bao nhiêu dòng (vào cảnh báo/báo cáo).
Ở ranh giới gọi API, lỗi của một mã thì bỏ mã đó và ghi cảnh báo, không nuốt lỗi cả lần chạy.

## 1. Chỉ số vnstock (VCI): điểm chia 1.000, làm tròn 2 số lẻ
- **Triệu chứng:** VN30 1.892,98 điểm về thành `1.89`, nên lợi nhuận ngày của chỉ số chỉ đi theo bậc 0,5%.
- **Phát hiện:** giá đóng cửa của chỉ số có ≤ 2 chữ số thập phân, hoặc khoảng 1–2 thay vì vài trăm/nghìn.
- **Xử lý:** `lay_gia_dong_cua(ma, so_ngay, "VCI", floating=6)` (`etf.py` `lay_du_lieu`); thang điểm là `HE_SO_CHI_SO = 1000`.
  Chỉ số chỉ có ở nguồn VCI. Tên khác HOSE: VNMID trong vnstock là `VNMIDCAP` (`TEN_TRONG_VNSTOCK`). VN50 GROWTH chưa có lịch sử trong vnstock.

## 2. vnstock KBS thiếu phiên thật và có nến sai (ETF)
- **Triệu chứng** (`ket_qua/bao_cao_nen_etf_2026-10-22.md`): thiếu 36 phiên có giao dịch thật. Ngày 20/06/2025 và 26/09/2025 thiếu ở 14 quỹ,
  04/04/2025 thiếu ở 4 quỹ, 16–17/06/2026 thiếu ở FUEMITEC và FUEVN50G; ngoài ra có 16 nến mà giá đóng cửa nằm ngoài khoảng cao–thấp.
  Vì thiếu 04/04/2025, KBS cho FUEVFVND ngày 08/04/2025 "−8,55%" (vượt cả giá sàn). Đây là gap giả: theo VCI, quỹ −1,69% ngày 04/04 rồi −6,98% ngày 08/04.
- **Phát hiện:** so lịch phiên của mã với lịch phiên thị trường; tìm biến động 1 phiên vượt biên độ ±7% của HOSE; kiểm `low ≤ close ≤ high`.
- **Xử lý:** giá ETF lấy từ **VCI** (`etf.py`: `lay_gia_dong_cua(ma, so_ngay, "VCI")`). VCI cũng có lỗi riêng (FUEVFVND 23/04/2025 sai giá mở/thấp)
  nên đừng dùng giá mở cửa hay râu nến làm tín hiệu.
- Giá **cổ phiếu cơ sở** vẫn lấy từ KBS (`cw_scanner.lay_gia_dong_cua`, mặc định): với CS, KBS và VCI cho cùng số, còn API lịch sử VCI từng lỗi liên tục
  hơn 20 phút. Đổi nguồn cho loại tài sản nào thì phải kiểm lại lịch phiên của loại đó.

## 3. Đơn vị giá: nghìn đồng hay đồng
- **Triệu chứng:** vnstock trả giá CS, CW, ETF theo nghìn đồng (CW `0.87` = 870 đ); bảng giá Vietcap và HOSE trả theo đồng.
- **Xử lý (mẫu dùng khắp repo):** `he_so = 10 ** round(log10(giá bảng giá hôm nay / close vnstock phiên cuối))`, rồi nhân cả chuỗi
  (`etf.py` `lap_bang`, `cw_scanner.py` `main`, `kiem_chung_luot.lay_du_lieu`, `web.py`). Với ETF trong backtest thì so trung vị NAV / trung vị giá
  (`kiem_chung_chiet_khau.py`).
- CW đã hết hạn không còn giá trên bảng giá: suy hệ số từ các CW còn sống, và `kiem_chung_luot.lay_du_lieu` **raise** nếu các hệ số không giống nhau.
  Đã kiểm trên 333 CW còn sống: hệ số × 1000.
- Ô nhập tay (`danh_muc.py`): số < 100 được hiểu là nghìn đồng, vì giá CW thấp nhất là 10 đ = 0,01 nghìn.

## 4. NAV Vietcap IQ gắn sai nhãn ngày
- **Triệu chứng:** NAV thứ Sáu nằm ở dòng Chủ nhật, còn dòng thứ Sáu lặp lại số của thứ Năm; một ngày có 2 số khác nhau (số sau thường là NAV phiên kế tiếp,
  vd FUEMAV30 07/10/2026); có gai (FUESSVFL 07/04/2026 thật ra là NAV 08/04, E1VFVN30 dòng 16/11/2025 là NAV thứ Hai).
- **Xử lý:**
  - `chiet_khau.lam_sach_nav`: dòng Chủ nhật thay dòng thứ Sáu; ngày có 2 số thì bỏ hẳn; bỏ các dòng cuối tuần còn lại.
  - `chiet_khau.bo_nav_loi`: bỏ ngày mà tỷ lệ NAV / chỉ số lệch trung vị 5 phiên quanh nó > 0,5% (`SAI_LECH_NAV_TOI_DA`, `SO_PHIEN_SO_GAI`).
    Đo trên 19 quỹ: bắt đủ các lỗi đã biết, chỉ bỏ khoảng 20/9.000 ngày. Ngày cuối chuỗi chưa có phiên sau để xác nhận nên bị bỏ tạm.
- NAV Vietcap trễ khoảng 2 phiên và thiếu FUEPHVNS. NAV dừng quá 5 phiên thì có cảnh báo. Không nguồn nào lưu lịch sử iNAV: `ket_qua/inav_*.csv` do lần chạy 5 phút tự ghi.

## 5. Giá CS đã điều chỉnh nhưng điều khoản CW hết hạn thì "đóng băng"
- **Triệu chứng:** vnstock điều chỉnh giá CS theo cả cổ tức tiền lẫn cổ tức cổ phiếu. Điều khoản Vietcap của CW **còn sống** cũng được điều chỉnh cùng thang
  (đã kiểm: IV không nhảy vào ngày GDKHQ). Riêng CW **đã hết hạn** thì điều khoản dừng ở lúc hết hạn, nên sự kiện quyền sau đó làm K và giá CS lệch thang:
  494/651 CW hết hạn từ 08/2024.
- **Phát hiện:** ngày GDKHQ lấy từ `Company(source="VCI", symbol=cs).events()` (`kiem_chung_luot.ngay_su_kien`); CW có `gd_cuoi` < một ngày GDKHQ của CS.
- **Xử lý:**
  - `kiem_chung_luot` bỏ các CW này.
  - `kiem_chung_truyen_dan.lay_bo_sung` đưa thang về lúc hết hạn bằng `f = giá CS điều chỉnh / gia_tho_hose(cs, gd_cuoi)` (giá đóng cửa thô HOSE).
    Trước đó kiểm f ≈ 1 (lệch ≤ 0,5%) trên CW không có sự kiện, lệch thì raise. 64 CW bị mất vì HOSE không có giá thô đúng ngày GD cuối
    (10/10/2024, 26/03/2025, 24/04/2025…).

## 6. Điều khoản Vietcap lỗi
- **Triệu chứng:** 7 CW STB năm 2024 có K bị × 10 (K/giá CS ≈ 10); CACB2401 có K = 210.030 trong khi ACB khoảng 25.000.
- **Xử lý:** bỏ CW có trung vị K / giá CS nằm ngoài `K_TREN_S = (0.3, 3.0)` và ghi cảnh báo (`kiem_chung_luot.py`, `kiem_chung_truyen_dan.py`).
  Trước khi kết luận về một CW cụ thể, kiểm lại điều khoản trên website TCPH/HOSE.

## 7. P/E, P/B lịch sử của VNDirect trước 2024: có dấu hiệu lookahead
- Repo chỉ ghi một dòng (`KE_HOACH.md` cuối Phần 8, khi bỏ tiêu chí "P/E chỉ số"); chi tiết kiểm tra không còn lưu.
- **Xử lý:** đừng dùng làm tín hiệu lịch sử. Muốn dùng lại thì kiểm trước: so ngày có số với ngày công bố BCTC, xem số quá khứ có bị sửa ngược không.
  Nếu không kiểm được thì báo người dùng.

## 8. Giá đóng cửa của quỹ hoặc CW mỏng = 1 lô nhỏ, bị lệch lên
- **Triệu chứng:** giá mở/đóng cửa (kể cả ATO/ATC) thường do 1–2 lô 100 CCQ quyết định: FUEKIVFS 01/10 −6,5%, 02/10 +6,9% trong khi chỉ số −0,9% / −1,7%.
  Giá đóng cửa hay bằng đúng giá chào bán tốt nhất (FUEDCMID: 18/19 lần nhảy quá 1% là tăng). Độ lệch thường tự đảo chiều ở phiên sau.
- **Xử lý:**
  - "CK 1 lệnh": giá mua bình quân của 1 lệnh 50 triệu ăn dần 3 mức chào bán (`chiet_khau.gia_mua_lenh`, `GIA_TRI_LENH`), không dùng giá tốt nhất 1 lô.
  - Backtest tách kịch bản A (mua ngay ở giá đóng cửa: cận lạc quan) với B (mua phiên có khớp kế tiếp). Khoảng cách A–B chính là phần độ lệch tự đảo chiều.
  - Coi "bán ở giá đóng cửa" là lạc quan. Quỹ có < 200 phiên khớp/năm (`MIN_PHIEN_KHOP`) thì RSI, MA, biến động kém tin cậy.

## 9. Chiết khấu theo giá khớp cũ là ảo
- **Triệu chứng:** quỹ ít giao dịch giữ giá khớp cũ nhiều tuần, trong khi NAV đã đi xa (22/10/2026: FUEBFVND −6,6% và FUEKIVFS −3,1% đều ảo).
  Nhiều phiên không khớp thì lần khớp sau chỉ đi tối đa ±7%, nên 1 cây nến gánh biến động của nhiều tuần.
- **Xử lý:** CK = giá **chào bán** tốt nhất / iNAV − 1 (mua được ngay), kèm cột "Phiên chưa khớp", và lọc giá khớp cũ ≤ 1 phiên.
  Chuỗi giá lịch sử chỉ lấy phiên có khớp (`etf.chuoi_gia`). iNAV đứng yên trong khi giá chạy cũng tạo "chiết khấu" ảo (iNAV SSI đã xác nhận cập nhật trong phiên 23/10).
- Tương tự với CW: trước giờ giao dịch sổ lệnh trống, giá mua rơi về giá khớp/tham chiếu (cột *Nguồn giá mua*). Đừng so CSV định giá theo giá chào bán với CSV cũ định giá theo giá khớp.

## 10. So NAV, giá, chỉ số khác ngày tạo chênh lệch giả
- **Triệu chứng:** NAV trễ 2 phiên đem so với giá hôm nay; lợi nhuận NAV và lợi nhuận chỉ số tính trên 2 cặp ngày khác nhau; NAV có nhãn sai ngày (mục 4).
- **Xử lý (`chiet_khau.thong_ke_nav`):** chênh lệch giá/NAV chỉ tính trên ngày có cả giá khớp lẫn NAV. "NAV so CS 1N" tính trên **cùng 2 ngày**,
  tới hôm nay thì bằng iNAV (không có iNAV thì tới ngày NAV cuối). Giá/NAV đầu kỳ lấy đúng mốc của lợi nhuận giá. `bo_nav_loi` so NAV với chỉ số **cùng ngày**.
- Chỉ số VN30, VNDIAMOND… là chỉ số **giá**, còn quỹ nhận cổ tức. E1VFVN30 mô phỏng VN30-TRI nên "so CS 1N" của nó lệch dương; đây không phải lỗi.

## 11. Survivorship bias
- **ETF:** danh sách là các quỹ đang niêm yết hôm nay (`Listing(source="VCI").symbols_by_group("ETF")`), quỹ đã hủy niêm yết không có trong mẫu.
  Khi báo kết quả backtest ETF, ghi rõ giới hạn này.
- **CW:** `Listing(source="KBS").all_covered_warrant()` chỉ trả CW đang niêm yết. Backtest lấy thêm CW đã hết hạn bằng cách dò mã
  `C{CS}{24–26}{01–79}` trên bảng giá Vietcap (bảng này vẫn trả điều khoản của CW hết hạn; vnstock gói golden có khoảng 800 ngày giá, kể cả CW hết hạn).
  Mẫu vẫn chỉ gồm 20 CS đang có CW.
- Vietcap trả `listingInfo` rỗng cho mã không tồn tại hoặc đã hủy niêm yết, nên nơi dùng phải tự xử lý mã bị thiếu.

## 12. Lookahead và độc lập thống kê trong backtest
- Tín hiệu phiên T chỉ dùng dữ liệu có tới T: điểm xếp hạng CW chỉ dùng giá tới ngày vào lệnh; trung vị trượt dùng `.shift(1)` trước `.rolling()`
  (`kiem_chung_chiet_khau.py`). Kịch bản chính mua phiên **sau** tín hiệu, lúc NAV T đã công bố.
- Hệ số đo trên dữ liệu kiểm (β IV theo TCPH) phải kiểm ngoài mẫu: đo trước một mốc, kiểm sau mốc đó (`kiem_chung_truyen_dan.py`).
- CW cùng ngày, cùng CS tương quan mạnh: số quan sát độc lập ≈ **số ngày**, không phải số lệnh, nên t-stat phải tính theo ngày.
- Lãi danh nghĩa phải trừ phần thị trường trước khi coi là tín hiệu ("vượt NAV" = (1 + lãi) / (1 + lợi nhuận NAV cùng kỳ) − 1). Kiểm chéo: mua ở mọi phiên
  thì vượt NAV ≈ −0,4%, đúng bằng chi phí khứ hồi.

## 13. Lặt vặt đã gặp
- vnstock trả **bảng rỗng, không báo lỗi** cho mã không có giá trong kỳ: gọi `df["close"].iloc[-1]` ngay để lỗi nổi lên.
- `VNSTOCK_AUTH_MINUTE_LIMIT`: chờ 61 giây rồi thử lại 1 lần (`cw_scanner.lay_gia_dong_cua`), không lặp vô hạn.
- Sổ lệnh phiên ATO/ATC có thể ghi chữ thay cho giá: lọc phần tử là số > 0 (`cw_scanner.gia_mua`).
- API không chính thức (Vietcap, KBS, SSI) có lúc lỗi 500 từ vài phút tới hơn 20 phút. Khi đó lần quét thất bại và báo lỗi, không dùng dữ liệu nửa vời.
- `Trading().price_board()` của vnstock (thấy ở bản 4.0.9) xóa các cột điều khoản CW, nên điều khoản lấy thẳng từ API bảng giá Vietcap (`lay_bang_gia`).
- Máy Mac ngủ thì launchd không chạy: một ngày thiếu file `inav_*.csv` là do máy ngủ, không phải do thị trường nghỉ.

## Khi thêm nguồn hoặc đổi nguồn — checklist ngắn
1. Đơn vị (đồng / nghìn đồng / điểm chia 1.000) và số chữ số thập phân.
2. Lịch phiên: so với lịch thị trường, đếm số phiên thiếu.
3. Giá đã điều chỉnh hay giá thô; điều khoản CW có cùng thang không.
4. Nhãn ngày: dữ liệu trễ bao nhiêu phiên, có ghi vào cuối tuần không.
5. Có bị lọc theo "đang niêm yết" không (survivorship).
6. Domain có nằm trong danh sách nguồn đã dùng không (AGENTS.md mục 5). Domain mới thì hỏi người dùng trước.
7. Nếu hai nguồn mâu thuẫn (vd vnstock vs filing): **dừng và báo**, đừng tự chọn một bên.
