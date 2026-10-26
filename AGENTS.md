# AGENTS.md — cw_scanner: sàng lọc chứng quyền (CW) và ETF trên HOSE

> Luật nền cho mọi agent làm việc trong repo. Tài liệu người dùng (cách chạy, công thức, kết quả kiểm chứng): `KE_HOACH.md`.
> Bản đồ code (file nào làm gì, sửa X thì mở đâu): skill `code-map`.

## 0. Ngôn ngữ và cách trao đổi
- Trả lời, comment, commit message: tiếng Việt (thuật ngữ kỹ thuật/tài chính giữ tiếng Anh).
- Người dùng là nhà đầu tư cá nhân, không phải lập trình viên: giải thích ngắn, dễ hiểu, có ví dụ số.
- **Lập plan trước khi code** (việc sẽ làm, file sẽ đụng, rủi ro) và chờ duyệt với việc lớn. Không tự ý phình scope.

## 1. Dự án làm gì
Công cụ sàng lọc cho 1 người dùng trên máy Mac của họ, **không phải khuyến nghị đầu tư**:
- Định giá CW bằng Black-Scholes, IV/HV, xếp hạng lướt 2–5 phiên, hiệu chỉnh IV theo tổ chức phát hành (`cw_scanner.py`).
- Danh mục CW đang nắm + cảnh báo Discord (`danh_muc.py`).
- ETF: chiết khấu so với NAV/iNAV, báo cáo ngày, cảnh báo trong phiên (`etf.py`, `chiet_khau.py`).
- Backtest/kiểm chứng chỉ đọc dữ liệu (`kiem_chung_*.py`); kết luận ghi trong `KE_HOACH.md`.
- Giao diện web cục bộ (`web.py`, http://localhost:8000).

## 2. Tech stack (không tự đổi nếu chưa hỏi)
- Python 3.10+, `.venv` riêng của repo; dependency: `requirements.txt` (vnstock 5.1.0 ghim cứng, pandas), dev: `requirements-dev.txt`.
- Web: `http.server` thư viện chuẩn, HTML/CSS/JS viết tay; không framework.
- Dữ liệu: vnstock 5.x (thế hệ 5, xem `~/AGENTS.md`), API bảng giá Vietcap, SSI iBoard (iNAV), Vietcap IQ (NAV), HOSE. Đều là API không chính thức.
- Lưu trữ: file trong `ket_qua/` (CSV, JSON, MD; gitignore), `danh_muc.csv`, `cw_da_biet.txt`. **Không có database.**
- Tự động: launchd (`cai_lich_quet.sh` cài 4 lịch `vn.cw-scanner.*`), các script `.sh` gọi `.venv/bin/python`. Sao lưu `ket_qua/` sang `~/cw_scanner_sao_luu`.
- Thông báo: Discord webhook (`DISCORD_WEBHOOK_URL` trong `.env`).
- Kiểm tra: pytest, ruff, black (line-length 120). Hook `.githooks/pre-commit` chạy cả ba + quét secret.

## 3. Luật vàng (NON-NEGOTIABLE)
1. **Không bịa số liệu, không bịa công thức tài chính.** Công thức phải khớp tài liệu chuẩn (Hull, CFA, Damodaran) hoặc đã được người dùng chốt.
   Không chắc → dừng, hỏi. Xem skill `valuation-models` (repo) và `vn-valuation-rules` (toàn máy).
2. **Dữ liệu phải toàn vẹn:** đơn vị (nghìn đồng vs đồng, điểm chỉ số /1000), nhãn ngày NAV, giá đã điều chỉnh vs điều khoản CW, lookahead, survivorship.
   Xem skill `financial-data-integrity` (repo) và `vn-finance-data` (toàn máy) TRƯỚC khi đụng dữ liệu.
3. **Mọi con số đầu ra truy vết được:** giả định ghi vào `ket_qua/gia_dinh_*.json`; ngưỡng là hằng số ở đầu file, không có magic number rải trong code.
4. **Không phá dữ liệu của người dùng:** `danh_muc.csv`, `cw_da_biet.txt`, `ket_qua/` không xóa/ghi đè hàng loạt khi chưa hỏi; ghi file kiểu tạm-rồi-đổi-tên.
5. **Không đổi ngưỡng, tiêu chí, thứ tự xếp hạng đang chạy** khi chưa có kiểm chứng và người dùng duyệt.
6. **Bảo mật mục 5 là tối thượng.**

## 4. Cách làm việc theo từng bước
1. Plan trước, chờ duyệt với việc lớn hoặc mơ hồ.
2. Làm nhỏ, một lát cắt hoàn chỉnh + test mỗi lần.
3. Mỗi hàm tài chính có unit test với ít nhất 1 ca **tính tay ra đúng** (ví dụ CVPB2615 ở `KE_HOACH.md` Phần 1).
4. Tự kiểm chứng: chạy thật, in vài dòng mẫu; sửa giao diện thì mở trang (`.claude/launch.json`: `cw-web`) và xem.
5. Commit nhỏ, message nói *cái gì + tại sao*.
6. Sửa bug: tìm nguyên nhân gốc, viết test tái hiện trước khi sửa; không bọc try/except để nuốt lỗi.
7. Đụng tích hợp ngoài (Discord, launchd, nguồn dữ liệu mới, lệnh hệ thống): dừng và xin duyệt trước khi chạy.

## 5. Bảo mật
- Không bao giờ hardcode hay commit `VNSTOCK_API_KEY`, `DISCORD_WEBHOOK_URL` hay bất kỳ token nào. Secret chỉ ở `.env` (gitignore); mẫu: `.env.example`.
- Không in, `echo`, log giá trị secret ra console, Discord hay file kết quả.
- Chỉ gọi các nguồn dữ liệu đã dùng trong repo (vnstock, Vietcap, SSI, HOSE). Domain mới → hỏi trước.
- Input từ ngoài (mã do người dùng nhập trên web, payload API) phải validate bằng regex/whitelist trước khi dùng; web chỉ nghe localhost và kiểm `Origin`
  (`nguon_hop_le`).

## 6. Định nghĩa "Hoàn thành"
- [ ] Test pass, có ca tính tay với hàm tài chính; ruff + black sạch (hook đạt).
- [ ] Không secret, không magic number.
- [ ] Đã chạy thật hoặc mở trang để xem; có sample output cho người dùng.
- [ ] Cập nhật `KE_HOACH.md` nếu đổi hành vi, ngưỡng hay cách đọc kết quả.

## 7. Khi nào DỪNG và hỏi
- Công thức/giả định tài chính không chắc chắn; muốn đổi ngưỡng, tiêu chí, mô hình.
- Kết quả vô lý (IV không giải được hàng loạt, "rẻ hơn" vài trăm %, giá âm) — báo, đừng giấu.
- Dữ liệu mâu thuẫn giữa các nguồn, hoặc nguồn đổi định dạng.
- Cần thêm dependency, dịch vụ ngoài, hoặc đổi lịch launchd.
