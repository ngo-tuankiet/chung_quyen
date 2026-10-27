"""
web.py - Giao diện web cho cw_scanner (chỉ dùng thư viện có sẵn của Python, không cần cài thêm).

Cách chạy:  python web.py   -> trình duyệt tự mở http://localhost:8000
- Trang chính: bấm "Quét ngay" để chạy cw_scanner.main(); luôn hiển thị kết quả mới nhất trong ket_qua/.
- Bấm vào một mã CW: trang phân tích chi tiết (biểu đồ, kịch bản lãi/lỗ, so sánh các CW cùng mã cơ sở).
- Trang "Hướng dẫn sử dụng" (/huong-dan): giải thích cho người mới, có trên thanh menu (đầu trang; điện thoại: dưới cùng).
"""

import contextlib
import io
import os
import re
import sys
import webbrowser
from datetime import date
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlsplit

import chiet_khau
import cw_scanner
import danh_muc
import web_chung as W
from web_chung import CONG, doc_von, trang
from web_cw import trang_chi_tiet, trang_chinh, trang_sap_ra_mat
from web_danh_muc import trang_danh_muc
from web_etf import trang_etf, trang_etf_chi_tiet
from web_huong_dan import trang_huong_dan
from web_luot import trang_luot


def nguon_hop_le(headers):
    """Chặn POST từ trang web khác (CSRF): chỉ nhận khi Origin (hoặc Referer) là chính trang này."""
    nguon = headers.get("Origin") or headers.get("Referer") or ""
    host = headers.get("Host") or ""
    goc = [f"http://localhost:{CONG}", f"http://127.0.0.1:{CONG}"]
    if host:
        goc.extend([f"http://{host}", f"https://{host}"])
    return any(nguon == g or nguon.startswith(g + "/") for g in goc)


class XuLy(BaseHTTPRequestHandler):
    def do_GET(self):
        duong_dan = self.path.split("?")[0]
        m = re.fullmatch(r"/cw/([A-Z0-9]{4,12})", duong_dan)  # chỉ nhận mã hợp lệ
        m_etf = re.fullmatch(r"/etf/(" + chiet_khau.MAU_MA_QUY.pattern + ")", duong_dan)
        noi_dung = (
            trang_luot()
            if duong_dan == "/luot-cw"
            else (
                trang_etf()
                if duong_dan == "/etf"
                else (
                    trang_etf_chi_tiet(m_etf.group(1))
                    if m_etf
                    else (
                        trang_chinh()
                        if duong_dan == "/"
                        else (
                            trang_huong_dan()
                            if duong_dan == "/huong-dan"
                            else (
                                trang_danh_muc()
                                if duong_dan == "/danh-muc"
                                else (
                                    trang_sap_ra_mat("tai_moi=1" in self.path)
                                    if duong_dan == "/sap-ra-mat"
                                    else trang_chi_tiet(m.group(1), doc_von(self.path)) if m else None
                                )
                            )
                        )
                    )
                )
            )
        )
        self.send_response(200 if noi_dung else 404)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(
            (
                noi_dung
                or trang("Không tìm thấy", '<h1>Không tìm thấy</h1><p><a href="/">← Về danh sách chứng quyền</a></p>')
            ).encode("utf-8")
        )

    def do_POST(self):
        duong_dan = urlsplit(self.path).path
        if not nguon_hop_le(self.headers):  # trang web lạ không được tự bấm "Quét ngay" hay thêm/xóa lệnh hộ bạn
            self.send_response(403)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write("Từ chối: yêu cầu không gửi từ trang cw_scanner.".encode())
            return
        ve_trang = "/"
        if duong_dan == "/quet":
            bo_dem = io.StringIO()
            try:
                with contextlib.redirect_stdout(bo_dem):  # gom lời nhắn của cw_scanner để hiện lên trang
                    cw_scanner.main()
                W.LOI = ""
            except Exception as e:  # lỗi mạng/API: báo trên trang thay vì làm sập máy chủ  # noqa: BLE001
                W.LOI = f"Lỗi khi quét: {e}"
            W.NHAT_KY = bo_dem.getvalue()
        elif duong_dan in ("/danh-muc/them", "/danh-muc/xoa"):
            ve_trang = "/danh-muc"
            form = parse_qs(self.rfile.read(min(int(self.headers.get("Content-Length") or 0), 10_000)).decode("utf-8"))
            try:
                if duong_dan.endswith("them"):
                    df, _ = W.doc_ket_qua()
                    W.LOI_DANH_MUC = "; ".join(
                        danh_muc.them_lenh(form, set(df["Mã CW"]) if df is not None else set(), date.today())
                    )
                else:
                    so_lenh = (form.get("id") or [""])[0]
                    W.LOI_DANH_MUC = danh_muc.xoa_lenh(int(so_lenh)) if so_lenh.isdigit() else "số lệnh không hợp lệ"
            # vd file danh_muc.csv bị sửa tay sai định dạng: báo lên trang, không ghi gì
            except Exception as e:  # noqa: BLE001
                W.LOI_DANH_MUC = f"Không lưu được: {e}"
        else:
            self.send_error(404)
            return
        self.send_response(303)  # quay về trang để bấm F5 không gửi lại form
        self.send_header("Location", ve_trang)
        self.end_headers()


if __name__ == "__main__":
    # chạy nền không có cửa sổ (Task Scheduler) Windows dùng bảng mã cũ -> in tiếng Việt bị lỗi và dừng chương trình
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]  # stdout luôn là TextIOWrapper
    host_nghe = os.environ.get("HOST", "127.0.0.1")
    may_chu = HTTPServer((host_nghe, CONG), XuLy)
    print(f"Giao diện web: http://{host_nghe}:{CONG}  (Ctrl+C để tắt)")
    if "KHONG_MO_TRINH_DUYET" not in os.environ and not os.environ.get("PORT"):
        webbrowser.open(f"http://localhost:{CONG}")
    may_chu.serve_forever()
