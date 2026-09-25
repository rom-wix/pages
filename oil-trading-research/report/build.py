"""Assemble the single-file HTML report from template + results.  python3 report/build.py"""
import html
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
R = os.path.join(ROOT, "results")
OUT = os.path.join(HERE, "oil-gas-bot-research.html")

ICON = {
    "build": '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M3 8.5l3.2 3L13 5" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    "maybe": '<svg viewBox="0 0 16 16" aria-hidden="true"><circle cx="8" cy="8" r="5.5" fill="none" stroke="currentColor" stroke-width="2"/><path d="M8 2.5a5.5 5.5 0 010 11z" fill="currentColor"/></svg>',
    "avoid": '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M4 4l8 8M12 4l-8 8" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"/></svg>',
}
LABEL = {"build": "Build", "maybe": "Test further", "avoid": "Avoid"}


def f2(x):
    return ("−" if x < 0 else "") + f"{abs(x):.2f}"


def main():
    D = json.load(open(os.path.join(R, "report_data.json")))
    H, RV, LY = D["headline"], D["revised"], D["last_year"]
    rob = {(r["name"], r["setting"]): r for r in D["robustness"]}
    C = LY["crude_sharpe"]
    ly_rev = (LY["revised"]["XTIUSD"]["sharpe"] + LY["revised"]["XBRUSD"]["sharpe"]) / 2
    extra = {}
    ap = os.path.join(HERE, "agent_results.json")
    if os.path.exists(ap):
        extra = json.load(open(ap))

    # ---------------- long-run scoreboard (one representative config per family) ----------------
    sb = [
        {"label": "Recommended bot", "sub": "multi-speed trend + crack, 3 markets", "value": RV["revised"]["sharpe"]},
        {"label": "Multi-speed trend", "sub": "without the crack tilt", "value": RV["revised_no_crack"]["sharpe"]},
        {"label": "Original slow trend blend", "sub": "EWMA 8–64 + breakouts 40–320", "value": H["trend"]["sharpe"]},
        {"label": "Crack-spread signal", "sub": "WTI + Brent", "value": H["crack"]["sharpe"]},
        {"label": "WTI settlement momentum", "sub": "intraday, 2005–2020, 1× notional", "value": 0.68},
        {"label": "Crude driving-season rule", "sub": "long Feb–May, short Oct–Dec", "value": 0.52},
        {"label": "Carry, 60-day smoothed", "sub": "3 markets", "value": 0.48},
        {"label": "Carry, raw, traded next day", "sub": "3 markets", "value": 0.35},
        {"label": "Opening-range breakout, WTI", "sub": "intraday, 2013–2020 out of sample", "value": 0.17},
        {"label": "Buy & hold, vol-targeted", "sub": "3 markets", "value": H["long_only"]["sharpe"]},
        {"label": "Gas seasonal (autumn long)", "sub": "on futures", "value": -0.17},
        {"label": "Daily mean reversion", "sub": "median of 19 rules", "value": -0.57},
        {"label": "Oil/gas ratio reversion", "sub": "WTI vs gas", "value": -0.17},
        {"label": "Brent–WTI spread reversion", "sub": "synchronous futures, best", "value": -0.78},
    ]
    sb += extra.get("scoreboard", [])
    sb.sort(key=lambda d: -d["value"])
    D["scoreboard"] = sb

    # ---------------- verdict rows: name, tested, 1991-2024, 2008-2024, last 12m, verdict, note ----------------
    rows = [
        ("Multi-speed trend following", "24 single rules and 6 speed blends; momentum, EWMA, breakouts, Turtle",
         f2(RV["revised_no_crack"]["sharpe"]), f2(RV["revised_no_crack"]["oos_sharpe"]), f2(ly_rev), "build",
         "Core engine. Positive in every decade and every market; the fast components carried the last year."),
        ("Crack-spread tilt (crude)", "z-score of the 3-2-1 refining margin; windows, lags, components",
         f2(H["crack"]["sharpe"]), f2(rob[("crack", "base")]["oos_sharpe"]), "n/a", "build",
         "Adds to trend; needs RBOB and ULSD prices."),
        ("Recommended bot (both)", "trend + crack for crude, trend for gas, volatility overlay",
         f2(RV["revised"]["sharpe"]), f2(RV["revised"]["oos_sharpe"]), f2(ly_rev) + "*", "build",
         "Start here. *Last 12 months without the crack part."),
        ("WTI settlement momentum (intraday)", "Gao et al. (2018) rule adapted to the 14:30 settlement; 44 variants",
         "0.68", "0.53", "n/a", "maybe", "Satellite only; needs ≤ 3 bp spreads. 2005–2020 data."),
        ("Crude seasonal tilt", "month-of-year, walk-forward seasonals, driving season",
         "0.52", "0.38", "1.37", "maybe",
         "Small add-on at most; not significant after correction."),
        ("Carry / curve shape", "sign, scaled, smoothed, seasonally adjusted; as trend filter", "0.48", "0.35", "n/a",
         "maybe", "Raw signal collapses with a one-day delay. Use it to understand swap costs."),
        ("Opening-range breakout", "486 variants per market incl. Crabel stretch", "0.29", "0.17", "n/a", "avoid",
         "Gross edge 5–10 bp a trade, costs 6–8 bp."),
        ("EIA report trading", "follow or fade the release, pre-report drift", "≤ 0.35", "≤ 0.36", "n/a", "avoid",
         "Use the report times as risk filters instead."),
        ("Daily mean reversion", "19 rules: reversals, z-fades, RSI(2), shock fades, IBS", "−0.9 to 0.20", "≤ 0.17",
         f2(LY["mr_median"]), "avoid", "Oil trends at these horizons; losses even before costs."),
        ("Brent–WTI spread", "z-score reversion and spread trend on futures and spot", "−2.0 to 0.19", "< 0.2", "0.55",
         "avoid", "Spot results of 2.5–3.1 are a timing artefact."),
        ("Oil/gas ratio", "reversion and trend on WTI vs gas", "−0.54 to 0.05", "≤ 0.21", "n/a", "avoid",
         "Structural break after the shale boom."),
        ("Gas seasonals and intraday gas", "autumn long, spring short; every intraday family", "≤ 0.05", "≤ 0.36", "n/a",
         "avoid", "Contango and 20 bp round trips eat it."),
    ]
    rows += [tuple(r) for r in extra.get("verdict_rows", [])]
    order = {"build": 0, "maybe": 1, "avoid": 2}
    rows.sort(key=lambda r: order[r[5]])
    trs = []
    for name, what, sr, oos, ly, v, note in rows:
        trs.append(
            f'<tr><td><strong>{html.escape(name)}</strong><span class="sub">{html.escape(note)}</span></td>'
            f'<td>{html.escape(what)}</td><td class="n">{html.escape(sr)}</td><td class="n">{html.escape(oos)}</td>'
            f'<td class="n">{html.escape(ly)}</td><td><span class="chip {v}">{ICON[v]}{LABEL[v]}</span></td></tr>')

    tpl = open(os.path.join(HERE, "template.html")).read()
    tpl = tpl.replace("<!--VERDICT_ROWS-->", "\n".join(trs))
    for key in ["INTRADAY", "ML", "GRID", "DIRECTION2"]:
        p = os.path.join(HERE, "sections", key.lower() + ".html")
        if os.path.exists(p):
            tpl = tpl.replace(f"<!--{key}-->", open(p).read())
    charts = open(os.path.join(HERE, "charts.js")).read()
    page = open(os.path.join(HERE, "page.js")).read()
    ajs = os.path.join(HERE, "sections", "agent.js")
    if os.path.exists(ajs):
        page = page.replace("/*__AGENT_JS__*/", open(ajs).read())
    if "agent_data" in extra:
        D["agent"] = extra["agent_data"]
    tpl = tpl.replace("/*__CHARTS_JS__*/", charts).replace("/*__PAGE_JS__*/", page)
    tpl = tpl.replace("/*__DATA__*/", json.dumps(D, separators=(",", ":"), default=float))
    open(OUT, "w").write(tpl)
    print("wrote", OUT, os.path.getsize(OUT) // 1024, "KB")


if __name__ == "__main__":
    main()
