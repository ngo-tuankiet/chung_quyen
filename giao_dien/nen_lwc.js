// Nến trang chi tiết CW bằng TradingView Lightweight Charts (giao_dien/THU_VIEN_NGOAI.md). Mỗi .lwc-nen có data-nen:
// [[thời điểm, mở, cao, thấp, đóng, KL, khớp lẻ] | [thời điểm] (mốc không khớp)]: 2 biểu đồ CW và cổ phiếu cơ sở cùng khung
// (data-khung) chung trục, nên phóng to / kéo / con trỏ ở biểu đồ này thì biểu đồ kia đi theo. Màu lấy từ biến CSS (sáng / tối).
(() => {
  if (!window.LightweightCharts) return;
  const LWC = window.LightweightCharts;
  const bien = ten => getComputedStyle(document.documentElement).getPropertyValue(ten).trim();
  const soVN = (x, le) => x.toLocaleString("vi-VN", { minimumFractionDigits: le, maximumFractionDigits: le });
  const giay = g => {  // "YYYY-MM-DD HH:MM" -> giây UTC: giờ trên trục đúng giờ Việt Nam đã ghi trong dữ liệu
    const [ngay, gio = "00:00"] = g.split(" ");
    const [n, t, d] = ngay.split("-").map(Number), [h, p] = gio.split(":").map(Number);
    return Date.UTC(n, t - 1, d, h, p) / 1000;
  };
  const nhanGio = (g, khung) =>
    g.slice(8, 10) + "/" + g.slice(5, 7) +
    (khung === "h1" ? " " + g.slice(11, 16) : khung === "h4" ? (g.slice(11, 16) < "13:00" ? " buổi sáng" : " buổi chiều") : "");
  const mau = { tang: bien("--tot"), giam: bien("--chu-am"), le: bien("--chu-mo"), chu: bien("--chu-phu"), luoi: bien("--luoi") };
  const theoKhung = {};

  document.querySelectorAll(".lwc-nen").forEach(o => {
    const ds = JSON.parse(o.dataset.nen), le = Number(o.dataset.soLe), khung = o.dataset.khung, chuGiai = o.previousElementSibling;
    const giaVN = p => soVN(p, le);
    const bd = LWC.createChart(o, {
      autoSize: true,
      layout: { background: { color: "transparent" }, textColor: mau.chu, fontFamily: getComputedStyle(document.body).fontFamily },
      grid: { vertLines: { visible: false }, horzLines: { color: mau.luoi } },
      rightPriceScale: { borderVisible: false },
      timeScale: {
        borderVisible: false, timeVisible: khung !== "d1", secondsVisible: false, rightOffset: 2,
        tickMarkFormatter: (t, loai) => {
          const d = new Date(t * 1000), dd = String(d.getUTCDate()).padStart(2, "0"), mm = String(d.getUTCMonth() + 1).padStart(2, "0");
          return loai <= 2 ? `${dd}/${mm}` : `${String(d.getUTCHours()).padStart(2, "0")}:${String(d.getUTCMinutes()).padStart(2, "0")}`;
        },
      },
      localization: {
        locale: "vi-VN",
        priceFormatter: giaVN,
        timeFormatter: t => nhanGio(new Date(t * 1000).toISOString().slice(0, 16).replace("T", " "), khung),
      },
    });
    const nen = bd.addSeries(LWC.CandlestickSeries, {
      upColor: mau.tang, downColor: mau.giam, wickUpColor: mau.tang, wickDownColor: mau.giam, borderVisible: false,
      priceFormat: { type: "custom", formatter: giaVN, minMove: le ? 10 ** -le : 1 },
    });
    nen.priceScale().applyOptions({ scaleMargins: { top: 0.06, bottom: 0.26 } });
    const kl = bd.addSeries(LWC.HistogramSeries, { priceScaleId: "kl", priceFormat: { type: "volume" }, lastValueVisible: false, priceLineVisible: false });
    bd.priceScale("kl").applyOptions({ scaleMargins: { top: 0.8, bottom: 0 } });
    // khớp lẻ (dưới 5 triệu đồng): giá không đáng tin, vẽ màu mờ như bản SVG
    nen.setData(ds.map(d => d.length < 2 ? { time: giay(d[0]) } : {
      time: giay(d[0]), open: d[1], high: d[2], low: d[3], close: d[4],
      ...(d[6] ? { color: mau.le, wickColor: mau.le } : {}),
    }));
    kl.setData(ds.map(d => d.length < 2 ? { time: giay(d[0]) } : {
      time: giay(d[0]), value: d[5], color: (d[6] ? mau.le : d[4] >= d[1] ? mau.tang : mau.giam) + "66",
    }));
    bd.timeScale().fitContent();

    const theoGiay = new Map(ds.map((d, i) => [giay(d[0]), i]));
    const ghiChuGiai = i => {  // dòng thông số của nến i (mặc định nến cuối), % so với đóng cửa nến có khớp trước đó
      const d = ds[i];
      if (!chuGiai || !d) return;
      if (d.length < 2) { chuGiai.innerHTML = `<b>${nhanGio(d[0], khung)}</b> không khớp lệnh`; return; }
      const truoc = ds.slice(0, i).reverse().find(x => x.length > 1), doi = d[4] / (truoc ? truoc[4] : d[1]) - 1;
      const lop = doi > 0 ? "gia-tang" : doi < 0 ? "gia-giam" : "";
      chuGiai.innerHTML = `<b>${nhanGio(d[0], khung)}</b> Mở <b>${giaVN(d[1])}</b> Cao <b>${giaVN(d[2])}</b> Thấp <b>${giaVN(d[3])}</b> ` +
        `Đóng <b class="${lop}">${giaVN(d[4])}</b> <span class="${lop}">${(doi >= 0 ? "+" : "") + soVN(doi * 100, 1)}%</span> ` +
        `KL <b>${soVN(d[5], 0)}</b>` + (d[6] ? " · <i>khớp lẻ dưới 5 triệu đồng, giá không đáng tin</i>" : "");
    };
    const cuoi = ds.map(d => d.length > 1).lastIndexOf(true);
    ghiChuGiai(cuoi);
    const muc = { bd, nen, ds, theoGiay, ghiChuGiai, cuoi };
    (theoKhung[khung] = theoKhung[khung] || []).push(muc);

    bd.subscribeCrosshairMove(p => {
      if (!p.sourceEvent) return;  // sự kiện do biểu đồ kia đặt con trỏ hộ: không chuyền tiếp (tránh vòng lặp)
      const i = p.time === undefined ? cuoi : theoGiay.get(p.time);
      ghiChuGiai(i);
      theoKhung[khung].filter(m => m !== muc).forEach(m => {
        const j = p.time === undefined ? undefined : m.theoGiay.get(p.time), d = j === undefined ? null : m.ds[j];
        if (d && d.length > 1) m.bd.setCrosshairPosition(d[4], p.time, m.nen);
        else m.bd.clearCrosshairPosition();
        m.ghiChuGiai(j === undefined ? m.cuoi : j);
      });
    });
    let dangDong = false;  // phóng to / kéo 1 biểu đồ thì biểu đồ kia theo (cùng trục, cùng số mốc)
    bd.timeScale().subscribeVisibleLogicalRangeChange(r => {
      if (dangDong || !r) return;
      dangDong = true;
      theoKhung[khung].filter(m => m !== muc).forEach(m => m.bd.timeScale().setVisibleLogicalRange(r));
      dangDong = false;
    });
  });

  // khung đang ẩn có bề rộng 0 lúc tạo: hiện ra thì vừa khít lại toàn bộ nến
  document.querySelectorAll("[data-chon-khung]").forEach(n => n.addEventListener("click", () =>
    requestAnimationFrame(() => (theoKhung[n.dataset.chonKhung] || []).forEach(m => m.bd.timeScale().fitContent()))));
})();
