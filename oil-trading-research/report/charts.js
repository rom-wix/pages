/* Tiny dependency-free SVG chart kit for the report.
   - reads colors from CSS custom properties at render time (theme-aware), re-renders on theme/size change
   - line (multi-series, optional log y), hbar (diverging around 0), columns (grouped or diverging)
   - hover/focus tooltips; values also available in the tables next to each chart */
(function () {
  const NS = "http://www.w3.org/2000/svg";
  const registry = [];

  function css(name) {
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  }
  function el(tag, attrs, parent) {
    const n = document.createElementNS(NS, tag);
    for (const k in attrs) n.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(n);
    return n;
  }
  function text(parent, x, y, str, opts = {}) {
    const t = el("text", {
      x, y, fill: opts.fill || css("--muted"), "font-size": opts.size || 12,
      "text-anchor": opts.anchor || "start", "dominant-baseline": opts.baseline || "middle",
      "font-family": opts.font || css("--font-data"), "font-weight": opts.weight || 400,
    }, parent);
    t.textContent = str;
    return t;
  }
  function niceStep(range, target) {
    const raw = range / Math.max(target, 1);
    const mag = Math.pow(10, Math.floor(Math.log10(raw)));
    const norm = raw / mag;
    const step = norm < 1.5 ? 1 : norm < 3 ? 2 : norm < 7 ? 5 : 10;
    return step * mag;
  }
  function linTicks(lo, hi, n) {
    const s = niceStep(hi - lo, n);
    const out = [];
    for (let v = Math.ceil(lo / s) * s; v <= hi + 1e-9; v += s) out.push(+v.toFixed(10));
    return out;
  }
  function tooltip(host) {
    let tip = host.querySelector(".viz-tip");
    if (!tip) {
      tip = document.createElement("div");
      tip.className = "viz-tip";
      tip.hidden = true;
      host.appendChild(tip);
    }
    return tip;
  }
  function showTip(tip, host, x, y, title, rows) {
    tip.replaceChildren();
    const h = document.createElement("div");
    h.className = "viz-tip-title";
    h.textContent = title;
    tip.appendChild(h);
    rows.forEach((r) => {
      const row = document.createElement("div");
      row.className = "viz-tip-row";
      const key = document.createElement("span");
      key.className = "viz-tip-key";
      key.style.background = r.color;
      const v = document.createElement("strong");
      v.textContent = r.value;
      const lab = document.createElement("span");
      lab.className = "viz-tip-label";
      lab.textContent = r.label;
      row.append(key, v, lab);
      tip.appendChild(row);
    });
    tip.hidden = false;
    const hw = host.clientWidth, tw = tip.offsetWidth, th = tip.offsetHeight;
    let left = x + 14;
    if (left + tw > hw - 4) left = x - tw - 14;
    tip.style.left = Math.max(4, left) + "px";
    tip.style.top = Math.max(4, y - th / 2) + "px";
  }

  // ------------------------------------------------------------------ line chart
  function line(host, cfg) {
    const draw = () => {
      host.querySelectorAll("svg").forEach((s) => s.remove());
      const W = Math.max(host.clientWidth, 280), H = cfg.height || 320;
      const narrow = W < 520;
      const m = { t: 16, r: cfg.endLabels === false ? 16 : narrow ? 16 : 96, b: 28, l: 48 };
      const svg = el("svg", { width: W, height: H, viewBox: `0 0 ${W} ${H}`, role: "img",
        "aria-label": cfg.aria || "line chart" });
      host.prepend(svg);
      const series = cfg.series;
      const xs = series[0].data.map((d) => d[0]);
      const tx = (s) => { const [y, mo, d] = s.split("-").map(Number); return y + ((mo || 1) - 1) / 12 + ((d || 1) - 1) / 365; };
      const allY = series.flatMap((s) => s.data.map((d) => d[1])).filter((v) => v != null);
      let ylo = cfg.yMin ?? Math.min(...allY), yhi = cfg.yMax ?? Math.max(...allY);
      const log = !!cfg.log;
      const f = log ? Math.log : (v) => v;
      if (!log) { const pad = (yhi - ylo) * 0.06; ylo -= pad; yhi += pad; }
      const x0 = tx(xs[0]), x1 = tx(xs[xs.length - 1]);
      const X = (s) => m.l + ((tx(s) - x0) / (x1 - x0)) * (W - m.l - m.r);
      const Y = (v) => m.t + (1 - (f(v) - f(ylo)) / (f(yhi) - f(ylo))) * (H - m.t - m.b);
      // grid + y ticks
      let ticks;
      if (log) {
        ticks = [];
        const cands = [0.25, 0.5, 1, 2, 3, 4, 6, 8, 10, 15, 20, 30, 50];
        cands.forEach((c) => { if (c >= ylo * 0.98 && c <= yhi * 1.02) ticks.push(c); });
        if (ticks.length > 7) ticks = ticks.filter((_, i) => i % 2 === 0);
      } else ticks = linTicks(ylo, yhi, 5);
      ticks.forEach((v) => {
        const y = Y(v);
        el("line", { x1: m.l, x2: W - m.r, y1: y, y2: y, stroke: css("--grid"), "stroke-width": 1 }, svg);
        text(svg, m.l - 8, y, cfg.yFmt ? cfg.yFmt(v) : String(v), { anchor: "end" });
      });
      if (cfg.zeroLine && ylo < 0 && yhi > 0)
        el("line", { x1: m.l, x2: W - m.r, y1: Y(0), y2: Y(0), stroke: css("--axis"), "stroke-width": 1 }, svg);
      // x ticks: years
      const span = x1 - x0;
      const every = span > 24 ? 5 : span > 10 ? 2 : span > 3 ? 1 : 0.25;
      for (let yv = Math.ceil(x0 / every) * every; yv <= x1; yv += every) {
        const xp = m.l + ((yv - x0) / (x1 - x0)) * (W - m.l - m.r);
        const yr = Math.floor(yv + 1e-9), q = Math.round((yv - yr) * 12);
        const lab = every < 1 ? (q === 0 ? String(yr) : ["", "", "", "Apr", "", "", "Jul", "", "", "Oct"][q] || "") : String(yr);
        if (lab) text(svg, xp, H - m.b + 16, lab, { anchor: "middle" });
        el("line", { x1: xp, x2: xp, y1: H - m.b, y2: H - m.b + 4, stroke: css("--axis") }, svg);
      }
      el("line", { x1: m.l, x2: W - m.r, y1: H - m.b, y2: H - m.b, stroke: css("--axis") }, svg);
      // shaded spans (e.g., holdout)
      (cfg.bands || []).forEach((b) => {
        const xa = X(b.from), xb = X(b.to);
        el("rect", { x: xa, y: m.t, width: Math.max(xb - xa, 1), height: H - m.t - m.b, fill: css("--band") }, svg);
        text(svg, xa + 6, m.t + 10, b.label, { size: 11, fill: css("--ink-2") });
      });
      // lines
      series.forEach((s) => {
        const pts = s.data.filter((d) => d[1] != null).map((d) => `${X(d[0]).toFixed(1)},${Y(d[1]).toFixed(1)}`);
        el("polyline", { points: pts.join(" "), fill: "none", stroke: css(s.color), "stroke-width": s.width || 2,
          "stroke-linejoin": "round", "stroke-linecap": "round", opacity: s.dim ? 0.9 : 1 }, svg);
      });
      // end labels (direct), de-collided with leader lines
      if (!narrow && cfg.endLabels !== false) {
        const ends = series.map((s) => {
          const d = s.data.filter((p) => p[1] != null).slice(-1)[0];
          return { s, x: X(d[0]), y: Y(d[1]), v: d[1] };
        }).sort((a, b) => a.y - b.y);
        const minGap = 26;
        for (let i = 1; i < ends.length; i++) if (ends[i].y - ends[i - 1].y < minGap) ends[i].ly = (ends[i - 1].ly ?? ends[i - 1].y) + minGap;
        ends.forEach((e) => {
          const ly = Math.min(e.ly ?? e.y, H - m.b - 8);
          el("circle", { cx: e.x, cy: e.y, r: 4, fill: css(e.s.color), stroke: css("--surface"), "stroke-width": 2 }, svg);
          if (Math.abs(ly - e.y) > 2) el("line", { x1: e.x + 5, y1: e.y, x2: e.x + 12, y2: ly, stroke: css("--axis") }, svg);
          text(svg, e.x + 14, ly - 6, e.s.name, { fill: css("--ink"), size: 11, font: css("--font-body"), weight: 600 });
          text(svg, e.x + 14, ly + 8, cfg.valFmt ? cfg.valFmt(e.v) : e.v.toFixed(2), { fill: css("--ink-2"), size: 11 });
        });
      }
      // crosshair + tooltip
      const tip = tooltip(host);
      const cross = el("line", { y1: m.t, y2: H - m.b, stroke: css("--axis"), "stroke-width": 1, visibility: "hidden" }, svg);
      const dots = series.map((s) => el("circle", { r: 4, fill: css(s.color), stroke: css("--surface"), "stroke-width": 2, visibility: "hidden" }, svg));
      const hit = el("rect", { x: m.l, y: m.t, width: W - m.l - m.r, height: H - m.t - m.b, fill: "transparent", tabindex: 0 }, svg);
      const onMove = (clientX) => {
        const r = svg.getBoundingClientRect();
        const px = clientX - r.left;
        let best = 0, bd = Infinity;
        xs.forEach((xv, i) => { const d = Math.abs(X(xv) - px); if (d < bd) { bd = d; best = i; } });
        const xv = xs[best], xp = X(xv);
        cross.setAttribute("x1", xp); cross.setAttribute("x2", xp); cross.setAttribute("visibility", "visible");
        const rows = [];
        series.forEach((s, k) => {
          const pt = s.data[best];
          if (!pt || pt[1] == null) { dots[k].setAttribute("visibility", "hidden"); return; }
          dots[k].setAttribute("cx", xp); dots[k].setAttribute("cy", Y(pt[1])); dots[k].setAttribute("visibility", "visible");
          rows.push({ color: css(s.color), value: cfg.valFmt ? cfg.valFmt(pt[1]) : pt[1], label: s.name, y: pt[1] });
        });
        rows.sort((a, b) => b.y - a.y);
        showTip(tip, host, xp, Y(rows.length ? rows[0].y : ylo), cfg.xFmt ? cfg.xFmt(xv) : xv, rows);
      };
      hit.addEventListener("pointermove", (e) => onMove(e.clientX));
      hit.addEventListener("pointerleave", () => { tip.hidden = true; cross.setAttribute("visibility", "hidden"); dots.forEach((d) => d.setAttribute("visibility", "hidden")); });
      hit.addEventListener("focus", () => { const r = svg.getBoundingClientRect(); onMove(r.left + W - m.r - 1); });
      hit.addEventListener("blur", () => { tip.hidden = true; });
    };
    registry.push({ host, draw });
    draw();
  }

  // ------------------------------------------------------------------ horizontal bars (diverging at 0)
  function hbar(host, cfg) {
    const draw = () => {
      host.querySelectorAll("svg").forEach((s) => s.remove());
      const W = Math.max(host.clientWidth, 280);
      const narrow = W < 560;
      const rowH = 30, labW = narrow ? Math.min(150, W * 0.42) : cfg.labelWidth || 250;
      const items = cfg.items;
      const H = items.length * rowH + 36;
      const svg = el("svg", { width: W, height: H, viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": cfg.aria || "bar chart" });
      host.prepend(svg);
      const vals = items.map((d) => d.value);
      const lo = Math.min(cfg.min ?? 0, ...vals), hi = Math.max(cfg.max ?? 0, ...vals);
      const m = { l: labW + 8, r: 52, t: 8, b: 26 };
      const X = (v) => m.l + ((v - lo) / (hi - lo)) * (W - m.l - m.r);
      linTicks(lo, hi, narrow ? 3 : 6).forEach((v) => {
        el("line", { x1: X(v), x2: X(v), y1: m.t, y2: H - m.b, stroke: css("--grid") }, svg);
        text(svg, X(v), H - m.b + 14, cfg.fmt ? cfg.fmt(v) : v.toFixed(1), { anchor: "middle" });
      });
      el("line", { x1: X(0), x2: X(0), y1: m.t, y2: H - m.b, stroke: css("--axis") }, svg);
      const tip = tooltip(host);
      items.forEach((d, i) => {
        const yc = m.t + i * rowH + rowH / 2;
        const g = el("g", { tabindex: 0, class: "viz-mark" }, svg);
        el("rect", { x: 0, y: yc - rowH / 2, width: W, height: rowH, fill: "transparent" }, g);
        const lbl = text(g, labW, yc, d.label, { anchor: "end", fill: css("--ink"), font: css("--font-body"), size: narrow ? 11 : 12.5 });
        if (d.sub && !narrow) { lbl.setAttribute("y", yc - 6); text(g, labW, yc + 8, d.sub, { anchor: "end", size: 10.5, fill: css("--muted"), font: css("--font-body") }); }
        const x0 = X(0), x1 = X(d.value), bh = Math.min(16, rowH - 10);
        const left = Math.min(x0, x1), w = Math.max(Math.abs(x1 - x0), 1.5);
        const col = css(d.color || (d.value >= 0 ? "--pos" : "--neg"));
        const r = Math.min(4, w / 2);
        // rounded data-end, square at baseline
        const pth = d.value >= 0
          ? `M${left},${yc - bh / 2} h${w - r} q${r},0 ${r},${r} v${bh - 2 * r} q0,${r} -${r},${r} h-${w - r} z`
          : `M${left + w},${yc - bh / 2} h-${w - r} q-${r},0 -${r},${r} v${bh - 2 * r} q0,${r} ${r},${r} h${w - r} z`;
        el("path", { d: pth, fill: col }, g);
        const vx = d.value >= 0 ? x1 + 6 : x1 - 6;
        text(g, vx, yc, cfg.fmt ? cfg.fmt(d.value) : d.value.toFixed(2), { anchor: d.value >= 0 ? "start" : "end", fill: css("--ink-2"), size: 11.5 });
        const show = () => {
          const b = host.getBoundingClientRect(), gb = g.getBoundingClientRect();
          showTip(tip, host, Math.min(x1, W - 60), gb.top - b.top + rowH / 2, d.label, [{ color: col, value: cfg.fmt ? cfg.fmt(d.value) : d.value.toFixed(2), label: d.tip || cfg.valueName || "" }]);
        };
        g.addEventListener("pointerenter", show);
        g.addEventListener("focus", show);
        g.addEventListener("pointerleave", () => (tip.hidden = true));
        g.addEventListener("blur", () => (tip.hidden = true));
      });
    };
    registry.push({ host, draw });
    draw();
  }

  // ------------------------------------------------------------------ columns (grouped; or single diverging)
  function columns(host, cfg) {
    const draw = () => {
      host.querySelectorAll("svg").forEach((s) => s.remove());
      const W = Math.max(host.clientWidth, 280), H = cfg.height || 260;
      const m = { t: 14, r: 12, b: cfg.rotate ? 46 : 30, l: 46 };
      const svg = el("svg", { width: W, height: H, viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": cfg.aria || "column chart" });
      host.prepend(svg);
      const cats = cfg.categories, ser = cfg.series;
      const allV = ser.flatMap((s) => s.values).filter((v) => v != null);
      let lo = Math.min(0, ...allV), hi = Math.max(0, ...allV);
      if (cfg.min != null) lo = Math.min(lo, cfg.min);
      if (cfg.max != null) hi = Math.max(hi, cfg.max);
      const pad = (hi - lo) * 0.08; hi += pad; if (lo < 0) lo -= pad;
      const Y = (v) => m.t + (1 - (v - lo) / (hi - lo)) * (H - m.t - m.b);
      linTicks(lo, hi, 5).forEach((v) => {
        el("line", { x1: m.l, x2: W - m.r, y1: Y(v), y2: Y(v), stroke: css("--grid") }, svg);
        text(svg, m.l - 8, Y(v), cfg.fmt ? cfg.fmt(v) : v.toFixed(1), { anchor: "end" });
      });
      el("line", { x1: m.l, x2: W - m.r, y1: Y(0), y2: Y(0), stroke: css("--axis") }, svg);
      const band = (W - m.l - m.r) / cats.length;
      const gap = 2;
      const bw = Math.min(cfg.maxBar || 24, (band * 0.72 - gap * (ser.length - 1)) / ser.length);
      const groupW = bw * ser.length + gap * (ser.length - 1);
      const tip = tooltip(host);
      const labelEvery = Math.ceil(cats.length / Math.max(1, Math.floor((W - m.l - m.r) / (cfg.rotate ? 22 : 48))));
      cats.forEach((c, i) => {
        const cx = m.l + band * i + band / 2;
        if (i % labelEvery === 0) {
          const t = text(svg, cx, H - m.b + 14, c, { anchor: cfg.rotate ? "end" : "middle", size: 11 });
          if (cfg.rotate) t.setAttribute("transform", `rotate(-45 ${cx} ${H - m.b + 14})`);
        }
        const g = el("g", { tabindex: 0, class: "viz-mark" }, svg);
        el("rect", { x: cx - band / 2, y: m.t, width: band, height: H - m.t - m.b, fill: "transparent" }, g);
        ser.forEach((s, k) => {
          const v = s.values[i];
          if (v == null) return;
          const x = cx - groupW / 2 + k * (bw + gap);
          const y0 = Y(0), y1 = Y(v), h = Math.max(Math.abs(y1 - y0), 1), r = Math.min(4, bw / 2, h);
          const col = css(s.colorFn ? s.colorFn(v) : s.color);
          const d = v >= 0
            ? `M${x},${y0} v-${h - r} q0,-${r} ${r},-${r} h${bw - 2 * r} q${r},0 ${r},${r} v${h - r} z`
            : `M${x},${y0} v${h - r} q0,${r} ${r},${r} h${bw - 2 * r} q${r},0 ${r},-${r} v-${h - r} z`;
          el("path", { d, fill: col }, g);
          if (cfg.valueLabels && ser.length <= 3 && bw >= 18)
            text(g, x + bw / 2, v >= 0 ? y1 - 8 : y1 + 9, cfg.fmt ? cfg.fmt(v) : v.toFixed(2), { anchor: "middle", size: 10.5, fill: css("--ink-2") });
        });
        const show = () => {
          const rows = ser.map((s) => ({ color: css(s.colorFn ? s.colorFn(s.values[i] ?? 0) : s.color), value: s.values[i] == null ? "–" : (cfg.fmt ? cfg.fmt(s.values[i]) : s.values[i].toFixed(2)), label: s.name }));
          showTip(tip, host, cx, Y(Math.max(...ser.map((s) => s.values[i] ?? 0))), cfg.catFmt ? cfg.catFmt(c) : c, rows);
        };
        g.addEventListener("pointerenter", show);
        g.addEventListener("focus", show);
        g.addEventListener("pointerleave", () => (tip.hidden = true));
        g.addEventListener("blur", () => (tip.hidden = true));
      });
    };
    registry.push({ host, draw });
    draw();
  }

  function redrawAll() { registry.forEach((r) => r.draw()); }
  let t;
  window.addEventListener("resize", () => { clearTimeout(t); t = setTimeout(redrawAll, 120); });
  try { window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", redrawAll); } catch (e) {}
  new MutationObserver(redrawAll).observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });

  window.Viz = { line, hbar, columns, redrawAll };
})();
