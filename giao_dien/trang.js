
// Báo cảnh báo mới (kêu + thông báo hệ thống + khung đỏ): hỏi /canh-bao/tin mỗi data-giay giây (máy chủ chỉ tính trong giờ
// khớp lệnh). Nhiều tab: tab hỏi trước thì tab khác bỏ lượt. Bật/tắt, đã báo, chưa xem: nhớ trong trình duyệt (localStorage).
(() => {
  const nut = document.getElementById("nut-bao");
  if (!nut) return;
  const doc = k => { try { return localStorage.getItem(k); } catch (e) { return null; } };
  const ghi = (k, v) => { try { localStorage.setItem(k, v); } catch (e) {} };
  const ds = k => { try { return JSON.parse(doc(k) || "[]"); } catch (e) { return []; } };
  const giay = +nut.dataset.giay, toi_da = +nut.dataset.toiDa, goc = document.title;
  const bat = () => doc("bao_dong") !== "tat";
  let am = null, nhay = null;
  const mo_am = () => {  // trình duyệt chỉ cho phát tiếng sau khi người dùng bấm vào trang ít nhất 1 lần
    try { am = am || new (window.AudioContext || window.webkitAudioContext)(); if (am.state === "suspended") am.resume(); } catch (e) {}
  };
  const keu = () => {  // 2 lần "ting-tong", tạo bằng trình duyệt (không cần file âm thanh)
    mo_am();
    if (!am) return;
    [[880, 0], [660, .3], [880, .75], [660, 1.05]].forEach(([tan_so, t]) => {
      const o = am.createOscillator(), g = am.createGain(), t0 = am.currentTime + t;
      o.frequency.value = tan_so; o.connect(g); g.connect(am.destination);
      g.gain.setValueAtTime(.0001, t0); g.gain.exponentialRampToValueAtTime(.3, t0 + .02); g.gain.exponentialRampToValueAtTime(.0001, t0 + .28);
      o.start(t0); o.stop(t0 + .3);
    });
  };
  const ve = () => {  // khung đỏ + tiêu đề tab nhấp nháy theo danh sách chưa xem (giữ qua các trang, tới khi bấm "Đã xem")
    const chua = ds("bao_chua_xem");
    document.getElementById("khung-bao")?.remove();
    clearInterval(nhay);
    document.title = goc;
    if (!chua.length) return;
    const k = document.createElement("section");
    k.id = "khung-bao";
    k.setAttribute("role", "alert");
    k.innerHTML = '<b></b><ul></ul><p class="phu" hidden>Chưa phát được tiếng: bấm vào trang một lần để trình duyệt cho phép.</p>'
      + '<button type="button" class="nut">Đã xem</button>';
    k.querySelector("b").textContent = `🔔 ${chua.length} cảnh báo mới`;
    chua.forEach(t => {
      const li = document.createElement("li"), a = document.createElement("a");
      a.href = t.link; a.textContent = t.tieu_de;
      li.append(a, ": " + t.noi_dung);
      k.querySelector("ul").append(li);
    });
    k.querySelector("button").addEventListener("click", () => { ghi("bao_chua_xem", "[]"); ve(); });
    document.body.append(k);
    setTimeout(() => { k.querySelector("p").hidden = !bat() || (am && am.state === "running"); }, 500);
    let sang = false;
    nhay = setInterval(() => { document.title = (sang = !sang) ? `🔔 (${chua.length}) Cảnh báo mới` : goc; }, 1000);
  };
  const bao = moi => {
    ghi("bao_chua_xem", JSON.stringify(ds("bao_chua_xem").concat(moi).slice(-30)));
    ve();
    keu();
    if ("Notification" in window && Notification.permission === "granted") {
      moi.slice(0, toi_da).forEach(t => {
        const n = new Notification("🔔 " + t.tieu_de, { body: t.noi_dung, tag: t.id });
        n.onclick = () => { window.focus(); location.href = t.link; };
      });
    }
  };
  const hoi = () => {
    if (!bat() || Date.now() - (+doc("bao_lan_hoi") || 0) < (giay - 5) * 1000) return;  // tắt, hoặc tab khác vừa hỏi
    ghi("bao_lan_hoi", Date.now());
    fetch("/canh-bao/tin", { cache: "no-store" }).then(r => r.json()).then(d => {
      const da = ds("bao_da_bao"), moi = d.tin.filter(t => !da.includes(t.id));
      if (!moi.length) return;
      const ngay = moi[0].id.split("|")[0];  // id "ngày|loại|mã": mỗi tin báo 1 lần/ngày, bỏ id ngày cũ
      ghi("bao_da_bao", JSON.stringify(da.filter(id => id.startsWith(ngay)).concat(moi.map(t => t.id))));
      bao(moi);
    }).catch(() => {});  // máy chủ tắt / mất mạng: lượt sau hỏi lại
  };
  const cap_nhat_nut = () => {
    nut.querySelector(".bt").textContent = bat() ? "🔊" : "🔇";
    nut.querySelector(".chu").textContent = bat() ? "Báo: bật" : "Báo: tắt";
    nut.setAttribute("aria-pressed", bat());
  };
  nut.addEventListener("click", () => {
    ghi("bao_dong", bat() ? "tat" : "bat");
    cap_nhat_nut();
    if (!bat()) return;
    keu();  // nghe thử; bấm nút cũng là lần bấm cho phép phát tiếng
    if ("Notification" in window && Notification.permission === "default") Notification.requestPermission();
  });
  ["pointerdown", "keydown"].forEach(su_kien => document.addEventListener(su_kien, mo_am, { once: true }));
  window.addEventListener("storage", e => { if (e.key === "bao_chua_xem") ve(); });  // "Đã xem" ở tab khác
  cap_nhat_nut();
  ve();
  hoi();
  setInterval(hoi, 10000);
})();
// Bấm vào cả dòng để mở trang chi tiết (đường link trong ô mã vẫn dùng được bằng bàn phím)
document.querySelectorAll("tr[data-href]").forEach(tr => tr.addEventListener("click", e => {
  if (!e.target.closest("a")) location.href = tr.dataset.href;
}));
// Bấm tiêu đề cột để sắp xếp tăng dần, bấm lần nữa để đảo chiều. Ô có data-v thì so số gốc, còn lại so chữ
document.querySelectorAll("th button").forEach(nut => nut.addEventListener("click", () => {
  const th = nut.parentElement, bang = th.closest("table"), cot = th.cellIndex;
  const tang = th.getAttribute("aria-sort") !== "ascending";
  bang.querySelectorAll("th").forEach(o => o.removeAttribute("aria-sort"));
  th.setAttribute("aria-sort", tang ? "ascending" : "descending");
  const gt = tr => tr.cells[cot].dataset.v ?? tr.cells[cot].textContent.trim();
  const dong = [...bang.tBodies[0].rows].sort((a, b) => {
    const x = gt(a), y = gt(b), kq = isNaN(x) || isNaN(y) ? x.localeCompare(y, "vi") : x - y;
    return tang ? kq : -kq;
  });
  bang.tBodies[0].append(...dong);
}));
// Ô tìm kiếm: ẩn các dòng không chứa chữ cần tìm
// biểu đồ nến: thanh dọc theo chuột / ngón tay (như TradingView) + dòng thông số của nến đang trỏ. Các biểu đồ cùng khung trong
// 1 mục (CW và CS, chung trục) chạy cùng nhau. Rời chuột thì về nến cuối. Phím ← → khi biểu đồ được chọn.
const nenCung = el => el.closest("section").querySelectorAll(`.khung-nen[data-khung="${el.closest(".khung-nen").dataset.khung}"] .nen-tuong-tac`);
const chiNen = (el, i) => nenCung(el).forEach(k => {
  const n = k.querySelectorAll(".nen-chu-giai > span"), cuoi = n.length - 1, j = i == null ? cuoi : Math.max(0, Math.min(cuoi, i));
  n.forEach((s, m) => { s.hidden = m !== j; });
  const v = k.querySelector(".vach-doc"), x = +k.dataset.x0 + (j + 0.5) * +k.dataset.rong;
  v.setAttribute("x1", x); v.setAttribute("x2", x); v.setAttribute("visibility", i == null ? "hidden" : "visible");
  k.dataset.i = i == null ? "" : j;
});
document.querySelectorAll(".nen-tuong-tac").forEach(k => {
  const svg = k.querySelector("svg");
  const viTri = e => { const r = svg.getBoundingClientRect(); return Math.floor(((e.clientX - r.left) / r.width * +k.dataset.r - +k.dataset.x0) / +k.dataset.rong); };
  svg.addEventListener("pointermove", e => chiNen(k, viTri(e)));
  svg.addEventListener("pointerdown", e => chiNen(k, viTri(e)));
  svg.addEventListener("pointerleave", () => chiNen(k, null));
  svg.addEventListener("keydown", e => {
    if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
    e.preventDefault();
    const n = k.querySelectorAll(".nen-chu-giai > span").length, i = k.dataset.i === "" || k.dataset.i == null ? n - 1 : +k.dataset.i;
    chiNen(k, i + (e.key === "ArrowLeft" ? -1 : 1));
  });
  svg.addEventListener("blur", () => chiNen(k, null));
});
// thanh ngang + thước đo: trong vùng giá, đường ngang và nhãn giá tại con trỏ (bên phải); giữ chuột / ngón tay kéo -> vùng đo
// từ điểm bắt đầu tới con trỏ: % thay đổi, chênh lệch giá (đ), số nến (như công cụ đo của TradingView). Thả ra vẫn giữ
// vùng đo; bấm (không kéo) hoặc Esc để xóa.
const soVN = (v, le = 0) => v.toLocaleString("vi-VN", { minimumFractionDigits: le, maximumFractionDigits: le });
document.querySelectorAll(".nen-tuong-tac").forEach(k => {
  const svg = k.querySelector("svg"), d = k.dataset, q = s => svg.querySelector(s), td = q(".thuoc-do");
  const toaDo = e => { const r = svg.getBoundingClientRect(); return [(e.clientX - r.left) / r.width * +d.r, (e.clientY - r.top) / r.height * +d.c]; };
  const kep = y => Math.max(+d.tren, Math.min(+d.tren + +d.nenCao, y));
  const giaTai = y => +d.giaCao - (kep(y) - +d.tren) / +d.nenCao * (+d.giaCao - +d.giaThap);
  const trongGia = y => y >= +d.tren && y <= +d.tren + +d.nenCao;
  const nenTai = x => Math.floor((x - +d.x0) / +d.rong);
  const dat = (el, o) => Object.entries(o).forEach(([a, v]) => el.setAttribute(a, v));
  let dau = null;
  const ngang = y => {
    const l = q(".vach-ngang"), n = q(".nhan-con-tro"), hien = trongGia(y) ? "visible" : "hidden";
    l.setAttribute("visibility", hien); n.setAttribute("visibility", hien);
    if (hien === "hidden") return;
    dat(l, { y1: y, y2: y }); n.querySelector("rect").setAttribute("y", y - 10);
    const ch = n.querySelector("text"); ch.setAttribute("y", y + 4); ch.textContent = soVN(giaTai(y), +d.soLe);
  };
  const doDen = (x, y) => {
    y = kep(y);
    const g0 = giaTai(dau.y), g1 = giaTai(y), pt = (g1 / g0 - 1) * 100, dau_ = pt >= 0 ? "+" : "−";
    td.classList.toggle("giam", pt < 0);
    dat(q(".vung-do"), { x: Math.min(dau.x, x), y: Math.min(dau.y, y), width: Math.abs(x - dau.x), height: Math.abs(y - dau.y) });
    dat(q(".duong-do"), { x1: dau.x, y1: dau.y, x2: x, y2: y });
    const ch = q(".chu-do"), xt = Math.min(x + 8, +d.r - 220);
    dat(ch, { x: xt, y: Math.max(+d.tren + 14, y + (y < dau.y ? -8 : 18)) });
    ch.textContent = `${dau_}${soVN(Math.abs(pt), 2)}% (${dau_}${soVN(Math.abs(g1 - g0), +d.soLe)} ${d.donVi}) · ${Math.abs(nenTai(x) - nenTai(dau.x))} nến`;
    td.setAttribute("visibility", "visible");
  };
  svg.addEventListener("pointerdown", e => {
    const [x, y] = toaDo(e);
    td.setAttribute("visibility", "hidden");
    if (!trongGia(y)) return;
    dau = { x, y, keo: false };
    svg.setPointerCapture(e.pointerId);
  });
  svg.addEventListener("pointermove", e => {
    const [x, y] = toaDo(e);
    ngang(y);
    if (!dau) return;
    if (Math.abs(x - dau.x) + Math.abs(y - dau.y) > 4) dau.keo = true;
    if (dau.keo) doDen(x, y);
  });
  svg.addEventListener("pointerup", () => { dau = null; });
  svg.addEventListener("pointerleave", () => { if (!dau) ngang(-1); });
});
document.addEventListener("keydown", e => {
  if (e.key === "Escape") document.querySelectorAll(".thuoc-do").forEach(g => g.setAttribute("visibility", "hidden"));
});
// nút H1 / H4 / D1: hiện biểu đồ nến đúng khung trong cùng mục, các khung khác ẩn (đã vẽ sẵn, không tải lại trang)
document.querySelectorAll("[data-chon-khung]").forEach(n => n.addEventListener("click", () => {
  const muc = n.closest("section");
  muc.querySelectorAll(".khung-nen").forEach(k => { k.hidden = k.dataset.khung !== n.dataset.chonKhung; });
  muc.querySelectorAll("[data-chon-khung]").forEach(b => b.setAttribute("aria-pressed", b === n));
}));
document.querySelectorAll("input[data-loc]").forEach(o => o.addEventListener("input", () => {
  const q = o.value.trim().toUpperCase();
  document.querySelectorAll(o.dataset.loc + " tbody tr").forEach(tr => { tr.hidden = q && !tr.textContent.toUpperCase().includes(q); });
}));
// Biểu đồ: đường dọc bám theo chuột (hoặc phím mũi tên) và hiện giá của ngày gần nhất
document.querySelectorAll(".bieu-do").forEach(khung => {
  const svg = khung.querySelector("svg"), diem = JSON.parse(khung.querySelector("script").textContent);
  const tro = svg.querySelector(".tro"), cham = svg.querySelector(".diem-tro"), hop = khung.querySelector(".o-tro");
  const rong = svg.viewBox.baseVal.width;
  let chiSo = diem.length - 1;
  khung.parentElement.scrollLeft = khung.parentElement.scrollWidth;  // màn hình hẹp: mở ở phần giá mới nhất
  const hien = i => {
    chiSo = Math.max(0, Math.min(diem.length - 1, i));
    const [x, y, ngay, gia] = diem[chiSo], ty = svg.getBoundingClientRect().width / rong;
    tro.setAttribute("x1", x); tro.setAttribute("x2", x); cham.setAttribute("cx", x); cham.setAttribute("cy", y);
    tro.style.visibility = cham.style.visibility = "visible";
    hop.querySelector("b").textContent = gia.toLocaleString("vi-VN") + " " + khung.dataset.donVi;
    hop.querySelector("span").textContent = ngay.split("-").reverse().join("/");
    hop.style.left = x * ty + "px"; hop.style.top = y * ty + "px"; hop.hidden = false;
    hop.classList.toggle("duoi", y * ty < 70);  // sát mép trên thì hiện bên dưới điểm để không bị che
  };
  const an = () => { tro.style.visibility = cham.style.visibility = "hidden"; hop.hidden = true; };
  svg.addEventListener("pointermove", e => {
    const r = svg.getBoundingClientRect(), x = (e.clientX - r.left) * rong / r.width;
    let gan = 0;
    diem.forEach((d, i) => { if (Math.abs(d[0] - x) < Math.abs(diem[gan][0] - x)) gan = i; });
    hien(gan);
  });
  svg.addEventListener("pointerleave", an);
  svg.addEventListener("blur", an);
  svg.addEventListener("focus", () => hien(chiSo));
  svg.addEventListener("keydown", e => {
    if (e.key === "ArrowLeft" || e.key === "ArrowRight") { e.preventDefault(); hien(chiSo + (e.key === "ArrowLeft" ? -1 : 1)); }
  });
});
