(function () {
  const $ = (id) => document.getElementById(id);
  const pct = (v, d = 0) => (v * 100).toFixed(d) + "%";
  const sgn = (v, d = 2) => (v == null || isNaN(v) ? "–" : (v >= 0 ? "" : "−") + Math.abs(v).toFixed(d));
  const spct = (v, d = 0) => (v >= 0 ? "+" : "−") + Math.abs(v * 100).toFixed(d) + "%";
  const MKT = { XTIUSD: ["WTI", "--s1"], XBRUSD: ["Brent", "--s2"], XNGUSD: ["Gas", "--s3"] };

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
  function kpis(host, list) {
    list.forEach(([l, v, d]) => {
      const div = document.createElement("div");
      div.className = "kpi";
      const a = document.createElement("span"); a.className = "l"; a.textContent = l;
      const b = document.createElement("span"); b.className = "v"; b.textContent = v;
      const c = document.createElement("span"); c.className = "d"; c.textContent = d;
      div.append(a, b, c);
      host.appendChild(div);
    });
  }
  const mLab = (m) => { const [y, mo] = m.split("-"); return ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"][+mo - 1] + " " + y.slice(2); };

  // ---------------------------------------------------------------- last 12 months
  const LY = DATA.last_year;
  const rg = Object.fromEntries(LY.regime.markets.map((m) => [m.symbol, m]));
  const W = rg.XTIUSD, B = rg.XBRUSD, SP = LY.regime.brent_wti_spread;
  kpis($("ly-kpis"), [
    ["Price change", `${spct(W.return)} / ${spct(B.return)}`, "WTI / Brent"],
    ["Volatility", `${pct(W.ann_vol)} / ${pct(B.ann_vol)}`, "annualised; long-run median ≈ 34–35%"],
    ["Worst drawdown", `−${pct(Math.abs(W.max_dd))} / −${pct(Math.abs(B.max_dd))}`, "peak on 7 Apr 2026 to the June low"],
    ["Days moving > 3%", `${W.days_abs_gt_3pct} / ${B.days_abs_gt_3pct}`, `of about ${W.n_days} trading days`],
    ["Brent − WTI", `$${SP.start.toFixed(2)} → $${SP.end.toFixed(2)}`, `peak $${SP.max.toFixed(2)} on 8 Apr`],
  ]);
  legend($("leg-lypx"), [["WTI", "--s1"], ["Brent", "--s2"]]);
  Viz.line($("fig-lypx"), {
    series: [{ name: "WTI", color: "--s1", data: LY.prices.XTIUSD }, { name: "Brent", color: "--s2", data: LY.prices.XBRUSD }],
    height: 300, yFmt: (v) => "$" + v, valFmt: (v) => "$" + v.toFixed(2), aria: "WTI and Brent over the last 12 months",
  });
  const C = LY.crude_sharpe;
  const lyItems = [
    ["Buy & hold (vol-targeted)", "hindsight after a 50–70% rally", C.long_only_voltarget],
    ["1-month momentum", "fast trend", C.tsmom_21],
    ["Donchian 20/10 breakout", "fast trend", C.donchian_20_10],
    ["Recommended trend blend", "multi-speed, with vol overlay", (LY.revised.XTIUSD.sharpe + LY.revised.XBRUSD.sharpe) / 2],
    ["Original slow trend blend", "EWMA 8–64 + breakouts 40–320", C.trend_combo],
    ["Mean reversion, median rule", "19 rules", LY.mr_median],
    ["Slow breakout, 320 days", "slow trend", C.breakout_320],
    ["Always short", "", C.static_short],
  ].map(([label, sub, value]) => ({ label, sub, value }));
  Viz.hbar($("fig-lyscore"), { items: lyItems, fmt: (v) => sgn(v), valueName: "net Sharpe, crude average", labelWidth: 230, aria: "Last 12 months strategy Sharpe" });
  const monR = LY.monthly["XTIUSD:revised"], monO = LY.monthly["XTIUSD:original"];
  legend($("leg-lymon"), [["Recommended blend", "--s1"], ["Original slow blend", "--gray"]], true);
  Viz.columns($("fig-lymon"), {
    categories: monR.map((d) => mLab(d[0])),
    series: [{ name: "Recommended blend", color: "--s1", values: monR.map((d) => d[1] * 100) },
             { name: "Original slow blend", color: "--gray", values: monO.map((d) => d[1] * 100) }],
    fmt: (v) => (v >= 0 ? "+" : "−") + Math.abs(v).toFixed(1) + "%", height: 260, maxBar: 14, aria: "Monthly P&L last 12 months",
  });
  const ch = document.querySelector("#tbl-character tbody");
  LY.character.filter((r) => r.symbol !== "XNGUSD").forEach((r) => {
    const tr = document.createElement("tr");
    cell(tr, `${MKT[r.symbol][0]}, ${r.period}`);
    [r.ac1, r.vr2, r.vr5, r.vr10, r.vr20].forEach((v) => cell(tr, v.toFixed(2), "n"));
    ch.appendChild(tr);
  });

  // ---------------------------------------------------------------- verdict scoreboard
  Viz.hbar($("fig-scoreboard"), {
    items: DATA.scoreboard.map((d) => ({ label: d.label, sub: d.sub, value: d.value, tip: d.tip })),
    fmt: (v) => sgn(v), valueName: "net Sharpe", labelWidth: 300, aria: "Net Sharpe by strategy family",
  });

  // ---------------------------------------------------------------- recommended bot
  const RV = DATA.revised.revised;
  const roll1 = RV.rolling.find((r) => r.years === 1);
  kpis($("kpis"), [
    ["Net Sharpe", RV.sharpe.toFixed(2), `Nov 1991 – Mar 2024 · t-stat ${RV.t_stat.toFixed(1)}`],
    ["Out-of-sample Sharpe", RV.oos_sharpe.toFixed(2), "2008–2024, rules fixed on earlier years"],
    ["Annual return", pct(RV.cagr, 1), `at ${pct(RV.ann_vol, 1)} volatility`],
    ["Worst drawdown", "−" + pct(Math.abs(RV.max_dd), 0), `longest under water ${RV.underwater_years.toFixed(1)} yrs`],
    ["Losing years", pct(roll1.p_loss, 0), "of rolling 12-month windows"],
    ["Last 12 months", `${sgn(LY.revised.XTIUSD.sharpe)} / ${sgn(LY.revised.XBRUSD.sharpe)}`, "Sharpe WTI / Brent, spot, no crack"],
  ]);
  const eqS = [["Recommended (trend + crack)", "revised", "--s1"], ["Recommended, no crack", "revised_no_crack", "--s2"],
               ["Original slow trend", "trend", "--s3"], ["Buy & hold", "long_only", "--gray"]];
  legend($("leg-equity"), eqS.map(([n, , c]) => [n, c]));
  Viz.line($("fig-equity"), {
    series: eqS.map(([n, k, c]) => ({ name: n.replace("Recommended (trend + crack)", "Recommended").replace("Recommended, no crack", "No crack").replace("Original slow trend", "Original"), color: c, data: DATA.equity[k] })),
    log: true, height: 360, yFmt: (v) => "$" + v, valFmt: (v) => "$" + v.toFixed(2), aria: "Growth of one dollar",
  });
  const Yr = RV.yearly;
  const yrs = Object.keys(Yr).filter((y) => +y >= 1991).sort();
  Viz.columns($("fig-yearly"), {
    categories: yrs,
    series: [{ name: "Recommended bot", colorFn: (v) => (v >= 0 ? "--pos" : "--neg"), values: yrs.map((y) => Yr[y] * 100) }],
    fmt: (v) => (v >= 0 ? "+" : "−") + Math.abs(v).toFixed(0) + "%", maxBar: 14, height: 240, aria: "Calendar-year returns",
  });

  // ---------------------------------------------------------------- trend evidence
  const decs = ["1990-1999", "2000-2009", "2010-2019", "2020-2029"];
  legend($("leg-dec"), Object.values(MKT), true);
  Viz.columns($("fig-decades"), {
    categories: ["1990s", "2000s", "2010s", "2020–Mar 24"],
    series: Object.entries(MKT).map(([s, [n, c]]) => ({ name: n, color: c, values: decs.map((d) => DATA.trend_decades[s][d]) })),
    fmt: (v) => sgn(v), aria: "Trend Sharpe by decade",
  });
  const buckets = ["<25", "25-50", "50-75", "75-90", ">90"];
  const vr = DATA.extras.vol_regime;
  legend($("leg-vol"), Object.values(MKT), true);
  Viz.columns($("fig-volreg"), {
    categories: ["< 25th", "25–50th", "50–75th", "75–90th", "> 90th"],
    series: Object.entries(MKT).map(([s, [n, c]]) => ({ name: n, color: c,
      values: buckets.map((b) => { const r = vr.find((x) => x.symbol === s && x.bucket === b); return r ? r.sharpe : null; }) })),
    fmt: (v) => sgn(v), aria: "Trend Sharpe by volatility percentile",
  });
  const sb = document.querySelector("#tbl-speeds tbody");
  const sbName = (n) => n.replace(" +vol overlay", "").replace("slow+medium (ew 8-64, bo 40-320)", "Slow + medium: EWMA 8–64, breakouts 40–320 (original)")
    .replace("fast (ew 4-8, bo 20-40)", "Fast: EWMA 4–8, breakouts 20–40").replace("fast+medium (ew 4-32, bo 20-160)", "Fast + medium: EWMA 4–32, breakouts 20–160")
    .replace("all speeds (ew 4-64, bo 20-320)", "All speeds: EWMA 4–64, breakouts 20–320").replace("tsmom 1/3/12m (HOP 2017)", "1/3/12-month momentum (Hurst, Ooi, Pedersen)")
    .replace("tsmom 1/3/12m + fast+medium", "1/3/12-month momentum + fast/medium (recommended)");
  DATA.speed_blends.filter((r) => r.name.endsWith("+vol overlay")).forEach((r) => {
    const tr = document.createElement("tr");
    cell(tr, sbName(r.name));
    cell(tr, sgn(r.fut_port), "n"); cell(tr, sgn(r.fut_oos), "n"); cell(tr, "−" + pct(Math.abs(r.fut_maxdd)), "n");
    cell(tr, sgn((r.spot_2024_26_wti + r.spot_2024_26_brent) / 2), "n"); cell(tr, sgn((r.last12m_wti + r.last12m_brent) / 2), "n");
    if (r.name.startsWith("tsmom 1/3/12m + fast")) tr.style.fontWeight = "600";
    sb.appendChild(tr);
  });
  const nice = (n) => n.replace("ewmac_multi_8-64", "EWMA crossovers, 4 speeds").replace("ewmac_multi_16-64", "EWMA crossovers, 3 slow speeds")
    .replace("breakout_multi", "Breakouts, 5 windows").replace("trend_combo", "Blend: crossovers + breakouts (original)")
    .replace(/^ewmac_(\d+)_(\d+)$/, "EWMA crossover $1/$2").replace(/^breakout_(\d+)$/, "Breakout $1 days").replace(/^tsmom_(\d+)$/, "Momentum, $1-day return sign")
    .replace(/^sma_(\d+)_(\d+)$/, "SMA cross $1/$2").replace(/^donchian_(\d+)_(\d+)$/, "Donchian/Turtle $1 in, $2 out").replace("long_only_voltarget", "Buy & hold (vol-targeted)");
  const tb = document.querySelector("#tbl-trendvars tbody");
  DATA.trend_variants.slice().sort((a, b) => b.sharpe - a.sharpe).forEach((r) => {
    const tr = document.createElement("tr");
    cell(tr, nice(r.name));
    cell(tr, sgn(r.sharpe), "n"); cell(tr, sgn(r.is_sharpe), "n"); cell(tr, sgn(r.oos_sharpe), "n"); cell(tr, "−" + pct(Math.abs(r.max_dd)), "n");
    tb.appendChild(tr);
  });

  // ---------------------------------------------------------------- crack
  Viz.columns($("fig-cracklag"), {
    categories: DATA.crack_lag.map((d) => (d.lag === 1 ? "same close" : `+${d.lag - 1} day${d.lag > 2 ? "s" : ""}`)),
    series: [{ name: "Net Sharpe", color: "--s1", values: DATA.crack_lag.map((d) => d.sharpe) }],
    fmt: (v) => v.toFixed(2), valueLabels: true, min: 0, aria: "Crack signal Sharpe by execution delay",
  });
  const cvName = { crack321_z60: "60-day z-score", crack321_z120: "120-day z-score", crack321_z250: "250-day z-score (used)", crack321_z500: "500-day z-score",
    crack_gasoline_z250: "Gasoline crack only", crack_heating_z250: "Heating-oil crack only", crack_321_pct_z250: "Margin as % of crude",
    crack321_seasadj_z250: "Seasonally adjusted", "crack321_nearWTI_z250": "Near-month WTI (2008+)", "crack321_z250_2008+": "Same, Dec WTI (2008+)",
    crack321_z250_weekly: "Rebalanced weekly" };
  Viz.hbar($("fig-crackvars"), {
    items: DATA.crack_variants.filter((d) => cvName[d.name]).map((d) => ({ label: cvName[d.name], value: d.sharpe, tip: `2008+ ${sgn(d.oos_sharpe)}` })),
    fmt: (v) => v.toFixed(2), labelWidth: 200, aria: "Crack signal variants",
  });

  // ---------------------------------------------------------------- carry
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

  // ---------------------------------------------------------------- mean reversion
  const mrName = (n) => n.replace(/^reversal_(\d+)d$/, "Fade last $1-day move").replace("rsi2_connors_trendfilter", "RSI(2) dips in uptrend").replace("rsi2_connors_nofilter", "RSI(2) extremes, no filter")
    .replace(/^zfade_(\d+)_2.0$/, "Fade ±2σ vs $1-day mean").replace(/^zcontinuous_(\d+)$/, "Continuous z-fade, $1 days")
    .replace(/^shock_reversal_([\d.]+)_(\d+)d$/, "Fade $1σ shock, hold $2d").replace(/^shock_continuation_([\d.]+)_(\d+)d$/, "Follow $1σ shock, hold $2d");
  Viz.hbar($("fig-mr"), {
    items: DATA.mean_reversion.filter((d) => d.lag === 1).sort((a, b) => b.sharpe - a.sharpe).map((d) => ({ label: mrName(d.name), value: d.sharpe, tip: `2008+ ${sgn(d.oos_sharpe)}` })),
    fmt: (v) => sgn(v), labelWidth: 230, aria: "Mean reversion Sharpe",
  });

  // ---------------------------------------------------------------- since 2024
  const H = DATA.holdout;
  legend($("leg-px"), [["WTI", "--s1"], ["Brent", "--s2"]]);
  Viz.line($("fig-prices"), {
    series: [{ name: "WTI", color: "--s1", data: H.prices.XTIUSD }, { name: "Brent", color: "--s2", data: H.prices.XBRUSD }],
    height: 280, yFmt: (v) => "$" + v, valFmt: (v) => "$" + v.toFixed(2), bands: [{ from: "2024-04-01", to: H.prices.XTIUSD.slice(-1)[0][0], label: "after futures data ends" }],
    aria: "WTI and Brent spot prices since mid-2023",
  });
  const rt = document.querySelector("#tbl-rolling tbody");
  RV.rolling.forEach((r) => {
    const tr = document.createElement("tr");
    cell(tr, `${r.years} year${r.years > 1 ? "s" : ""}`); cell(tr, pct(r.p_loss), "n"); cell(tr, spct(r.median), "n"); cell(tr, spct(r.worst), "n");
    rt.appendChild(tr);
  });

  // ---------------------------------------------------------------- intraday
  if ($("fig-intra") && DATA.agent && DATA.agent.intraday_mom_yearly) {
    const Iy = DATA.agent.intraday_mom_yearly;
    const med = Iy.map((d) => d[2]).sort((a, b) => a - b)[Math.floor(Iy.length / 2)];
    legend($("leg-intra"), [[`High-volatility year (> ${pct(med)})`, "--s1"], ["Calmer year", "--gray"]], true);
    Viz.columns($("fig-intra"), {
      categories: Iy.map((d) => String(d[0])),
      series: [{ name: "Net return", color: "--gray", values: Iy.map((d) => d[1] * 100) }],
      fmt: (v) => (v >= 0 ? "+" : "−") + Math.abs(v).toFixed(0) + "%", maxBar: 18, height: 240, aria: "Intraday momentum yearly returns",
      colorAt: (i) => (Iy[i][2] > med ? "--s1" : "--gray"),
    });
  }

  /*__AGENT_JS__*/
})();
