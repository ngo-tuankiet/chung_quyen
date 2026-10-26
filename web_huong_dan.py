"""Trang Hướng dẫn sử dụng (/huong-dan)."""

import chiet_khau
import cw_scanner
import web_chung as W  # doc_ket_qua và trạng thái LOI/NHAT_KY/LOI_DANH_MUC đọc qua module: test patch được, handler gán được
from web_chung import COT, ESC, KET_LUAN, huy_hieu, so, trang


# ============ TRANG HƯỚNG DẪN ============
def trang_huong_dan():
    """Hướng dẫn cho người mới: CW là gì, cách dùng trang, ý nghĩa các con số, việc cần làm trước khi mua."""
    C = cw_scanner
    df, _ = W.doc_ket_qua()
    tot = df[df["Đánh giá"] == "NÊN XEM XÉT"] if df is not None else None
    vi_du = (
        f' Xem thử một ví dụ thật: <a href="/cw/{ESC(tot["Mã CW"].iloc[0])}">{ESC(tot["Mã CW"].iloc[0])}</a>.'
        if tot is not None and len(tot)
        else ""
    )
    muc = [
        ("cong-cu", "Công cụ này làm gì?"),
        ("cw-la-gi", "Chứng quyền là gì? (1 phút)"),
        ("5-buoc", "Dùng trang web trong 5 bước"),
        ("tieu-chi", "4 tiêu chí chấm điểm"),
        ("cac-cot", "Ý nghĩa từng cột trong bảng"),
        ("trang-phan-tich", "Đọc trang phân tích một mã"),
        ("gia-hop-ly", "Giá hợp lý được tính thế nào?"),
        ("truoc-khi-mua", "5 câu tự hỏi trước khi mua"),
        ("etf", "Trang 📊 ETF: mua quỹ dưới NAV"),
        ("hoi-dap", "Câu hỏi thường gặp"),
    ]
    phan = [
        '<div class="huong-dan"><h1>Hướng dẫn sử dụng</h1><p class="phu">Đọc lần lượt từ trên xuống, khoảng 5 phút. '
        "Không cần biết lập trình hay công thức toán.</p>"
        '<nav class="the" aria-label="Mục lục"><h2>Mục lục</h2><ol class="muc-luc">'
        + "".join(f'<li><a href="#{a}">{t}</a></li>' for a, t in muc)
        + "</ol></nav>"
    ]

    phan.append(
        '<section class="the" id="cong-cu"><h2>1. Công cụ này làm gì?</h2>'
        "<p>Mỗi lần bạn bấm <b>Quét ngay</b>, chương trình tải giá của <b>tất cả chứng quyền đang niêm yết trên HOSE</b>, "
        "tính <b>giá hợp lý</b> của từng mã bằng công thức Black-Scholes, rồi chấm điểm theo 4 tiêu chí để bạn biết "
        "<b>nên xem kỹ mã nào</b> và <b>nên bỏ qua mã nào</b>.</p>"
        "<p>Chương trình <b>không mua bán giúp bạn</b>, <b>không dự báo cổ phiếu sẽ tăng hay giảm</b>, và <b>không phải lời khuyên đầu tư</b>. "
        'Nó giúp bạn trả lời câu hỏi: <i>"Nếu tôi đã muốn đặt cược vào cổ phiếu X, thì chứng quyền nào của X đang có giá tốt?"</i></p></section>'
    )

    phan.append(
        '<section class="the" id="cw-la-gi"><h2>2. Chứng quyền là gì? (1 phút)</h2><ul>'
        "<li>Mua chứng quyền (CW) = trả một khoản tiền nhỏ để được hưởng <b>phần tăng giá của một cổ phiếu</b> "
        "(gọi là <b>cổ phiếu cơ sở</b>) vượt trên một mức gọi là <b>giá thực hiện</b>, tính vào <b>ngày đáo hạn</b>.</li>"
        "<li><b>Ví dụ:</b> CW của VPB có giá thực hiện 22.605 đ, tỷ lệ chuyển đổi 1,5863 CW : 1 cổ phiếu. "
        "Nếu ngày đáo hạn VPB là 26.000 đ, mỗi CW nhận về (26.000 − 22.605) ÷ 1,5863 ≈ <b>2.140 đ</b>. "
        "Nếu VPB dưới 22.605 đ, CW <b>về 0 đ</b>.</li>"
        "<li><b>Lỗ tối đa</b> = toàn bộ tiền bạn bỏ ra mua CW. Không bao giờ lỗ nhiều hơn số đó.</li>"
        "<li><b>Lãi có thể gấp nhiều lần</b> nhờ <b>đòn bẩy</b>: cổ phiếu tăng 10% thì CW có thể tăng 50-100%.</li>"
        "<li><b>CW mất giá dần theo thời gian</b>: nếu cổ phiếu đứng yên, giá CW giảm dần mỗi ngày đến ngày đáo hạn.</li>"
        "<li>CW ngừng giao dịch <b>2 phiên trước ngày đáo hạn</b>. Nếu còn giữ đến đáo hạn, bạn nhận tiền mặt (không nhận cổ phiếu).</li>"
        "</ul></section>"
    )

    phan.append(
        '<section class="the" id="5-buoc"><h2>3. Dùng trang web trong 5 bước</h2><ol>'
        '<li><b>Bấm "Quét ngay"</b> ở <a href="/">trang chính</a> và chờ 1-3 phút. Nên quét <b>sau 15:00</b> các ngày giao dịch để có giá đóng cửa.</li>'
        "<li><b>Xem 4 ô số</b> ở đầu trang: có bao nhiêu mã <i>Nên xem xét</i>, <i>Theo dõi</i>, <i>Bỏ qua</i> và bao nhiêu mã mới phát hành.</li>"
        '<li><b>Xem bảng "Nên xem xét"</b>: đây là các mã đạt cả 4 tiêu chí. '
        '<b>Bấm vào tiêu đề cột để sắp xếp</b> (ví dụ bấm "So với giá hợp lý" để mã rẻ nhất lên đầu). '
        'Muốn tìm CW của một cổ phiếu cụ thể, gõ mã (VPB, HPG…) vào <b>ô tìm kiếm</b> của bảng "Tất cả".</li>'
        f"<li><b>Bấm vào một mã CW</b> để mở trang phân tích chi tiết (xem mục 6).{vi_du}</li>"
        "<li><b>Tự trả lời 5 câu hỏi</b> ở mục 8 rồi mới quyết định mua hay không. Đặt lệnh qua ứng dụng của công ty chứng khoán bạn đang dùng.</li>"
        '</ol><p class="phu">Mẹo: rê chuột lên tiêu đề cột bất kỳ để xem giải thích ngắn của cột đó.</p></section>'
    )

    phan.append(
        '<section class="the" id="tieu-chi"><h2>4. Bốn tiêu chí chấm điểm</h2><div class="cuon"><table class="bang-chu"><thead><tr>'
        "<th>Tiêu chí</th><th>Mức đang dùng</th><th>Vì sao quan trọng</th></tr></thead><tbody>"
        f"<tr><td>Thời gian còn lại</td><td>≥ {C.MIN_NGAY_CON_LAI} ngày</td><td>Gần ngày đáo hạn, CW mất giá rất nhanh và ít thời gian để cổ phiếu tăng.</td></tr>"
        f"<tr><td>Biến động ngầm định so với lịch sử (IV − HV)</td><td>≤ {so(C.MAX_IV_TRU_HV * 100, 0, True)} điểm</td><td>Không trả cho mức dao động "
        'cao hơn hẳn 1 năm qua (tính theo giá mua = giá chào bán thấp nhất). Dùng IV thay cho "% đắt hơn giá hợp lý" vì cùng đắt 10% về giá, '
        "CW ngoài tiền chỉ tương đương khoảng +1,6 điểm IV còn CW sâu trong tiền tới khoảng +14 điểm; mức +3 điểm tương đương đắt 10% ở CW quanh tiền. "
        "CW có giá mua dưới mức tối thiểu của mô hình (không giải được IV) được tính là đạt, kèm cảnh báo.</td></tr>"
        f"<tr><td>Mức tăng cần để hòa vốn</td><td>≤ {C.MAX_TANG_DE_HOA_VON:.0%}</td><td>Mục tiêu phải thực tế: cổ phiếu tăng vài % dễ hơn nhiều so với tăng 30%.</td></tr>"
        f"<tr><td>Thanh khoản</td><td>≥ {so(C.MIN_KHOI_LUONG)} CW khớp/phiên</td><td>Đủ người mua bán thì bạn mới bán ra được đúng giá khi cần.</td></tr>"
        "</tbody></table></div><p>"
        + " · ".join(
            f"{huy_hieu(k)} {m}" for k, m in zip(KET_LUAN, ("đạt cả 4", "trượt 1 tiêu chí", "trượt từ 2 tiêu chí"))
        )
        + '</p><p class="phu">Muốn đổi các mức trên: mở file <code>cw_scanner.py</code>, sửa phần <b>CẤU HÌNH</b> ở đầu file, lưu lại rồi bấm Quét ngay.</p></section>'
    )

    phan.append(
        '<section class="the" id="cac-cot"><h2>5. Ý nghĩa từng cột trong bảng</h2><div class="cuon"><table class="bang-chu">'
        "<thead><tr><th>Cột</th><th>Ý nghĩa</th></tr></thead><tbody>"
        + "".join(f"<tr><td><b>{ten}</b></td><td>{ESC(gt)}</td></tr>" for ten, _, gt in COT)
        + "</tbody></table></div></section>"
    )

    phan.append(
        '<section class="the" id="trang-phan-tich"><h2>6. Đọc trang phân tích một mã</h2><ul>'
        "<li><b>Tóm tắt</b>: đọc đoạn này trước. Nó nói bạn trả bao nhiêu, cổ phiếu phải lên mức nào mới có lãi, và mỗi ngày CW mất bao nhiêu tiền. "
        "Bên dưới là 4 tiêu chí với dấu ✓ (đạt) hoặc ✕ (không đạt).</li>"
        "<li><b>Giá trị nội tại và giá trị thời gian</b>: giá CW = phần lãi nếu đáo hạn ngay hôm nay (<i>nội tại</i>) + phần trả thêm cho thời gian còn lại "
        "(<i>thời gian</i>). Phần thời gian luôn giảm về 0 vào ngày đáo hạn. Phần này càng nhỏ, bạn càng ít mất tiền do thời gian.</li>"
        "<li><b>Điểm hòa vốn</b>: giá cổ phiếu cần đạt vào ngày đáo hạn để bạn không lỗ không lãi.</li>"
        "<li><b>📐 Giá hợp lý … được tính thế nào?</b>: bấm vào để xem 7 bước tính giá hợp lý bằng số thật của mã đó, "
        "kèm phần kiểm chứng bằng 20.000 kịch bản (xem thêm mục 7).</li>"
        "<li><b>Khối lượng CW</b>: tổng số CW phát hành, số CW <b>đang chào bán</b> (lượng bạn mua được ngay và giá thấp nhất), "
        "số CW đang chờ mua (lượng bán ra được ngay) và sổ lệnh 3 mức giá, tải trực tiếp lúc mở trang.</li>"
        "<li><b>Đòn bẩy</b>: ví dụ 9x nghĩa là cổ phiếu tăng 1% thì CW tăng khoảng 9%, cổ phiếu giảm 1% thì CW giảm khoảng 9%.</li>"
        '<li><b>Delta</b> (từ 0 đến 1): mức CW "chạy theo" cổ phiếu. Ô này ghi sẵn cổ phiếu tăng/giảm 1.000 đ thì 1 CW tăng/giảm khoảng bao nhiêu đồng. '
        "Delta gần 1: CW bám sát cổ phiếu; gần 0: CW gần như không phản ứng (thường do giá cổ phiếu còn xa dưới giá thực hiện).</li>"
        '<li><b>Biến động ngầm định (IV)</b>: mức dao động mà giá mua CW đang "giả định". So với mức dao động thật 1 năm qua (HV): '
        '<b>IV − HV</b> âm → CW đang rẻ, dương → đắt. Khác với "% so với giá hợp lý", con số này so sánh được giữa các CW ở gần và xa giá thực hiện, '
        f'nên bảng xếp theo nó và dùng nó làm tiêu chí (≤ {so(C.MAX_IV_TRU_HV * 100, 0, True)} điểm). "—" nghĩa là không giải được, thường do giá mua thấp hơn <b>mức tối thiểu</b> S − K × e<sup>−rT</sup> của mô hình '
        '(có khung ⚠ Lưu ý): khi đó chữ "Rẻ" chủ yếu đến từ giả định lãi suất và mức dao động, không chắc là món hời.</li>'
        "<li><b>Biểu đồ</b>: đường xanh là giá cổ phiếu 1 năm qua; đường xám là giá thực hiện; đường cam là <b>điểm hòa vốn</b>. "
        "Muốn có lãi khi giữ đến đáo hạn, giá cổ phiếu phải <b>nằm trên đường cam</b>. Rê chuột (hoặc bấm vào biểu đồ rồi dùng phím ← →) để xem giá từng ngày.</li>"
        '<li><b>Bảng "Nếu giữ đến ngày đáo hạn"</b>: xem trước lãi/lỗ theo từng kịch bản cổ phiếu tăng/giảm. '
        "Nhìn dòng <b>−10%</b> và <b>−20%</b> để biết <b>kịch bản xấu</b>, cột cuối cho biết lãi/lỗ theo số tiền bạn nhập ở mục <b>Rủi ro với số tiền của bạn</b>.</li>"
        "<li><b>Rủi ro với số tiền của bạn</b>: nhập số tiền định bỏ ra để xem mua được bao nhiêu CW, tương đương nắm bao nhiêu tiền cổ phiếu "
        "(thường gấp 5-15 lần), cổ phiếu giảm đến đâu thì mất toàn bộ, ngày cuối cùng còn bán được và điểm hòa vốn sau phí, thuế.</li>"
        '<li><b>IV theo thời gian</b>: biểu đồ mức dao động mà giá CW "giả định" từng ngày từ lúc lên sàn. IV thường cao lúc mới phát hành rồi '
        "giảm dần. Đáng chú ý khi IV xuống thấp hẳn dưới HV và trung vị các CW cùng mã (ví dụ CVPB2608, CVPB2615 của ACBS tháng 10/2026): "
        "tổ chức phát hành đang bán ra rẻ, nên giá có thể còn thấp nữa trước khi đáo hạn.</li>"
        "<li>Mọi con số ở trang phân tích được <b>tính lại theo giá trực tiếp</b> lúc mở trang (dòng đầu trang ghi giờ lấy giá). "
        "Kết luận có thể khác bảng ở trang chính (bảng đó là số lúc quét).</li>"
        "<li><b>Các CW khác của cùng cổ phiếu</b>: cùng đặt cược vào một cổ phiếu, hãy so để chọn CW rẻ hơn, còn nhiều ngày hơn hoặc dễ hòa vốn hơn.</li>"
        "<li>Khung màu vàng <b>⚠ Bất thường</b> (nếu có): giá CW thấp hơn cả giá trị nội tại. Hãy đọc thông báo của tổ chức phát hành trước khi mua.</li>"
        "</ul></section>"
    )

    phan.append(
        '<section class="the" id="gia-hop-ly"><h2>7. Giá hợp lý được tính thế nào? (nói đơn giản)</h2>'
        "<p><b>Ý tưởng:</b> tưởng tượng hàng nghìn kịch bản giá cổ phiếu có thể xảy ra đến ngày đáo hạn (cổ phiếu dao động mạnh hay yếu "
        "giống như 1 năm qua). Trong mỗi kịch bản, CW trả một số tiền hoặc về 0. <b>Giá hợp lý = trung bình số tiền đó, quy về tiền hôm nay.</b> "
        "Công thức Black-Scholes là cách tính nhanh ra con số trung bình này mà không cần thử từng kịch bản.</p>"
        "<p><b>Ví dụ dễ hình dung:</b> cổ phiếu giá 100 đ, giá thực hiện 100 đ, tỷ lệ 1 : 1.</p><ul>"
        "<li>Nếu đến ngày đáo hạn cổ phiếu chỉ có thể là <b>90 hoặc 110</b> (mỗi khả năng một nửa): CW trả 0 hoặc 10 → trung bình <b>5 đ</b>.</li>"
        "<li>Nếu cổ phiếu dao động mạnh hơn, là <b>70 hoặc 130</b>: CW trả 0 hoặc 30 → trung bình <b>15 đ</b>.</li></ul>"
        "<p>Cùng một cổ phiếu, dao động mạnh hơn thì CW đáng giá gấp 3. Lý do: lỗ tối đa chỉ là tiền mua CW, còn lãi thì không giới hạn.</p>"
        "<p><b>Công thức viết bằng lời:</b></p>"
        '<p class="cong-thuc">Giá hợp lý 1 CW = ( Giá cổ phiếu × A − Giá thực hiện × B ) ÷ Tỷ lệ chuyển đổi</p><ul>'
        '<li><b>Giá cổ phiếu × A</b> = phần bạn "nhận được"; <b>Giá thực hiện × B</b> = phần bạn "phải trả". Chênh lệch là giá trị của quyền.</li>'
        "<li><b>A</b> và <b>B</b> là hai hệ số từ 0 đến 1. <b>B</b> gần bằng <b>xác suất</b> đến ngày đáo hạn giá cổ phiếu vẫn trên giá thực hiện.</li>"
        "<li>A và B được tính từ 3 câu hỏi: giá đang cách giá thực hiện bao xa? còn bao nhiêu thời gian? cổ phiếu hay dao động cỡ nào?</li></ul>"
        "<p><b>3 quy luật dễ nhớ – CW đáng giá hơn khi:</b></p><ol>"
        "<li>Giá cổ phiếu <b>càng cao hơn</b> giá thực hiện.</li><li><b>Còn càng nhiều thời gian</b> đến ngày đáo hạn.</li>"
        "<li>Cổ phiếu <b>càng hay dao động mạnh</b> (như ví dụ trên).</li></ol>"
        f'<p>Muốn xem <b>từng bước tính bằng số thật</b>: mở trang phân tích một mã bất kỳ, bấm mục <b>"📐 Giá hợp lý … được tính thế nào?"</b>.{vi_du}</p></section>'
        '<section class="the" id="truoc-khi-mua"><h2>8. Năm câu tự hỏi trước khi mua</h2><ol>'
        "<li><b>Tôi có lý do tin cổ phiếu cơ sở sẽ lên trên điểm hòa vốn trước ngày đáo hạn không?</b> "
        "Công cụ chỉ cho biết CW đắt hay rẻ, không cho biết cổ phiếu sẽ tăng.</li>"
        "<li><b>Nếu cổ phiếu giảm 10-20%, tôi mất bao nhiêu?</b> Xem bảng kịch bản. Có thể mất gần hết tiền mua CW.</li>"
        f"<li><b>Còn đủ thời gian không?</b> Ưu tiên CW còn trên {C.MIN_NGAY_CON_LAI} ngày.</li>"
        "<li><b>Có CW nào khác của cùng cổ phiếu tốt hơn không?</b> Xem bảng so sánh ở cuối trang phân tích.</li>"
        "<li><b>Nếu mất hết số tiền này, tôi vẫn ổn chứ?</b> Chỉ dùng phần tiền bạn chấp nhận mất.</li></ol>"
        "<p><b>Khi đặt lệnh:</b> dùng <b>lệnh giới hạn (LO)</b> với mức giá bạn muốn thay vì mua bằng mọi giá; kiểm tra lại điều khoản CW "
        "trên website tổ chức phát hành / HOSE; ghi nhớ ngày giao dịch cuối cùng (2 phiên trước ngày đáo hạn).</p></section>"
    )

    hoi_dap = [
        (
            "Vì sao quét mất 1-3 phút?",
            "Gói miễn phí của vnstock giới hạn số lượt lấy dữ liệu mỗi phút, chương trình tự chờ rồi chạy tiếp. Có API key hợp lệ thì nhanh hơn.",
        ),
        (
            "Nhật ký có dòng [!] … số thiết bị tối đa?",
            "Tài khoản vnstock của bạn đã dùng hết số máy được phép. Vào trang tài khoản trên vnstocks.com để gỡ thiết bị cũ. Trong lúc đó chương trình vẫn quét được, chỉ chậm hơn.",
        ),
        (
            "Dữ liệu được cập nhật khi nào?",
            "Mỗi lần bấm Quét ngay. Ngày của dữ liệu ghi ở đầu trang chính. Giá trong ngày thay đổi liên tục nên hãy quét lại trước khi đặt lệnh.",
        ),
        (
            'Chữ "Mới" cạnh mã CW là gì?',
            "CW chưa có ở lần quét trước, tức là mới niêm yết. Lần quét đầu tiên chưa đánh dấu mã nào.",
        ),
        (
            "Xem số CW đã bán ra và còn lại ở đâu?",
            (
                "Các nguồn dữ liệu miễn phí chỉ công bố tổng khối lượng phát hành, không công bố nhà đầu tư đang nắm bao nhiêu. "
                'Trang phân tích mỗi mã có mục "Khối lượng CW": khối lượng phát hành, số CW đang chào bán (lượng mua được ngay), đang chờ mua và sổ lệnh 3 mức giá, '
                'tải trực tiếp lúc mở trang. Cột "Đang chào bán" trong bảng là số liệu lúc quét.'
            ),
        ),
        (
            "Vì sao dùng giá chào bán (giá mua) chứ không dùng giá khớp?",
            (
                "Muốn mua ngay, bạn phải trả giá thấp nhất đang chào bán, thường cao hơn giá khớp gần nhất "
                "(có mã cao hơn hơn 10%). Định giá theo giá khớp có thể làm CW trông rẻ hơn thực tế. Khi sổ lệnh trống (trước giờ giao dịch), chương trình "
                'dùng giá khớp hoặc giá tham chiếu và ghi chữ nhỏ "khớp" / "TC" cạnh giá.'
            ),
        ),
        (
            '"Đắt > 1.000%" là sao?',
            "CW gần hết hạn và giá cổ phiếu còn quá xa giá thực hiện, nên giá hợp lý gần 0 đ. Gần như chắc chắn nên bỏ qua.",
        ),
        (
            '"Giá hợp lý" có chắc đúng không?',
            "Không. Nó dựa trên giả định mức dao động của cổ phiếu 1 năm qua sẽ lặp lại. Hãy coi nó là một ý kiến tham khảo, không phải sự thật.",
        ),
        (
            "Theo dõi CW đang nắm ở đâu?",
            (
                'Trang "💼 Danh mục": nhập lệnh mua/bán, xem lãi/lỗ nếu bán ngay, mức tiếp xúc với từng cổ phiếu cơ sở và '
                "cảnh báo. Có DISCORD_WEBHOOK_URL trong file .env thì cảnh báo được gửi lên Discord (chỉ mã, %, giá, lý do; không gửi số tiền) khi vừa xuất hiện: "
                "còn ít ngày tới ngày giao dịch cuối, cổ phiếu gần giá thực hiện, chạm chốt lời/cắt lỗ, không ai đặt mua, IV bất thường, phát hành thêm."
            ),
        ),
        (
            "Tắt chương trình thế nào?",
            "Đóng cửa sổ Terminal (Mac) hoặc cửa sổ đen (Windows), hoặc nhấn Ctrl + C trong cửa sổ đó.",
        ),
    ]
    phan.append(
        '<section class="the" id="etf"><h2>9. Trang 📊 ETF: mua quỹ dưới NAV</h2><ul>'
        "<li><b>ETF</b> là quỹ mua cả rổ cổ phiếu theo một chỉ số (vd VN30), giao dịch trên sàn như cổ phiếu. <b>NAV</b> là giá trị "
        "thật của rổ cổ phiếu chia cho mỗi chứng chỉ quỹ.</li>"
        "<li>Giá quỹ trên sàn có lúc thấp hơn NAV (<b>chiết khấu</b>). Mua lúc chiết khấu rồi bán khi giá về sát NAV thì có lời, "
        "dù chỉ số đứng yên.</li>"
        f"<li>Bảng <b>Chiết khấu so với NAV</b>: 🟢 = lãi ròng nếu mua ở giá chào bán rồi bán đúng NAV ≥ "
        f"{chiet_khau.NGUONG_LAI_RONG:.0%} (sau phí, thuế) và mua được ≥ {so(chiet_khau.MIN_GIA_TRI_CHAO_BAN / 1e6)} triệu.</li>"
        "<li>Xem cột <b>Thường lệch</b>: quỹ ít giao dịch có thể chiết khấu rất lâu, giá không chắc quay về NAV. Đó không phải món hời.</li>"
        "<li>Dữ liệu tự cập nhật 9:40 thứ Hai–Sáu. Bấm vào một quỹ để xem biểu đồ giá và chênh lệch so với NAV.</li></ul></section>"
    )
    phan.append(
        '<section class="the" id="hoi-dap"><h2>10. Câu hỏi thường gặp</h2>'
        + "".join(
            f'<details style="margin-top:10px"><summary>{ESC(q)}</summary><p>{ESC(a)}</p></details>' for q, a in hoi_dap
        )
        + "</section></div>"
    )
    return trang("Hướng dẫn sử dụng", "".join(phan), "/huong-dan")
