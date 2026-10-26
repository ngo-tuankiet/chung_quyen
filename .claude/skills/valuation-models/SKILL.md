---
name: valuation-models
description: Mô hình định giá nào dùng cho tài sản nào trong cw_scanner, kèm giả định, giới hạn và hàm đang dùng. Gồm Black-Scholes cho chứng quyền (CW) kiểu châu Âu thanh toán tiền, HV/IV, hành vi tổ chức phát hành (IV đổi theo hướng CS, β theo TCPH), NAV/iNAV và chiết khấu cho ETF, và khi nào KHÔNG dùng P/E, EV/EBITDA cho cổ phiếu. Đọc TRƯỚC khi viết hoặc sửa bất kỳ công thức giá, giá hợp lý, IV, hòa vốn, lãi kịch bản, chiết khấu NAV, chỉ số định giá; khi thêm loại tài sản hay mô hình mới; hoặc khi kết quả định giá trông vô lý. Có quy tắc dừng hỏi người dùng khi không chắc công thức.
---

# Mô hình định giá — cw_scanner

Luật vàng 1–2 của AGENTS.md: không bịa công thức, không dùng sai mô hình cho sai loại tài sản. File này chỉ ghi những gì đã có trong repo,
kèm nguồn chuẩn khi có. Những gì **không** có ở đây thì làm theo mục "Khi nào dừng và hỏi" ở cuối.
Chi tiết và ví dụ số: `KE_HOACH.md` Phần 1, 6, 7b, 8.
Luật chung cho cổ phiếu (WACC/COE, ROE bền vững, NOT_RATED, hiệu chuẩn…): skill toàn máy `vn-valuation-rules`.

## Bảng chọn mô hình

| Tài sản | Mô hình | Hàm | Ghi chú |
|---|---|---|---|
| CW trên HOSE | Black-Scholes call châu Âu, không cổ tức | `cw_scanner.black_scholes_call` → (giá, delta) | giá 1 CW = giá quyền / tỷ lệ chuyển đổi n |
| Biến động lịch sử (HV) | độ lệch chuẩn của ln(P_t / P_t−1), 250 phiên, × √250 | `bien_dong_lich_su` | `SO_PHIEN_DO_BIEN_DONG`, `SO_PHIEN_MOT_NAM` |
| Biến động ngầm định (IV) | giải ngược Black-Scholes bằng chia đôi trên [0,001; 5] | `bien_dong_ngam_dinh` | trả None nếu giá × n < cận dưới `can_duoi` = max(S − K·e^(−rT), 0) |
| Kiểm chéo Black-Scholes | Monte Carlo 20.000 kịch bản, seed cố định | `mo_phong_gia` | chỉ để kiểm, không để định giá |
| Lướt CW 2–5 phiên | hòa vốn và lãi kịch bản theo BS, IV giữ nguyên (hoặc + β) | `luot_ngan_han` | gồm sẵn spread, mất giá theo thời gian, phí, thuế |
| ETF | so với NAV/iNAV của chính quỹ | `chiet_khau.py`, `etf.py` | không định giá rổ cổ phiếu |
| Cổ phiếu VN100 | **chưa có mô hình trong repo** | — | xem mục "Cổ phiếu" bên dưới |

## CW: Black-Scholes

**Vì sao dùng được:** CW ở Việt Nam là kiểu châu Âu (chỉ thực hiện lúc đáo hạn) và thanh toán bằng tiền.
Tiền nhận lúc đáo hạn cho 1 CW = max(giá thanh toán − K, 0) / n. Đây đúng là loại quyền chọn mà công thức Black-Scholes mô tả
(nguồn chuẩn: Hull, *Options, Futures, and Other Derivatives*, chương Black-Scholes-Merton).

```
d1 = [ln(S/K) + (r + σ²/2)·T] / (σ·√T),   d2 = d1 − σ·√T
Giá quyền = S·N(d1) − K·e^(−rT)·N(d2);     Giá 1 CW = Giá quyền / n
```
- T = số ngày lịch tới **ngày đáo hạn** / 365. r = `LAI_SUAT_PHI_RUI_RO` (đang là 0,04, chỉnh trong config, không viết số vào code).
- T ≤ 0 hoặc σ ≤ 0: chỉ còn giá trị nội tại max(S − K, 0).
- **Ca tính tay để test** (CVPB2615, 16/10/2026): S = 24.500, K = 22.605, n = 1,5863, 123 ngày, r = 4%, σ = 32,8% → d1 = 0,5888, d2 = 0,3984,
  giá quyền ≈ 3.085 đ, giá 1 CW ≈ 1.944 đ. Tính tay khác số này thì code sai, không phải ví dụ sai.

**Giả định và giới hạn** (KE_HOACH Phần 6; khi trình bày kết quả phải nói ra, đừng giấu):
1. σ không đổi tới đáo hạn. **HV ≠ biến động tương lai**: đây là nguồn sai số lớn nhất. "Rẻ 40%" có thể chỉ vì TCPH yết IV thấp hơn,
   hoặc năm qua CS có biến cố làm HV phình to.
2. Cổ tức **không** đưa vào mô hình: khi có cổ tức tiền, cổ tức cổ phiếu hay thưởng cổ phiếu, TCPH điều chỉnh K và n theo hệ số giá tham chiếu ngày GDKHQ
   (TT 107/2016 Điều 10, nay là TT 122/2025), còn giá CS lịch sử của vnstock đã được điều chỉnh. Thêm lợi suất cổ tức vào là **tính trùng**.
   Ví dụ VPB 2026: CVPB2608 đi từ K 30.000, tỷ lệ 2:1 về K 23.379, tỷ lệ 1,5586:1.
3. Giá thanh toán là trung bình giá đóng cửa 5 phiên trước đáo hạn, mô hình coi như giá 1 ngày (sai số nhỏ). CW còn < 20 ngày tới GD cuối thì đừng lướt
   (`MIN_NGAY_GD_CUOI_LUOT`).
4. Giá thị trường **do TCPH chi phối**: TCPH là bên bán chính, không bắt buộc yết theo giá trị lý thuyết, và Việt Nam không cho bán khống. Vì vậy giá có thể
   nằm dưới giá hợp lý rất lâu (ACBS: IV CVPB2608/2615 từ khoảng 41% lúc lên sàn xuống 12–14% vào 10/2026). Phần "rẻ" chỉ chắc thu về nếu giữ tới đáo hạn.
5. 4 tiêu chí của `danh_gia` chưa trừ phí/thuế. Phần lãi/lỗ thì có trừ (`PHI_GIAO_DICH`, `THUE_BAN`).
   **Giữ tới đáo hạn:** thuế 0,1% tính trên giá trị danh nghĩa CS (giá thanh toán / tỷ lệ), không trên tiền nhận về, nên CW sát K có thể
   bị thuế lớn hơn tiền nhận. Mọi chỗ dùng chung `cw_scanner.tien_dao_han`; theo mô hình thì giá trị giữ = (call − thuế·S·delta) / n.
   Nguồn: bản cáo bạch HSC 2023 (mục rủi ro thuế); Luật Thuế TNCN 109/2025 giữ 0,1%/lần, nghị định cho thực hiện quyền chưa xác minh.
6. Giá mua = giá **chào bán** thấp nhất (`gia_mua`); sổ lệnh trống thì rơi về giá khớp/tham chiếu, cột *Nguồn giá mua* ghi rõ. IV giải từ giá chào bán.
   Trong backtest, IV giải từ giá đóng cửa (≈ giá giữa).

## CW: hành vi tổ chức phát hành (IV đổi theo hướng CS)
- Bảng ⚡ giả định IV giữ nguyên trong 5 phiên. Backtest (`kiem_chung_luot.py`) cho thấy IV đổi trung vị −0,2 điểm, nhưng P10–P90 là −5,6…+5,1 điểm,
  và lãi thực lệch mô hình ±4,2% (trung vị tuyệt đối), chủ yếu do IV.
- Nhiều TCPH **hạ IV khi CS tăng** (ACBS, Vietcap rõ nhất). Hiệu chỉnh đang dùng (người dùng chọn 24/10/2026):
  **IV bán ra = IV chờ mua + β × CS đổi**, với β = trung vị (ΔIV / CS đổi) trên cửa sổ 5 phiên có |CS| ≥ 2%, theo từng TCPH và từng chiều.
  Code: `luot_ngan_han(..., d_iv=β × 5%)`, `doc_he_so_iv`, `lai_kb_hieu_chinh`. Chỉ áp vào lãi kịch bản, **không** áp vào "CS cần tăng", và không đổi thứ tự xếp hạng.
- **Đừng nhân một "hệ số truyền dẫn" chung** (CW thực đổi / CW mô hình đổi): IV tác động lên giá qua vega, nên truyền dẫn phụ thuộc độ sâu tiền
  (ACBS khi CS tăng, 12 tháng: ngoài tiền 0,43, quanh giá 0,45, trong tiền 0,74). Một hệ số chung sẽ sai ở cả 2 đầu.
- β lấy từ file `ket_qua/he_so_iv_tcph_*.csv` mới nhất. Chỉ dùng **12 tháng gần nhất** (`SO_THANG_HE_SO_IV`), chỉ TCPH có ≥ 50 cửa sổ (`MIN_MAU_HE_SO_IV`),
  còn lại để "—". Lý do: TCPH đổi cách yết theo thời gian (β ACBS khi CS tăng: −0,20 năm 2025-H1 → −0,88 năm 2026-H2).
  **Không chép bảng β vào code hay tài liệu**, vì nó cũ đi. Chạy lại: `python kiem_chung_luot.py` rồi `python kiem_chung_truyen_dan.py`.
- β là trung vị, không phải hồi quy: không tách được phần IV trôi theo thời gian khỏi phần theo CS. Muốn đổi sang hồi quy hay mô hình IV khác thì hỏi trước.
- Đọc kết quả xếp hạng lướt đúng nghĩa: thứ tự là **thước đo chi phí** (đúng khi CS đi −5…+5% trong 5 phiên), không phải dự báo, và vô dụng khi CS > +5%.

## ETF: NAV / iNAV
ETF không định giá bằng mô hình mà so với NAV của chính quỹ. Giá mỗi CCQ (9.360 đ hay 33.980 đ) không nói gì về đắt hay rẻ.
- **CK (chiết khấu mua được)** = giá chào bán tốt nhất / iNAV − 1. **CK 1 lệnh** = giá mua bình quân của 1 lệnh `GIA_TRI_LENH` ăn 3 mức chào bán / iNAV − 1.
- **Lãi ròng nếu về NAV** = iNAV × (1 − phí − thuế) / (giá chào bán × (1 + phí)) − 1 (`lai_rong_neu_ve_nav`). Tính tay: 9.700 và 10.000 → +2,68%.
- **Mức thường** = trung vị (giá đóng cửa / NAV − 1) 1 năm của chính quỹ. "Rẻ hơn thường" = CK 1 lệnh − mức thường. Có quỹ chiết khấu thường trực
  (FUEFCV50, FUEIP100), nên CK âm chưa chắc là rẻ bất thường.
- **Vượt NAV** (dùng trong backtest) = (1 + lãi) / (1 + lợi nhuận NAV cùng kỳ) − 1: phần lãi nhờ chênh lệch thu hẹp, đã bỏ phần thị trường.
- Kiểm chứng 22–23/10/2026: cả ngưỡng tuyệt đối 2% lẫn ngưỡng tương đối đều **không** tự có lãi khi mua phiên sau (vượt NAV ≈ 0 sau phí).
  Đây là sàng lọc, không phải tín hiệu. Người kéo giá về NAV là thành viên lập quỹ (lô 100.000 CCQ), họ không bị buộc phải làm vậy.

## Cổ phiếu (VN100): chưa có mô hình
AGENTS.md đặt mục tiêu định giá cổ phiếu VN100, nhưng repo hiện chưa có code định giá cổ phiếu, và `docs/spec.md` mà AGENTS.md nhắc tới chưa tồn tại.
Chấm điểm ETF theo "P/E chỉ số" đã bỏ vì người dùng không chọn tiêu chí "chỉ số rẻ"; P/E, P/B lịch sử VNDirect trước 2024 có dấu hiệu lookahead.
Trước khi viết bất kỳ mô hình cổ phiếu nào: **lập plan và hỏi người dùng chọn mô hình**. Các luật cứng đã có:
- **Không dùng EV/EBITDA hay DCF theo FCFF cho ngân hàng, bảo hiểm, công ty chứng khoán.** Với các doanh nghiệp này, nợ là "nguyên liệu" chứ không phải
  nguồn vốn, và tái đầu tư không xác định được, nên chi phí vốn và EV mất nghĩa. Dùng mô hình vốn chủ (cổ tức / FCFE) và bội số theo vốn chủ.
  Nguồn: Damodaran, *Investment Valuation* (3rd ed.), Ch. 21 "Valuing Financial Service Firms":
  <https://pages.stern.nyu.edu/~adamodar/pdfiles/val3ed/c21.pdf>.
- **Không dùng P/E cho công ty lỗ** (EPS ≤ 0): P/E âm hoặc không xác định thì không có nghĩa kinh tế. Khi xếp hạng, dùng lợi suất lợi nhuận E/P;
  hoặc chuyển sang bội số khác, nhưng phải hỏi trước. Nguồn: CFA Institute, *Market-Based Valuation: Price and Enterprise Value Multiples* (refresher reading 2026):
  <https://www.cfainstitute.org/insights/professional-learning/refresher-readings/2026/market-based-valuation-price-enterprise-value-multiples>.
- Dữ liệu BCTC đưa vào mô hình phải qua checklist của skill `financial-data-integrity`: hợp nhất hay công ty mẹ, restatement, ngày công bố (lookahead), survivorship.
- Base case do máy đặt chỉ là điểm khởi đầu, người dùng phải chỉnh được (AGENTS.md mục 7).

## Khi nào dừng và hỏi người dùng
- Công thức hoặc giả định không có trong file này, trong `KE_HOACH.md`, và không dẫn được nguồn chuẩn (CFA, Damodaran, Hull, văn bản pháp luật).
  Đừng "đoán cho chạy".
- Định đổi mô hình đang dùng: thêm cổ tức vào BS, đổi cách đo HV (số phiên, EWMA…), đổi cách hiệu chỉnh TCPH, đổi r, đổi thứ tự xếp hạng.
- Muốn áp mô hình cho loại tài sản mới: CW kiểu khác (put, kiểu Mỹ, CW trên chỉ số), chứng chỉ quỹ mở, trái phiếu, cổ phiếu.
- Kết quả vô lý: giá âm, IV không giải được ở hàng loạt CW, upside/"rẻ hơn" vài trăm %, K/giá CS ngoài khoảng 0,3–3. Báo kèm số liệu, đừng lọc bỏ cho đẹp.
- Hai nguồn cho điều khoản CW hoặc NAV khác nhau: báo, kiểm lại trên website TCPH/HOSE.

Mỗi công thức mới cần có unit test, với ít nhất 1 ca số liệu tính tay ra đúng (AGENTS.md mục 4.3), như ca CVPB2615 ở trên.
