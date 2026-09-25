(function () {
  const $ = (id) => document.getElementById(id);
  const pct = (v, d = 0) => (v * 100).toFixed(d) + "%";
  const sgn = (v, d = 2) => (v >= 0 ? "" : "−") + Math.abs(v).toFixed(d);
  const MKT = { XTIUSD: ["WTI", "--s1"], XBRUSD: ["Brent", "--s2"], XNGUSD: ["Gas", "--s3"] };
  const css = (n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim();

  function legend(host, items, box) {
    if (!host) return;
    host.replaceChildren();
    items.forEach(([label, color]) => {
      const s = document.createElement("span");
      const i = document.createElement("i");
      if (box) i.className = "box";
      i.style.background = `var(${color})`;
      s.append(i, document.createTextNode(label));
      host.appendChild(s);
    });
  }
  function cell(tr, v, cls) {
    const td = document.createElement("td");
    if (cls) td.className = cls;
    td.textContent = v;
    tr.appendChild(td);
    return td;
  }

  // KPIs
  const K = DATA.kpi;
  const kp = $("kpis");
  [["Net Sharpe", K.sharpe.toFixed(2), `1991–2024 · t-stat ${K.t_stat.toFixed(1)}`],
   ["Out-of-sample Sharpe", K.oos.toFixed(2), "2008–2024, rules fixed on 1991–2007"],
   ["Annual return", pct(K.cagr, 1), `at ${pct(K.ann_vol, 1)} volatility`],
   ["Worst drawdown", "−" + pct(Math.abs(K.max_dd), 0), `longest under water ${K.underwater} yrs`],
   ["Losing years", pct(K.p_loss_1y, 0), "of rolling 12-month windows"],
   ["Costs", pct(K.cost, 1) + "/yr", "mostly the financing markup"]].forEach(([l, v, d]) => {
    const div = document.createElement("div");
    div.className = "kpi";
    const a = document.createElement("span"); a.className = "l"; a.textContent = l;
    const b = document.createElement("span"); b.className = "v"; b.textContent = v;
    const c = document.createElement("span"); c.className = "d"; c.textContent = d;
    div.append(a, b, c);
    kp.appendChild(div);
  });

  // Scoreboard
  Viz.hbar($("fig-scoreboard"), {
    items: DATA.scoreboard.map((d) => ({ label: d.label, sub: d.sub, value: d.value, tip: d.tip })),
    fmt: (v) => sgn(v), valueName: "net Sharpe", labelWidth: 300, aria: "Net Sharpe by strategy family",
  });

  // Equity
  const eqS = [["Trend + crack", "trend+crack", "--s1"], ["Trend only", "trend", "--s2"], ["Crack only (crude)", "crack", "--s3"], ["Buy & hold", "long_only", "--gray"]];
  legend($("leg-equity"), eqS.map(([n, , c]) => [n, c]));
  Viz.line($("fig-equity"), {
    series: eqS.map(([n, k, c]) => ({ name: n, color: c, data: DATA.equity[k] })),
    log: true, height: 360, yFmt: (v) => "$" + v, valFmt: (v) => "$" + v.toFixed(2), aria: "Growth of one dollar",
  });

  // Yearly returns
  const Y = DATA.headline["trend+crack"].yearly;
  const yrs = Object.keys(Y).filter((y) => +y >= 1991).sort();
  Viz.columns($("fig-yearly"), {
    categories: yrs,
    series: [{ name: "Trend + crack", colorFn: (v) => (v >= 0 ? "--pos" : "--neg"), values: yrs.map((y) => Y[y] * 100) }],
    fmt: (v) => (v >= 0 ? "+" : "−") + Math.abs(v).toFixed(0) + "%",
    maxBar: 14, height: 240, aria: "Calendar-year returns",
  });

  // Decades
  const decs = ["1990-1999", "2000-2009", "2010-2019", "2020-2029"];
  const decLab = ["1990s", "2000s", "2010s", "2020–Mar 24"];
  legend($("leg-dec"), Object.values(MKT), true);
  Viz.columns($("fig-decades"), {
    categories: decLab,
    series: Object.entries(MKT).map(([s, [n, c]]) => ({ name: n, color: c, values: decs.map((d) => DATA.trend_decades[s][d]) })),
    fmt: (v) => sgn(v), valueLabels: false, aria: "Trend Sharpe by decade",
  });

  // Vol regime
  const buckets = ["<25", "25-50", "50-75", "75-90", ">90"];
  const vr = DATA.extras.vol_regime;
  legend($("leg-vol"), Object.values(MKT), true);
  Viz.columns($("fig-volreg"), {
    categories: ["< 25th", "25–50th", "50–75th", "75–90th", "> 90th"],
    series: Object.entries(MKT).map(([s, [n, c]]) => ({ name: n, color: c,
      values: buckets.map((b) => { const r = vr.find((x) => x.symbol === s && x.bucket === b); return r ? r.sharpe : null; }) })),
    fmt: (v) => sgn(v), aria: "Trend Sharpe by volatility percentile",
  });

  // Trend variants table
  const nice = (n) => n.replace("ewmac_multi_8-64", "EWMA crossovers, 4 speeds").replace("ewmac_multi_16-64", "EWMA crossovers, 3 slow speeds")
    .replace("breakout_multi", "Breakouts, 5 windows").replace("trend_combo", "Blend: crossovers + breakouts (used)")
    .replace(/^ewmac_(\d+)_(\d+)$/, "EWMA crossover $1/$2").replace(/^breakout_(\d+)$/, "Breakout $1 days").replace(/^tsmom_(\d+)$/, "Momentum, $1-day return sign")
    .replace(/^sma_(\d+)_(\d+)$/, "SMA cross $1/$2").replace(/^donchian_(\d+)_(\d+)$/, "Donchian/Turtle $1 in, $2 out").replace("long_only_voltarget", "Buy & hold (vol-targeted)");
  const tb = document.querySelector("#tbl-trendvars tbody");
  DATA.trend_variants.slice().sort((a, b) => b.sharpe - a.sharpe).forEach((r) => {
    const tr = document.createElement("tr");
    cell(tr, nice(r.name));
    cell(tr, sgn(r.sharpe), "n"); cell(tr, sgn(r.is_sharpe), "n"); cell(tr, sgn(r.oos_sharpe), "n"); cell(tr, "−" + pct(Math.abs(r.max_dd)), "n");
    if (r.name === "trend_combo") tr.style.fontWeight = "600";
    tb.appendChild(tr);
  });

  // Crack
  Viz.columns($("fig-cracklag"), {
    categories: DATA.crack_lag.map((d) => (d.lag === 1 ? "same close" : `+${d.lag - 1} day${d.lag > 2 ? "s" : ""}`)),
    series: [{ name: "Net Sharpe", color: "--s1", values: DATA.crack_lag.map((d) => d.sharpe) }],
    fmt: (v) => v.toFixed(2), valueLabels: true, min: 0, aria: "Crack signal Sharpe by execution delay",
  });
  const cvName = { crack321_z60: "60-day z-score", crack321_z120: "120-day z-score", crack321_z250: "250-day z-score (used)", crack321_z500: "500-day z-score",
    crack_gasoline_z250: "Gasoline crack only", crack_heating_z250: "Heating-oil crack only", crack_321_pct_z250: "Margin as % of crude",
    crack321_seasadj_z250: "Seasonally adjusted", "crack321_nearWTI_z250": "Near-month WTI (2008+)", "crack321_z250_2008+": "Same, Dec WTI (2008+)",
    crack321_z250_weekly: "Rebalanced weekly", trend_only: "Trend only (2 crude mkts)", "trend+crack": "Trend + crack (2 crude mkts)" };
  Viz.hbar($("fig-crackvars"), {
    items: DATA.crack_variants.filter((d) => cvName[d.name]).map((d) => ({ label: cvName[d.name], value: d.sharpe, tip: `IS ${sgn(d.is_sharpe ?? NaN)} · OOS ${sgn(d.oos_sharpe)}` })),
    fmt: (v) => v.toFixed(2), labelWidth: 200, aria: "Crack signal variants",
  });

  // Carry table
  const cn = { carry_sign: "Sign of curve slope", carry_scaled: "Scaled curve slope", carry_ema60_sign: "60-day smoothed, sign", carry_ema60_scaled: "60-day smoothed, scaled",
    carry_seasadj_sign: "Seasonally adjusted, sign", static_short: "Always short", trend: "Trend (reference)", trend_carry_filter: "Trend, half size when carry disagrees", trend_plus_carry: "Trend + ½ carry" };
  const ct = document.querySelector("#tbl-carry tbody");
  Object.keys(cn).forEach((k) => {
    const rows = DATA.carry.filter((r) => r.name === k);
    const P = rows.find((r) => r.symbol === "PORT"), g = (s) => rows.find((r) => r.symbol === s);
    if (!P) return;
    const tr = document.createElement("tr");
    cell(tr, cn[k]); cell(tr, sgn(P.sharpe), "n"); cell(tr, sgn(P.is_sharpe), "n"); cell(tr, sgn(P.oos_sharpe), "n");
    ["XTIUSD", "XBRUSD", "XNGUSD"].forEach((s) => cell(tr, sgn(g(s).sharpe), "n"));
    ct.appendChild(tr);
  });

  // Mean reversion
  const mrName = (n) => n.replace(/^reversal_(\d+)d$/, "Fade last $1-day move").replace("rsi2_connors_trendfilter", "RSI(2) dips in uptrend").replace("rsi2_connors_nofilter", "RSI(2) extremes, no filter")
    .replace(/^zfade_(\d+)_2.0$/, "Fade ±2σ vs $1-day mean").replace(/^zcontinuous_(\d+)$/, "Continuous z-fade, $1 days")
    .replace(/^shock_reversal_([\d.]+)_(\d+)d$/, "Fade $1σ shock, hold $2d").replace(/^shock_continuation_([\d.]+)_(\d+)d$/, "Follow $1σ shock, hold $2d");
  Viz.hbar($("fig-mr"), {
    items: DATA.mean_reversion.filter((d) => d.lag === 1).sort((a, b) => b.sharpe - a.sharpe).map((d) => ({ label: mrName(d.name), value: d.sharpe, tip: `2008+ ${sgn(d.oos_sharpe)}` })),
    fmt: (v) => sgn(v), labelWidth: 230, aria: "Mean reversion Sharpe",
  });

  // Prices + holdout
  const H = DATA.holdout;
  legend($("leg-px"), [["WTI", "--s1"], ["Brent", "--s2"]]);
  Viz.line($("fig-prices"), {
    series: [{ name: "WTI", color: "--s1", data: H.prices.XTIUSD }, { name: "Brent", color: "--s2", data: H.prices.XBRUSD }],
    height: 280, yFmt: (v) => "$" + v, valFmt: (v) => "$" + v.toFixed(2), bands: [{ from: "2024-04-01", to: H.prices.XTIUSD.slice(-1)[0][0], label: "holdout" }],
    aria: "WTI and Brent spot prices",
  });
  legend($("leg-hold"), [["WTI", "--s1"], ["Brent", "--s2"]], true);
  const months = H.XTIUSD.map((d) => d[0]);
  const mLab = (m) => { const [y, mo] = m.split("-"); return ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"][+mo - 1] + " " + y.slice(2); };
  Viz.columns($("fig-holdout"), {
    categories: months.map(mLab),
    series: [{ name: "WTI", color: "--s1", values: H.XTIUSD.map((d) => d[1] * 100) }, { name: "Brent", color: "--s2", values: H.XBRUSD.map((d) => d[1] * 100) }],
    fmt: (v) => (v >= 0 ? "+" : "−") + Math.abs(v).toFixed(1) + "%", rotate: true, maxBar: 9, height: 280, aria: "Monthly P&L of trend rule",
  });

  // Rolling table
  const rt = document.querySelector("#tbl-rolling tbody");
  DATA.extras.rolling.filter((r) => r.strategy === "trend+crack" && r.years !== "dd").forEach((r) => {
    const tr = document.createElement("tr");
    cell(tr, `${r.years} year${r.years > 1 ? "s" : ""}`); cell(tr, pct(r.p_loss), "n"); cell(tr, (r.median >= 0 ? "+" : "−") + pct(Math.abs(r.median)), "n");
    cell(tr, (r.worst >= 0 ? "+" : "−") + pct(Math.abs(r.worst)), "n");
    rt.appendChild(tr);
  });

  /*__AGENT_JS__*/
})();
