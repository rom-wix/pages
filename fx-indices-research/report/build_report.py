"""Build ../../fx-indices-strategies.html from results/report_data.json (tables rendered here, charts in the page JS)."""
import html
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
D = json.load(open(os.path.join(ROOT, "results", "report_data.json")))
OUT = os.path.join(os.path.dirname(ROOT), "fx-indices-strategies.html")

NAMES = {
    "S01_london_breakout": ("London breakout", "Breakout", "FX (8)",
        "Asian box 00:00–07:00 London. Stop orders 3% ATR beyond both edges (one cancels the other), live 07:00–11:00. "
        "SL opposite edge · TP 1× box · exit 16:00 London. Skip boxes > 0.6 ATR."),
    "S02_orb": ("Opening-range breakout", "Breakout", "Indices (8)",
        "Range of the first 30 min of the cash session. Stop orders at its high/low for 3 h. SL other side · TP 2R · exit 5 min before the close."),
    "S03_noise_momentum": ("Noise-area momentum", "Momentum", "Indices (8)",
        "Zarattini–Aziz–Barbon bands (open ± average move-from-open, 14 days). Checked every 30 min; enter on a close outside the band; "
        "exit back inside band/VWAP or at the close; hard SL 0.5 ATR."),
    "S04_gap_fade": ("Opening-gap fade", "Mean reversion", "Indices (8)",
        "Gap of 0.15–0.6 ATR between the prior cash close and the open: fade at the open. TP prior close · SL 1× gap · exit after 2.5 h."),
    "S05_sweep_reversal": ("Prior-day high/low sweep", "Range / reversal", "All (16)",
        "A 15m bar trades through the prior day's high (low) and closes back inside: fade at the next bar. SL beyond the bar + 5% ATR · TP 2R · 8 h max."),
    "S06_trend_pullback": ("Trend pullback", "Pullback", "All (16)",
        "New 20-day high in the last 5 days, 1h pullback ≥ 0.5 ATR, enter when a 1h bar closes above the prior bar's high (mirror for shorts). "
        "SL pullback extreme · TP 2R · 72 h max."),
    "S07_asian_fade": ("Asian-session range fade", "Range", "FX (8)",
        "19:30–00:30 New York: a 15m close beyond the prior 2 h range is faded. TP range midpoint · SL 1× range · exit 02:00 NY."),
    "S08_tokyo_fix": ("Tokyo-fix flow (gotobi)", "Flow / calendar", "USDJPY, EURJPY",
        "On gotobi days (5th, 10th … month-end): long 08:00 → 09:55 JST fix. SL 0.3 ATR."),
    "S09_news_momentum": ("US data-release shock", "News", "USD pairs + US indices (10)",
        "08:30 ET candle ≥ 2.5× its 20-day median range with a body ≥ 50%: follow at 08:45 (fade variant in the grid). "
        "SL candle midpoint · TP 2R · exit 12:00 ET."),
    "S10_eur_seasonality": ("Home-hours seasonality", "Flow / calendar", "EURUSD, GBPUSD, USDCHF",
        "Breedon–Ranaldo: a currency weakens in its own business hours. Short EUR/GBP (long USDCHF) 03:00 → 11:00 NY; SL 0.4 ATR. US-afternoon leg in the grid."),
    "S11_nr_breakout": ("NR4 inside-bar breakout", "Breakout", "All (16)",
        "4h bar that is an inside bar and the narrowest of 4: stop orders at its high/low for 2 bars. SL other side · TP 2× bar range · 24 h max."),
    "S12_last_half_hour": ("Last-half-hour momentum", "Momentum", "Indices (8)",
        "Gao–Han–Li–Zhou: sign of prior close → first 30 min predicts the last 30 min. Trade the last 30 min of the cash session; SL 0.25 ATR."),
    "S13_overnight_drift": ("Overnight drift", "Calendar", "Indices (8)",
        "Long 5 min before the cash close → 5 min after the next open, Mon–Thu. SL 0.6 ATR."),
}
R2 = {
    "R2a_jpy_shock_follow": ("JPY big-move continuation", "USDJPY, EURJPY", "15m bar ≥ 2.5σ: follow at the next bar, SL 1× bar range, exit after 4 h"),
    "R2b_usidx_shock_fade": ("US-index big-move fade", "US500, NAS100, US30, US2000", "15m bar ≥ 2.5σ: fade, TP ½ bar range, SL 1× range, exit after 4 h"),
    "R2c_fxmaj_shock_fade": ("FX-majors big-move fade", "6 non-JPY pairs", "15m bar ≥ 2.5σ: fade, TP ½ bar range, SL 1× range, exit after 4 h"),
    "R2d_rowidx_1h_follow": ("Europe/Asia index 1h continuation", "GER40, EUSTX50, JPN225, AUS200", "1h bar ≥ 2σ: follow, SL 1× bar range, exit after 4 h"),
}
e = html.escape


def f(x, nd=2, sign=True, pct=False):
    if x is None:
        return "–"
    if pct:
        return f"{x * 100:.0f}%"
    s = f"{x:+.{nd}f}" if sign else f"{x:.{nd}f}"
    return s.replace("-", "−")


def cls(x, t=None):
    if x is None:
        return ""
    return "pos" if x > 0 else "neg"


def cfg_text(c):
    try:
        d = json.loads(c)
    except Exception:
        return e(str(c))
    return e(", ".join(f"{k}={v}" for k, v in d.items()))


fam_rows = []
for r in sorted(D["families"], key=lambda r: -r["d_net"]):
    name, kind, uni, rule = NAMES[r["family"]]
    fam_rows.append(f"""<tr>
<td class="name"><b>{e(name)}</b><span class="kind">{e(kind)} · {e(uni)}</span><span class="rule">{e(rule)}</span></td>
<td class="num">{r['d_n']:,}</td><td class="num">{r['d_week']:.1f}</td><td class="num">{f(r['d_win'], pct=True)}</td>
<td class="num">{f(r['d_gross'])}</td><td class="num {cls(r['d_net'])}"><b>{f(r['d_net'])}</b></td><td class="num">{f(r['d_t'], 1)}</td>
<td class="num {cls(r['d_h1'])}">{f(r['d_h1'])}</td><td class="num {cls(r['d_h2'])}">{f(r['d_h2'])}</td>
<td class="num">{int(round(r['share_both'] * r['n_cfg']))} / {r['n_cfg']}</td>
<td class="num {cls(r['b_net'])}">{f(r['b_net'])}<span class="sub">t {f(r['b_t'], 1, sign=False)}</span></td>
</tr>""")

r2_rows = []
for r in D["round2"]:
    name, uni, rule = R2[r["family"]]
    verdict = "Failed" if not (r["h2_r"] > 0 and r["h1_r"] > 0) else "Passed"
    r2_rows.append(f"""<tr><td class="name"><b>{e(name)}</b><span class="kind">{e(uni)}</span><span class="rule">{e(rule)}</span></td>
<td class="num">{r['h1_n']}</td><td class="num {cls(r['h1_r'])}">{f(r['h1_r'])}</td><td class="num">{f(r['h1_t'], 1)}</td>
<td class="num">{r['h2_n']}</td><td class="num {cls(r['h2_r'])}"><b>{f(r['h2_r'])}</b></td><td class="num">{f(r['h2_t'], 1)}</td>
<td><span class="tag bad">{verdict}</span></td></tr>""")

r3 = {}
for r in D["round3"]:
    r3.setdefault(r["family"], []).append(r)
don = sorted(r3["R3a_donchian_4h"], key=lambda r: -r["avg_r"])
dip = sorted(r3["R3b_dip_buy_idx"], key=lambda r: -r["avg_r"])
rnd = r3["R3c_random_long_idx"]
rnd_avg = sum(r["avg_r"] for r in rnd) / len(rnd)

vr_rows = "".join(
    f"<tr><td>{e(v['sym'])}</td>" + "".join(f"<td class='num {'hi' if v[k] and v[k] > 1 else ''}'>{v[k]:.2f}</td>" for k in ("h1_4h", "h2_4h", "h1_1d", "h2_1d")) + "</tr>"
    for v in sorted(D["vr"], key=lambda v: -(v["h1_1d"] + v["h2_1d"])))

m, sc = D["meta"], D["screen"]
fam_json = json.dumps([dict(name=NAMES[r["family"]][0], gross=r["d_gross"], net=r["d_net"], n=r["d_n"]) for r in D["families"]])
cfg_json = json.dumps([dict(fam=(NAMES.get(c["family"], (c["family"],))[0] if c["family"] in NAMES else
                                 {"R3a_donchian_4h": "4h Donchian breakout", "R3b_dip_buy_idx": "Index dip-buy"}.get(c["family"], c["family"])),
                            cfg=c["cfg"], n=c["n"], h1=c["h1"], h2=c["h2"], avg=c["avg_r"]) for c in D["configs"] if c["h1"] is not None and c["h2"] is not None])
round1_both = sum(int(round(r["share_both"] * r["n_cfg"])) for r in D["families"])
round1_cfgs = sum(r["n_cfg"] for r in D["families"])

page = open(os.path.join(HERE, "template.html")).read()
for k, v in {
    "__FAM_ROWS__": "\n".join(fam_rows), "__R2_ROWS__": "\n".join(r2_rows), "__VR_ROWS__": vr_rows,
    "__FAM_JSON__": fam_json, "__CFG_JSON__": cfg_json,
    "__START__": "1 Feb 2026", "__END__": "25 Sep 2026", "__WEEKS__": f"{m['weeks']:.0f}",
    "__TRADES__": f"{m['trades_simulated']:,}", "__CONFIGS__": str(m["configs"]),
    "__R1_BOTH__": str(round1_both), "__R1_CFGS__": str(round1_cfgs),
    "__SC_TESTS__": f"{sc['tests']:,}", "__SC_HITS__": str(sc["t_ge2"]), "__SC_CHANCE__": str(sc["chance_t_ge2"]), "__SC_NEG__": str(sc["t_le_m2"]),
    "__DON_ALL__": f(don[0]["avg_r"]) + " to " + f(don[-1]["avg_r"]), "__DON_JPY__": f(max(r["jpy"] for r in don)),
    "__DIP_BEST__": f(dip[0]["avg_r"]), "__DIP_N__": str(dip[0]["n"]), "__RND__": f(rnd_avg),
}.items():
    page = page.replace(k, v)
open(OUT, "w").write(page)
print("wrote", OUT, len(page) // 1024, "KB")
