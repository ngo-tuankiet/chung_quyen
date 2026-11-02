---
name: code-map
description: Bản đồ code của cw_scanner — file nào làm gì, hàm chính ở đâu, luồng quét CW/ETF/danh mục, file nào sinh ra trong ket_qua/, lịch launchd, lệnh chạy và test, và "muốn sửa X thì mở file Y". Đọc ĐẦU TIÊN khi nhận bất kỳ việc code nào trong repo này (sửa giao diện web, tiêu chí CW, lướt, ETF, danh mục, cảnh báo Discord, backtest), để mở đúng file thay vì đọc cả repo.
---

# Bản đồ code — cw_scanner

~7.500 dòng Python, không có database: mọi kết quả là file trong `ket_qua/`. Tài liệu người dùng + kết quả kiểm chứng: `KE_HOACH.md`.
Bản đồ viết 26/10/2026; thấy lệch với code thì tin code và sửa lại bản đồ.

## File
| File | Làm gì | Hàm chính |
|---|---|---|
| `cw_scanner.py` | Lõi CW: lấy dữ liệu, Black-Scholes, IV/HV, 4 tiêu chí, lướt, lưu kết quả quét | `black_scholes_call`, `bien_dong_ngam_dinh`, `lay_bang_gia` (API Vietcap), `lay_gia_dong_cua` (vnstock), `bien_dong_lich_su`, `gia_mua`, `danh_gia`, `dinh_gia`, `luot_ngan_han`, `chon_luot`, `doc_he_so_iv`, `lai_kb_hieu_chinh`, `la_ngay_giao_dich`, `main` |
| `danh_muc.py` | Lệnh CW đang nắm (`danh_muc.csv`), vị thế, cảnh báo + báo cáo ngày qua Discord | `them_lenh`, `xoa_lenh`, `tinh_vi_the`, `danh_gia_danh_muc`, `kiem_tra`, `bao_cao_ngay`, `gui_discord` |
| `etf.py` | Báo cáo ETF: giá/NAV, chỉ số kỹ thuật, xếp hạng "rẻ hơn thường" | `lay_du_lieu` (VCI), `lay_nav`, `lap_bang`, `xep_hang`, `bao_cao_gon`, `chay` |
| `chiet_khau.py` | Chiết khấu ETF so với iNAV (SSI), làm sạch NAV Vietcap IQ, cảnh báo trong phiên | `lai_rong_neu_ve_nav`, `gia_mua_lenh`, `danh_gia_quy`, `lam_sach_nav`, `bo_nav_loi`, `thong_ke_nav`, `kiem_tra_trong_phien` |
| `web.py` | Máy chủ web localhost:8000: định tuyến GET/POST, chặn CSRF (`nguon_hop_le`), nút 🔄 Quét chạy nền (`VIEC_QUET` loại -> bước; đang quét mọi trang hiện `W.trang_cho`) | `XuLy`, `bat_dau_quet`, `chay_quet`, `bo_bo_nho` |
| `web_chung.py` | Phần chung của web: CSS/JS, `trang` (khung + menu; trải hết chiều ngang, tự thu `p.phu` > 160 ký tự vào "ℹ Giải thích" trừ /huong-dan), `hang_doi` (2 mục cạnh nhau, < 1.100 px xếp 1 cột), `bieu_do_nen` + `bang_khop_lenh` (khớp lẻ < `cw_scanner.GIA_TRI_KHOP_TOI_THIEU` vẽ mờ), `do_sau_thi_truong`, `so`, `bang` (bảng CW, cột `COT`), `bieu_do`, `doc_ket_qua`, nút 🔄 Quét theo tab (`NUT_QUET`, `muc_quet`, màn hình chờ `trang_cho`), trạng thái `QUET`/`LOI_DANH_MUC` | |
| `web_cw.py` | `/` danh sách CW (+ mục ⚠ giảm mạnh), `/cw/<mã>` chi tiết (+ nến H1/H4/D1 CW/CS), `/sap-ra-mat` | `trang_chinh`, `muc_giam_manh`, `trang_chi_tiet`, `trang_sap_ra_mat` (mục nến: `web_chung.muc_nen`, dùng chung với ETF) |
| `web_luot.py` | Mục ⚡ Lướt trên trang chính (`/#luot`, cột `COT_LUOT`; `/luot-cw` chuyển hướng 301) | `muc_luot` |
| `web_etf.py` | `/etf`, `/etf/<mã>` (giống trang CW: ô, Tóm tắt, kịch bản bán, nến quỹ + chỉ số, iNAV trong phiên, bám chỉ số) | `trang_etf`, `trang_etf_chi_tiet`, `bang_etf`, `so_lieu_truc_tiep`, `kich_ban_ban`, `muc_inav_trong_phien`, `muc_theo_kip_chi_so` |
| `web_phai_sinh.py`, `phai_sinh.py` | `/phai-sinh`, `/phai-sinh/<mã>`: HĐTL VN30 và VN100 (`CHI_SO_HD`; basis, năm hóa, lãi/lỗ giữ đến đáo hạn, nến HĐ + chỉ số) | `trang_phai_sinh`, `trang_phai_sinh_chi_tiet`; `lay_du_lieu`, `basis`, `basis_nam_hoa`, `lai_lo_dao_han`, `thue_mot_lan` |
| `web_canh_bao.py`, `canh_bao_gia.py` | `/canh-bao` (🔔 đầu menu): giá lệch bất thường đang mua được (CW so giá lẽ ra theo CS, ETF dưới iNAV + số HĐTL phòng hộ, HĐTL đắt/rẻ so với S·e^(rT) sau chi phí 2 chân) + mức giá tự đặt (`muc_gia.csv`, POST `/canh-bao/them`, `/canh-bao/xoa`); lịch 5 phút `kiem_tra_muc_gia` (gọi từ `danh_muc.py`) | `trang_canh_bao`, `lay_du_lieu`; `cw_lech_re`, `etf_duoi_inav`, `hdtl_lech`, `lai_khoa_ban_hd_mua_etf`, `so_hd_phong_ho`, `gia_xet`, `them_muc_gia`, `kiem_tra_muc_gia` |
| `web_danh_muc.py`, `web_huong_dan.py` | `/danh-muc`, `/huong-dan` | `trang_danh_muc`, `trang_huong_dan` |
| `kiem_chung_luot.py` | Backtest thứ tự xếp hạng lướt; tải dữ liệu CW kể cả đã hết hạn (cache `.pkl`) | `lay_du_lieu`, `dieu_khoan`, `chay` |
| `kiem_chung_truyen_dan.py` | Đo β IV theo TCPH → `ket_qua/he_so_iv_tcph_*.csv` (trang ⚡ đọc) | `gia_tho_hose`, `lay_bo_sung`, `bang_he_so`, `chay` |
| `kiem_chung_chiet_khau.py` | Backtest ngưỡng chiết khấu ETF | `chay` (`tuong_doi` = ngưỡng tương đối) |
| `test_*.py` | pytest cho từng file trên (có ca tính tay); `test_web.py`: nút 🔄 Quét | |

Trang web đọc qua module (`W.doc_ket_qua()`, `W.LOI_DANH_MUC`), không `from web_chung import doc_ket_qua`: để handler gán được và test patch được.

## Luồng
- **Quét CW** (`cw_scanner.py` / nút 🔄 Quét ở tab Chứng quyền hoặc Cảnh báo): danh sách CW (vnstock KBS) → bảng giá Vietcap (điều khoản, sổ lệnh) → giá CS 1 năm → HV →
  BS + IV → 4 tiêu chí + lướt → `ket_qua/cw_*.csv`, `gia_dinh_*.json`, `lich_su_*.json`; cập nhật `cw_da_biet.txt` (đánh dấu CW mới).
- **Danh mục:** `danh_muc.py` đọc file quét mới nhất + bảng giá → cảnh báo → Discord; trạng thái đã gửi trong `canh_bao_da_gui.json`.
- **ETF:** `etf.py` → `ket_qua/etf_*.csv|.md`, `nav_etf_*.csv.gz`; `chiet_khau.py --trong-phien` → `inav_*.csv`, cảnh báo, `canh_bao_chiet_khau.json`.
- **Kiểm chứng** (chạy tay, chỉ đọc dữ liệu): `kiem_chung_*.py` → `ket_qua/kiem_chung_*_<ngày>.md|.csv`; kết luận chép vào `KE_HOACH.md` Phần 7b/8.

## Tự động (launchd, `bash cai_lich_quet.sh` cài / `… go` gỡ)
| Lịch | Script | Giờ |
|---|---|---|
| `vn.cw-scanner.quet` | `chay_quet_tu_dong.sh` (quét, danh mục, báo cáo ngày, sao lưu `~/cw_scanner_sao_luu`) | 14:00 T2–T6 |
| `vn.cw-scanner.etf` | `chay_etf_tu_dong.sh` | 9:40 T2–T6 |
| `vn.cw-scanner.danh-muc` | `kiem_tra_danh_muc.sh` | mỗi 5 phút |
| `vn.cw-scanner.chiet-khau` | `kiem_tra_chiet_khau.sh` | mỗi 5 phút |
Nhật ký: `log.txt`. Ngày nghỉ lễ: `la_ngay_giao_dich()` bỏ qua.

## Lệnh
- Test: `.venv/bin/python -m pytest -q`; lint: `.venv/bin/python -m ruff check . && .venv/bin/python -m black --check .` (hook pre-commit chạy cả ba).
- Web: `.venv/bin/python web.py` hoặc `.claude/launch.json` → `cw-web` (cổng 8000; nếu đang có server cũ chạy thì phải tắt/khởi động lại để thấy code mới).
- Quét tay: `.venv/bin/python cw_scanner.py`; ETF: `.venv/bin/python etf.py --no-discord`.

## Muốn sửa X thì mở đâu
| Việc | Mở |
|---|---|
| Ngưỡng / tiêu chí CW, phí, thuế, r | hằng số đầu `cw_scanner.py` (rồi cập nhật `KE_HOACH.md` Phần 4) |
| Công thức định giá, IV, lướt | `cw_scanner.py` + `test_cw_scanner.py` (ca tính tay) |
| Thêm cột vào bảng CW | `cw_scanner.dinh_gia` (tính) → `web_chung.COT` (hiển thị) |
| Trang 🔔 Cảnh báo giá, mức giá tự đặt | `canh_bao_gia.py` (công thức, ngưỡng đầu file, `GUI_DISCORD_MUC_GIA`) → `web_canh_bao.py` |
| Bảng ⚡ Lướt | `cw_scanner.luot_ngan_han`/`chon_luot` → `web_luot.py` |
| Một trang web | `web_<trang>.py`; menu, CSS, khung trang: `web_chung.py`; đường dẫn mới: `web.py::XuLy.do_GET` |
| Cảnh báo / báo cáo Discord | `danh_muc.py` (CW), `etf.py`, `chiet_khau.py` (ETF) |
| Ngưỡng ETF | đầu `etf.py`, `chiet_khau.py` |
| Hệ số IV theo TCPH | chạy lại `kiem_chung_luot.py` rồi `kiem_chung_truyen_dan.py` |

Bẫy dữ liệu: skill `financial-data-integrity`; mô hình: `valuation-models`; luật chung: `vn-finance-data`, `vn-valuation-rules`.
