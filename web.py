"""
web.py - Giao diện web cho cw_scanner (chỉ dùng thư viện có sẵn của Python, không cần cài thêm).

Cách chạy:  python web.py   -> trình duyệt tự mở http://localhost:8000
- Nút "🔄 Quét" đầu mỗi tab chạy ở luồng nền phần quét của tab đó (VIEC_QUET); trang Cảnh báo quét tất cả. Đang quét: mọi
  trang hiện màn hình chờ. Luôn hiển thị kết quả mới nhất trong ket_qua/.
- Bấm vào một mã CW: trang phân tích chi tiết (biểu đồ, kịch bản lãi/lỗ, so sánh các CW cùng mã cơ sở).
- Trang "🔔 Cảnh báo giá" (/canh-bao): giá lệch bất thường đang mua được (CW, ETF, HĐTL) + mức giá tự đặt. Mọi trang đang mở
  hỏi /canh-bao/tin mỗi phút trong giờ khớp lệnh: cảnh báo mới thì kêu + thông báo hệ thống + khung đỏ (nút 🔊 trên menu).
- Trang "Hướng dẫn sử dụng" (/huong-dan): giải thích cho người mới, có trên thanh menu (đầu trang; điện thoại: dưới cùng).
"""

import contextlib
import io
import json
import re
import threading
import webbrowser
from datetime import date, datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlsplit

import canh_bao_gia
import chiet_khau
import cw_scanner
import danh_muc
import etf
import phai_sinh
import web_canh_bao
import web_chung as W
from web_chung import CONG, doc_von, trang
from web_cw import trang_chi_tiet, trang_chinh, trang_sap_ra_mat
from web_danh_muc import trang_danh_muc
from web_etf import trang_etf, trang_etf_chi_tiet
from web_huong_dan import trang_huong_dan
from web_phai_sinh import trang_phai_sinh, trang_phai_sinh_chi_tiet

# loại quét (web_chung.NUT_QUET) -> [(tên bước, hàm)]; mọi loại xong đều bỏ giá đã nhớ (bo_bo_nho) nên trang mở lại lấy giá mới.
# Phái sinh, danh mục lấy giá trực tiếp mỗi lần mở trang nên chỉ cần bỏ bộ nhớ.
VIEC_QUET = {
    "cw": [("chứng quyền", cw_scanner.main)],
    "etf": [("ETF", lambda: etf.chay(gui=False))],  # nút quét không gửi Discord
    "phai-sinh": [],
    "danh-muc": [],
}
VIEC_QUET["tat-ca"] = VIEC_QUET["cw"] + VIEC_QUET["etf"]
TAB_QUET = {loai: dd for dd, (loai, *_) in W.NUT_QUET.items()}  # loại quét -> tab hiện kết quả


def bo_bo_nho():
    """Bỏ giá đã nhớ (phái sinh 5 phút, trang cảnh báo, nến, lịch sử IV) để trang mở lại lấy giá mới."""
    for bo_nho in (phai_sinh.BO_NHO, canh_bao_gia.BO_NHO, W.BO_NHO_NEN, W.BO_NHO_IV):
        bo_nho.clear()


def chay_quet():
    """Chạy các bước của lần quét W.QUET (luồng nền); 1 bước lỗi thì ghi lại rồi chạy tiếp bước sau."""
    q, loi = W.QUET, []
    buoc = VIEC_QUET[q["loai"]]
    try:
        # gom lời nhắn để hiện lên trang. shortcut: đổi sys.stdout cả tiến trình, chỉ ổn vì máy chủ không in ra stdout
        with contextlib.redirect_stdout(q["nhat_ky"]):
            for i, (ten, ham) in enumerate(buoc, 1):
                q["buoc"] = ten + (f" (bước {i}/{len(buoc)})" if len(buoc) > 1 else "")
                try:
                    ham()
                # lỗi mạng/API: báo trên trang thay vì làm sập máy chủ
                except (Exception, SystemExit) as e:  # noqa: BLE001
                    loi.append(f"{ten}: {e}")
        bo_bo_nho()
    finally:  # lỗi lạ nào cũng không để mọi trang kẹt ở màn hình chờ
        q.update(dang=False, xong=datetime.now(), loi="; ".join(loi))


def bat_dau_quet(loai):
    """Ghi trạng thái "đang quét" ngay (trang mở sau đó thấy màn hình chờ) rồi chạy ở luồng nền; không có bước thì chạy luôn.
    Máy chủ xử lý từng yêu cầu một nên kiểm W.QUET["dang"] rồi gán không cần khóa. -> luồng nền (test chờ được) hoặc None.
    """
    W.QUET.update(dang=True, loai=loai, tab=TAB_QUET[loai], buoc="", bat_dau=datetime.now(), xong=None, loi="")
    W.QUET["nhat_ky"] = io.StringIO()
    if not VIEC_QUET[loai]:
        chay_quet()
        return None
    luong = threading.Thread(target=chay_quet, daemon=True)
    luong.start()
    return luong


def trang_ve(headers, loai):
    """Trang quay về sau khi bấm Quét: trang đang xem (Referer, đã qua nguon_hop_le); sai dạng thì về tab của loại quét."""
    duong = urlsplit(headers.get("Referer") or "").path
    return duong if re.fullmatch(r"/(?!/)[A-Za-z0-9/_.-]*", duong) else TAB_QUET[loai]


def nguon_hop_le(headers):
    """Chặn POST từ trang web khác (CSRF): chỉ nhận khi Origin (hoặc Referer) là chính trang này."""
    nguon = headers.get("Origin") or headers.get("Referer") or ""
    goc = (f"http://localhost:{CONG}", f"http://127.0.0.1:{CONG}")
    return nguon in goc or nguon.startswith(tuple(g + "/" for g in goc))


class XuLy(BaseHTTPRequestHandler):
    def do_GET(self):
        duong_dan = self.path.split("?")[0]
        if duong_dan == "/luot-cw":  # tab Lướt cũ đã gộp vào trang Chứng quyền (30/10/2026): giữ link cũ dùng được
            self.send_response(301)
            self.send_header("Location", "/#luot")
            self.end_headers()
            return
        if (
            duong_dan == "/canh-bao/tin"
        ):  # mọi trang đang mở hỏi định kỳ (JS trong web_chung) để báo âm thanh + thông báo
            tin = (
                {"ngoai_gio": False, "dang_quet": True, "tin": [], "loi": []}  # không đọc file kết quả đang ghi dở
                if W.QUET["dang"]
                else web_canh_bao.tin_canh_bao()
            )
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(json.dumps(tin, ensure_ascii=False).encode("utf-8"))
            return
        # đang quét: mọi trang (trừ Hướng dẫn) chỉ hiện màn hình chờ, không đọc file kết quả đang ghi dở
        cho = W.trang_cho() if W.QUET["dang"] and duong_dan != "/huong-dan" else None
        m = re.fullmatch(r"/cw/([A-Z0-9]{4,12})", duong_dan)  # chỉ nhận mã hợp lệ
        m_etf = re.fullmatch(r"/etf/(" + chiet_khau.MAU_MA_QUY.pattern + ")", duong_dan)
        m_ps = re.fullmatch(r"/phai-sinh/(" + phai_sinh.MAU_MA_HD.pattern + ")", duong_dan)  # chỉ nhận mã hợp lệ
        noi_dung = cho or (
            web_canh_bao.trang_canh_bao()
            if duong_dan == "/canh-bao"
            else (
                trang_phai_sinh()
                if duong_dan == "/phai-sinh"
                else (
                    trang_phai_sinh_chi_tiet(m_ps.group(1))
                    if m_ps
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
        if not nguon_hop_le(self.headers):  # trang web lạ không được tự bấm "🔄 Quét" hay thêm/xóa lệnh hộ bạn
            self.send_response(403)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write("Từ chối: yêu cầu không gửi từ trang cw_scanner.".encode())
            return
        form = parse_qs(self.rfile.read(min(int(self.headers.get("Content-Length") or 0), 10_000)).decode("utf-8"))
        if W.QUET["dang"] and duong_dan != "/quet":  # thêm/xóa đọc file kết quả đang ghi dở: chờ quét xong
            self.send_response(409)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write("Đang quét dữ liệu nên chưa lưu. Quay lại trang, quét xong thì gửi lại.".encode())
            return
        if duong_dan == "/quet":
            loai = (form.get("loai") or [""])[0]
            if loai not in VIEC_QUET:
                self.send_error(400, "loai quet khong hop le")
                return
            ve_trang = trang_ve(self.headers, loai)
            if not W.QUET["dang"]:  # bấm thêm lúc đang quét: không chạy lần nữa
                bat_dau_quet(loai)
        elif duong_dan in ("/danh-muc/them", "/danh-muc/xoa"):
            ve_trang = "/danh-muc"
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
        elif duong_dan in ("/canh-bao/them", "/canh-bao/xoa"):
            ve_trang = "/canh-bao"
            try:
                if duong_dan.endswith("them"):
                    web_canh_bao.LOI_MUC_GIA = "; ".join(canh_bao_gia.them_muc_gia(form, date.today()))
                else:
                    so_muc = (form.get("id") or [""])[0]
                    web_canh_bao.LOI_MUC_GIA = (
                        canh_bao_gia.xoa_muc_gia(int(so_muc)) if so_muc.isdigit() else "số mức không hợp lệ"
                    )
            # muc_gia.csv sửa tay sai định dạng, mất mạng khi kiểm mã: báo lên trang, không ghi gì
            except Exception as e:  # noqa: BLE001
                web_canh_bao.LOI_MUC_GIA = f"Không lưu được: {e}"
        else:
            self.send_error(404)
            return
        self.send_response(303)  # quay về trang để bấm F5 không gửi lại form
        self.send_header("Location", ve_trang)
        self.end_headers()


if __name__ == "__main__":
    # Chỉ mở cho máy của bạn (127.0.0.1), người khác trong mạng không truy cập được
    may_chu = HTTPServer(("127.0.0.1", CONG), XuLy)
    print(f"Giao diện web: http://localhost:{CONG}  (Ctrl+C để tắt)")
    webbrowser.open(f"http://localhost:{CONG}")
    may_chu.serve_forever()
