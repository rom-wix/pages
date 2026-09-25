"""Assemble the single-file HTML report from template + results.  python3 report/build.py"""
import html
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
R = os.path.join(ROOT, "results")
OUT = os.path.join(HERE, "oil-gas-bot-research.html")


def load(p):
    return json.load(open(os.path.join(R, p)))


def main():
    D = load("report_data.json")
    H = D["headline"]
    ex = D["extras"]
    rob = {(r["name"], r["setting"]): r for r in D["robustness"]}
    tc = H["trend+crack"]
    roll_dd = [r for r in ex["rolling"] if r["strategy"] == "trend+crack" and r["years"] == "dd"][0]
    p1 = [r for r in ex["rolling"] if r["strategy"] == "trend+crack" and r["years"] == 1][0]
    D["kpi"] = {"sharpe": tc["sharpe"], "t_stat": tc["t_stat"], "cagr": tc["cagr"], "ann_vol": tc["ann_vol"],
                "max_dd": tc["max_dd"], "oos": rob[("trend+crack", "base")]["oos_sharpe"],
                "underwater": roll_dd["longest_underwater_years"], "p_loss_1y": p1["p_loss"],
                "cost": 0.0137}
    extra = json.load(open(os.path.join(HERE, "agent_results.json"))) if os.path.exists(
        os.path.join(HERE, "agent_results.json")) else {}

    # ---------------- scoreboard (one representative config per family) ----------------
    sb = [
        {"label": "Trend + crack tilt", "sub": "3 markets, recommended", "value": tc["sharpe"], "tip": "1991–2024, net"},
        {"label": "Trend following", "sub": "blend of 8 rules, 3 markets", "value": H["trend"]["sharpe"]},
        {"label": "Crack-spread signal", "sub": "WTI + Brent", "value": H["crack"]["sharpe"]},
        {"label": "Carry, 60-day smoothed", "sub": "3 markets", "value": rob.get(("carry", "base"), {}).get("sharpe", 0.483) if False else 0.483},
        {"label": "Carry, raw, traded next day", "sub": "3 markets", "value": 0.35},
    ]
    sb += extra.get("scoreboard", [])
    sb += [
        {"label": "Buy & hold, vol-targeted", "sub": "3 markets", "value": H["long_only"]["sharpe"]},
        {"label": "Daily mean reversion", "sub": "best of 19 rules, excl. RSI dips", "value": -0.02},
        {"label": "Daily mean reversion", "sub": "typical (median) rule", "value": -0.57},
        {"label": "Oil/gas ratio reversion", "sub": "WTI vs gas", "value": -0.17},
        {"label": "Brent–WTI spread reversion", "sub": "synchronous futures, best", "value": -0.78},
    ]
    sb.sort(key=lambda d: -d["value"])
    D["scoreboard"] = sb

    # ---------------- verdict table rows ----------------
    icon = {
        "build": '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M3 8.5l3.2 3L13 5" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/></svg>',
        "maybe": '<svg viewBox="0 0 16 16" aria-hidden="true"><circle cx="8" cy="8" r="5.5" fill="none" stroke="currentColor" stroke-width="2"/><path d="M8 2.5a5.5 5.5 0 010 11z" fill="currentColor"/></svg>',
        "avoid": '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M4 4l8 8M12 4l-8 8" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"/></svg>',
    }
    label = {"build": "Build", "maybe": "Test further", "avoid": "Avoid"}
    rows = [
        ("Trend following", "24 rules: momentum, SMA/EWMA crossovers, breakouts, Turtle; blends", f'{H["trend"]["sharpe"]:.2f}',
         f'{rob[("trend", "base")]["oos_sharpe"]:.2f}', "build", "Core engine. Positive in every decade and every market."),
        ("Crack-spread tilt (crude)", "z-score of 3-2-1 refining margin; windows, lags, components", f'{H["crack"]["sharpe"]:.2f}',
         f'{rob[("crack", "base")]["oos_sharpe"]:.2f}', "build", "Adds to trend; needs RBOB and ULSD prices."),
        ("Trend + crack combined", "50/50 blend for crude, trend only for gas", f'{tc["sharpe"]:.2f}',
         f'{rob[("trend+crack", "base")]["oos_sharpe"]:.2f}', "build", "Recommended starting point."),
        ("Carry / curve shape", "sign, scaled, smoothed, seasonally adjusted; as trend filter", "0.48",
         "0.35", "maybe", "Raw signal collapses with a one-day delay. Use it to understand swap costs."),
    ]
    rows += [tuple(r) for r in extra.get("verdict_rows", [])]
    rows += [
        ("Daily mean reversion", "19 rules: reversals, z-fades, RSI(2), shock fades, IBS", "−0.9 to 0.20", "≤ 0.17",
         "avoid", "Oil trends at these horizons; losses even before costs."),
        ("Brent–WTI spread", "z-score reversion and spread trend on futures and spot", "−2.0 to 0.19", "< 0.2",
         "avoid", "Spot results of 2.5–3.1 are a timing artefact."),
        ("Oil/gas ratio", "reversion and trend on WTI vs gas", "−0.54 to 0.05", "≤ 0.21", "avoid",
         "Structural break after the shale boom."),
    ]
    order = {"build": 0, "maybe": 1, "avoid": 2}
    rows.sort(key=lambda r: order[r[4]])
    trs = []
    for name, what, sr, oos, v, note in rows:
        trs.append(
            f'<tr><td><strong>{html.escape(name)}</strong><span class="sub">{html.escape(note)}</span></td>'
            f'<td>{html.escape(what)}</td><td class="n">{html.escape(sr)}</td><td class="n">{html.escape(oos)}</td>'
            f'<td><span class="chip {v}">{icon[v]}{label[v]}</span></td></tr>')

    tpl = open(os.path.join(HERE, "template.html")).read()
    tpl = tpl.replace("<!--VERDICT_ROWS-->", "\n".join(trs))
    for key in ["SEASONALITY", "INTRADAY", "ML", "GRID", "DIRECTION2"]:
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
