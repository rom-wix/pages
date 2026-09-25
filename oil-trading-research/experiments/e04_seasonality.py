"""E04 - Seasonality & calendar effects (daily futures; EIA spot for comparison).

Sections
  A  Month-of-year returns (futures + spot), t-stats, halves 1990-2007 / 2008-2024, joint tests, FDR
  B  Walk-forward seasonal strategy: each month, trade the sign / t-stat of that calendar month's trailing
     mean over the previous N years (N = 5, 10, 15, expanding).  Strictly causal.
  C  Fixed hypotheses: crude driving season / Q4 weakness; NG autumn long / late-winter short;
     NG contango decomposition (spot vs futures vs carry) and carry-conditioned variants
  D  Daily calendar effects: day-of-week, turn-of-month, EIA report day, pre/post US holiday,
     futures expiry week / LTD / options expiry, index-roll window
  E  Daily-effect standalone bots (fixed-sign and walk-forward-sign)
  F  Multiple testing: variant count, BH-FDR, deflated Sharpe of the best variants
  G  Overlay: trend-only vs trend + seasonal tilt;  lag=2 and 2x-cost robustness

Timing: signal at close t uses data <= t and calendar facts about t+1 (known in advance);
evaluate(lag=1) trades at close t and earns ret[t+1].
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import warnings  # noqa: E402

warnings.filterwarnings("ignore")

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from scipy import stats  # noqa: E402
import statsmodels.api as sm  # noqa: E402
from statsmodels.stats.multitest import multipletests  # noqa: E402

from src import backtest as bt  # noqa: E402
from src import calendar_tools as ct  # noqa: E402
from src import plotstyle as ps  # noqa: E402
from src import signals as sg  # noqa: E402
from src.data import SYMBOLS  # noqa: E402
from src.evaluate import IS_END, evaluate, get_dataset, show  # noqa: E402

OUT = os.path.join(ROOT, "results")
pd.set_option("display.width", 250)
pd.set_option("display.max_columns", 40)
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

FUT = get_dataset("fut")
SPOT = get_dataset("spot")
# US-calendar futures for day-level work: returns on US-holiday rows folded into the next US trading day
FUTC = {s: ct.merge_holiday_rows(df).assign(sym=s) for s, df in FUT.items()}
FUT_S = {s: df.assign(sym=s) for s, df in FUT.items()}
SPOT_S = {s: df.assign(sym=s) for s, df in SPOT.items()}

TREND = lambda d: sg.multi_ewmac(d["tri"], d["ret"])  # noqa: E731
ALL_EVALS = []  # every standalone variant evaluated (for the multiple-testing count)


def run_eval(fn, name, family, data, kind="fut", **kw):
    res = evaluate(fn, name, kind=kind, data=data, keep_series=True, **kw)
    t = res["table"]
    t["family"] = family
    t["lag"] = kw.get("lag", 1)
    t["cost_mult"] = kw.get("cost_mult", 1.0)
    t["window_start"] = kw.get("start") or ""
    ALL_EVALS.append(t.copy())
    return res


def next_dates(idx: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """Date of the next row (the day whose return a position set at close t earns)."""
    last = pd.DatetimeIndex([idx[-1] + pd.offsets.BDay(1)])
    return idx[1:].append(last)


# ================================================================================================
# A. Month-of-year
# ================================================================================================
def monthly_returns(ret: pd.Series) -> pd.DataFrame:
    """Compounded calendar-month returns; the first and last (partial) months are dropped."""
    m = (1 + ret).groupby([ret.index.year, ret.index.month]).prod() - 1
    m.index.names = ["year", "month"]
    m = m.iloc[1:-1]
    return m.reset_index(name="r")


PERIODS = {"full": (0, 9999), "1990-2007": (1990, 2007), "2008-2024": (2008, 2024)}


def moy_table(data: dict, kind: str) -> pd.DataFrame:
    rows = []
    for s, df in data.items():
        m = monthly_returns(df["ret"])
        for per, (a, b) in PERIODS.items():
            x = m[(m.year >= a) & (m.year <= b)]
            for mo, g in x.groupby("month")["r"]:
                n = len(g)
                mu, sd = g.mean(), g.std(ddof=1)
                t = mu / (sd / np.sqrt(n)) if sd > 0 else np.nan
                rows.append({"dataset": kind, "symbol": s, "period": per, "month": mo, "n_years": n,
                             "first_year": int(x.year.min()), "last_year": int(x.year.max()),
                             "mean_pct": mu * 100, "median_pct": g.median() * 100, "sd_pct": sd * 100,
                             "t_stat": t, "p_value": 2 * stats.t.sf(abs(t), n - 1), "pct_pos": (g > 0).mean()})
    return pd.DataFrame(rows)


def moy_joint(data: dict, kind: str) -> pd.DataFrame:
    rows = []
    for s, df in data.items():
        m = monthly_returns(df["ret"])
        groups = [g.values for _, g in m.groupby("month")["r"]]
        kw = stats.kruskal(*groups)
        an = stats.f_oneway(*groups)
        h1 = m[(m.year >= 1990) & (m.year <= 2007)].groupby("month")["r"].mean()
        h2 = m[(m.year >= 2008) & (m.year <= 2024)].groupby("month")["r"].mean()
        rho = np.corrcoef(h1, h2)[0, 1]
        sign_agree = int((np.sign(h1) == np.sign(h2)).sum())
        rows.append({"dataset": kind, "symbol": s, "years": f"{m.year.min()}-{m.year.max()}",
                     "anova_p": an.pvalue, "kruskal_p": kw.pvalue, "split_half_corr": rho,
                     "sign_agree_of_12": sign_agree})
    return pd.DataFrame(rows)


def ng_decomposition() -> pd.DataFrame:
    """NG: spot (Henry Hub) vs futures monthly returns vs average carry, common window 1997-2024."""
    f = FUT["XNGUSD"]
    sp = SPOT["XNGUSD"]
    end = f.index[-1]
    mf = monthly_returns(f["ret"])
    ms = monthly_returns(sp["ret"][sp.index <= end])
    c = f["carry"].groupby([f.index.year, f.index.month]).mean()
    c.index.names = ["year", "month"]
    c = c.reset_index(name="carry")
    j = mf.merge(ms, on=["year", "month"], suffixes=("_fut", "_spot")).merge(c, on=["year", "month"])
    j = j[j.year >= 1997]
    out = j.groupby("month").agg(fut_mean_pct=("r_fut", lambda x: x.mean() * 100),
                                 spot_mean_pct=("r_spot", lambda x: x.mean() * 100),
                                 carry_ann_pct=("carry", lambda x: x.mean() * 100),
                                 n=("r_fut", "size"))
    out["carry_month_pct"] = out["carry_ann_pct"] / 12
    out["fut_minus_spot_pct"] = out["fut_mean_pct"] - out["spot_mean_pct"]
    # regression across all months: fut = a + b*spot + c*carry/12
    X = sm.add_constant(pd.DataFrame({"spot": j["r_spot"], "carry_m": j["carry"] / 12}))
    ols = sm.OLS(j["r_fut"], X).fit(cov_type="HC1")
    out.attrs["ols"] = ols
    # within-month regression: does de-seasonalised carry at the start of a month predict that month's return?
    c_start = f["carry"].groupby([f.index.year, f.index.month]).first()
    c_start.index.names = ["year", "month"]
    k = mf.merge(c_start.reset_index(name="c0"), on=["year", "month"])
    k["c0_dm"] = k["c0"] - k.groupby("month")["c0"].transform("mean")
    X2 = pd.get_dummies(k["month"], prefix="m", drop_first=False).astype(float)
    X2["c0_dm"] = k["c0_dm"]
    ols2 = sm.OLS(k["r"], X2).fit(cov_type="HC1")
    out.attrs["ols_carry_fe"] = ols2
    return out


# ================================================================================================
# B. Walk-forward seasonal strategy
# ================================================================================================
def seasonal_scores(ret: pd.Series, N: int | None, mode: str, min_years: int = 5) -> pd.DataFrame:
    """score[Y, m] from calendar-month-m returns of years Y-N..Y-1 only (expanding if N is None)."""
    m = monthly_returns(ret)
    tab = m.pivot(index="year", columns="month", values="r")
    years = list(range(int(tab.index.min()) + 1, int(tab.index.max()) + 2))
    sc = pd.DataFrame(np.nan, index=years, columns=range(1, 13))
    for Y in years:
        past = tab[tab.index < Y]
        if N is not None:
            past = past[past.index >= Y - N]
        for mo in range(1, 13):
            x = past[mo].dropna() if mo in past.columns else pd.Series(dtype=float)
            need = N if N is not None else min_years
            if len(x) < need:
                continue
            mu = x.mean()
            if mode == "sign":
                sc.loc[Y, mo] = np.sign(mu)
            else:
                se = x.std(ddof=1) / np.sqrt(len(x))
                sc.loc[Y, mo] = float(np.clip(mu / se / 2.0, -1, 1)) if se > 0 else 0.0
    return sc


def wf_seasonal_fn(N, mode):
    def fn(df):
        sc = seasonal_scores(df["ret"], N, mode)
        nd = next_dates(df.index)
        lut = sc.stack()
        keys = list(zip(nd.year, nd.month))
        vals = lut.reindex(pd.MultiIndex.from_tuples(keys)).values
        return pd.Series(vals, index=df.index).fillna(0.0)
    return fn


def first_live(fn, data) -> str:
    starts = []
    for s, df in data.items():
        sig = fn(df)
        nz = sig[sig != 0]
        if len(nz):
            starts.append(nz.index[0])
    return str(max(starts).date()) if starts else None


# ================================================================================================
# C. Fixed hypotheses
# ================================================================================================
def month_rule_fn(long_m=(), short_m=()):
    def fn(df):
        nm = next_dates(df.index).month
        s = np.where(np.isin(nm, long_m), 1.0, np.where(np.isin(nm, short_m), -1.0, 0.0))
        return pd.Series(s, index=df.index)
    return fn


def carry_sign_fn(df):
    return np.sign(df["carry"]).fillna(0.0)


def carry_deseason_fn(years=5):
    """sign(carry_t - mean carry of the same calendar month in the previous `years` years)."""
    def fn(df):
        c = df["carry"]
        cm = c.groupby([c.index.year, c.index.month]).mean()
        tab = cm.unstack()
        base = tab.shift(1).rolling(years, min_periods=3).mean()  # previous years only
        keys = pd.MultiIndex.from_arrays([c.index.year, c.index.month])
        b = base.stack().reindex(keys).values
        return pd.Series(np.sign(c.values - b), index=c.index).fillna(0.0)
    return fn


def rule_with_carry_filter(long_m=(), short_m=(), mode="less_contango", years=5):
    """Month rule, but only take the trade when de-seasonalised carry agrees with its direction
    (longs only when contango is *less* steep than the same month's 5-y norm, shorts only when steeper)."""
    base_rule = month_rule_fn(long_m, short_m)
    cds = carry_deseason_fn(years)

    def fn(df):
        r = base_rule(df)
        c = cds(df)
        keep = ((r > 0) & (c > 0)) | ((r < 0) & (c < 0))
        return r.where(keep, 0.0)
    return fn


# ================================================================================================
# D/E. Daily calendar effects
# ================================================================================================
EFFECTS = ["tom", "eia", "pre_hol", "post_hol", "exp_week", "ltd", "opt_exp", "roll_win"]
EFFECT_LABEL = {"tom": "Turn of month (last 1 + first 3)", "eia": "EIA report day", "pre_hol": "Pre-holiday day",
                "post_hol": "Post-holiday day", "exp_week": "Expiry week (5d to LTD)", "ltd": "Futures LTD",
                "opt_exp": "Options expiry day", "roll_win": "Index roll window (BD 5-9)",
                "dow0": "Monday", "dow1": "Tuesday", "dow2": "Wednesday", "dow3": "Thursday", "dow4": "Friday"}


def daily_frame(df: pd.DataFrame, sym: str, gapfree: bool) -> pd.DataFrame:
    f = ct.calendar_flags(df.index, sym)
    f["ret"] = df["ret"]
    if gapfree:
        f = f[ct.gap_free(df["ret"]).values]
    f = f.dropna(subset=["dow"])
    for d in range(5):
        f[f"dow{d}"] = (f["dow"] == d).astype(int)
    return f


def effect_tests(data: dict, kind: str) -> pd.DataFrame:
    rows = []
    for s, df in data.items():
        f = daily_frame(df, s, gapfree=(kind == "spot"))
        for per, (a, b) in PERIODS.items():
            x = f[(f.index.year >= a) & (f.index.year <= b)]
            for e in EFFECTS + [f"dow{d}" for d in range(5)]:
                on, off = x.loc[x[e] == 1, "ret"], x.loc[x[e] == 0, "ret"]
                if len(on) < 20:
                    continue
                tt = stats.ttest_ind(on, off, equal_var=False)
                t1 = stats.ttest_1samp(on, 0.0)
                rows.append({"dataset": kind, "symbol": s, "period": per, "effect": e, "n_on": len(on),
                             "mean_on_bp": on.mean() * 1e4, "mean_off_bp": off.mean() * 1e4,
                             "diff_bp": (on.mean() - off.mean()) * 1e4, "t_diff": tt.statistic,
                             "p_diff": tt.pvalue, "t_on_vs_0": t1.statistic, "p_on_vs_0": t1.pvalue,
                             "vol_ratio": on.std() / off.std(), "hit_on": (on > 0).mean()})
        # joint day-of-week test (full sample)
        g = [f.loc[f["dow"] == d, "ret"].values for d in range(5)]
        rows.append({"dataset": kind, "symbol": s, "period": "full", "effect": "dow_anova",
                     "n_on": len(f), "p_diff": stats.f_oneway(*g).pvalue,
                     "t_diff": np.nan})
    return pd.DataFrame(rows)


def flag_fixed_fn(flag, sign=1.0):
    def fn(df):
        sym = df["sym"].iloc[0]
        nf = ct.next_row_flags(df.index, sym)
        if flag.startswith("dow"):
            on = (nf["dow"] == int(flag[3:])).astype(float)
        else:
            on = nf[flag].fillna(0.0)
        return (on * sign).fillna(0.0)
    return fn


def flag_wf_fn(flag, min_obs=30):
    """Trade only on flagged days, direction = sign of the expanding mean of *past* flagged-day returns."""
    def fn(df):
        sym = df["sym"].iloc[0]
        cf = ct.calendar_flags(df.index, sym)
        nf = ct.next_row_flags(df.index, sym)
        if flag.startswith("dow"):
            cur = (cf["dow"] == int(flag[3:])).astype(float)
            nxt = (nf["dow"] == int(flag[3:])).astype(float)
        else:
            cur, nxt = cf[flag].fillna(0.0), nf[flag].fillna(0.0)
        fr = df["ret"].where(cur == 1)
        mu = fr.expanding().mean()
        n = fr.expanding().count()
        sgn = np.sign(mu).where(n >= min_obs, 0.0).ffill().fillna(0.0)
        return (nxt * sgn).fillna(0.0)
    return fn


def dow_wf_fn(min_obs=100):
    """Always in the market: each day, the sign of that weekday's expanding past mean return."""
    def fn(df):
        sym = df["sym"].iloc[0]
        cd = ct.calendar_flags(df.index, sym)["dow"]
        nd = ct.next_row_flags(df.index, sym)["dow"]
        out = pd.Series(0.0, index=df.index)
        for d in range(5):
            fr = df["ret"].where(cd == d)
            mu = fr.expanding().mean().ffill()
            n = fr.expanding().count()
            sgn = np.sign(mu).where(n >= min_obs, 0.0).fillna(0.0)
            out = out.where(nd != d, sgn)
        return out.fillna(0.0)
    return fn


# ================================================================================================
# helpers for tables
# ================================================================================================
KEEP = ["name", "family", "symbol", "dataset", "window_start", "lag", "cost_mult", "start", "end", "years",
        "sharpe", "is_sharpe", "oos_sharpe", "gross_sharpe", "cagr", "ann_vol", "max_dd", "t_stat",
        "turnover_py", "cost_py", "time_in_mkt", "sr_1990-1999", "sr_2000-2009", "sr_2010-2019", "sr_2020-2029"]


def tidy(t: pd.DataFrame) -> pd.DataFrame:
    return t[[c for c in KEEP if c in t.columns]]


def port_turnover(t: pd.DataFrame) -> float:
    return float(t.loc[t.symbol != "PORT", "turnover_py"].mean())


def main():
    ps.apply()
    # ------------------------------------------------------------------ A
    moy = pd.concat([moy_table(FUT, "fut"), moy_table(SPOT, "spot")], ignore_index=True)
    # BH-FDR across the 36 futures full-sample month cells (and separately for spot)
    moy["p_bh"] = np.nan
    for kind in ["fut", "spot"]:
        mask = (moy.dataset == kind) & (moy.period == "full")
        moy.loc[mask, "p_bh"] = multipletests(moy.loc[mask, "p_value"], method="fdr_bh")[1]
        moy.loc[mask, "p_holm"] = multipletests(moy.loc[mask, "p_value"], method="holm")[1]
    moy.to_csv(os.path.join(OUT, "e04_month_of_year.csv"), index=False)
    joint = pd.concat([moy_joint(FUT, "fut"), moy_joint(SPOT, "spot")], ignore_index=True)
    joint.to_csv(os.path.join(OUT, "e04_month_of_year_joint_tests.csv"), index=False)
    print("\n=== A. month-of-year joint tests\n", joint.round(3).to_string(index=False))
    full_f = moy[(moy.dataset == "fut") & (moy.period == "full")]
    print("\nfutures cells with |t|>2 (full):\n",
          full_f.loc[full_f.t_stat.abs() > 2, ["symbol", "month", "mean_pct", "t_stat", "p_value", "p_bh", "p_holm"]]
          .round(3).to_string(index=False))
    ngd = ng_decomposition()
    ngd.to_csv(os.path.join(OUT, "e04_ng_spot_vs_futures_by_month.csv"))
    print("\n=== NG decomposition (1997-2024)\n", ngd.round(2).to_string())
    ols = ngd.attrs["ols"]
    ols2 = ngd.attrs["ols_carry_fe"]
    ng_reg = pd.DataFrame({
        "model": ["fut ~ spot + carry/12", "fut ~ spot + carry/12", "fut ~ spot + carry/12",
                  "fut ~ month FE + demeaned carry (start of month)"],
        "term": ["const", "spot", "carry_m", "c0_dm"],
        "coef": [ols.params["const"], ols.params["spot"], ols.params["carry_m"], ols2.params["c0_dm"]],
        "t": [ols.tvalues["const"], ols.tvalues["spot"], ols.tvalues["carry_m"], ols2.tvalues["c0_dm"]],
        "r2": [ols.rsquared] * 3 + [ols2.rsquared]})
    ng_reg.to_csv(os.path.join(OUT, "e04_ng_carry_regressions.csv"), index=False)
    print(ng_reg.round(3).to_string(index=False))

    # ------------------------------------------------------------------ B
    wf_rows = []
    wf_series = {}
    variants = [(N, mode) for N in [5, 10, 15, None] for mode in ["sign", "tstat"]]
    for N, mode in variants:
        nm = f"wf_seasonal_N{N or 'exp'}_{mode}"
        fn = wf_seasonal_fn(N, mode)
        for kind, data in [("fut", FUT), ("spot", SPOT)]:
            st = first_live(fn, data)
            r_own = run_eval(fn, nm, "B_wf_seasonal", data, kind=kind, start=st)
            r_com = run_eval(fn, nm, "B_wf_seasonal", data, kind=kind, start="2006-01-01")
            for tag, r in [("own", r_own), ("common2006", r_com)]:
                t = r["table"].copy()
                t["window"] = tag
                t["family"] = "B_wf_seasonal"
                wf_rows.append(t)
            if kind == "fut":
                wf_series[nm] = r_own["port"]
    wf = pd.concat(wf_rows, ignore_index=True)
    wf.to_csv(os.path.join(OUT, "e04_walkforward_seasonal.csv"), index=False)
    print("\n=== B. walk-forward seasonal (PORT)")
    print(wf[wf.symbol == "PORT"][["name", "dataset", "window", "start", "sharpe", "is_sharpe", "oos_sharpe",
                                   "cagr", "max_dd"]].round(3).to_string(index=False))
    print(wf[(wf.dataset == "fut") & (wf.window == "own")][["name", "symbol", "start", "sharpe", "is_sharpe",
                                                             "oos_sharpe", "gross_sharpe", "turnover_py"]]
          .round(3).to_string(index=False))

    # ------------------------------------------------------------------ C
    rules = {
        # crude
        "crude_long_FebMay": ((2, 3, 4, 5), ()),
        "crude_long_MarMay": ((3, 4, 5), ()),
        "crude_long_FebApr": ((2, 3, 4), ()),
        "crude_short_OctDec": ((), (10, 11, 12)),
        "crude_short_SepNov": ((), (9, 10, 11)),
        "crude_short_NovDec": ((), (11, 12)),
        "crude_FebMay_long_OctDec_short": ((2, 3, 4, 5), (10, 11, 12)),
        # natural gas
        "ng_long_AugOct": ((8, 9, 10), ()),
        "ng_long_SepOct": ((9, 10), ()),
        "ng_long_SepNov": ((9, 10, 11), ()),
        "ng_long_AugNov": ((8, 9, 10, 11), ()),
        "ng_short_JanApr": ((), (1, 2, 3, 4)),
        "ng_short_FebApr": ((), (2, 3, 4)),
        "ng_short_JanFeb": ((), (1, 2)),
        "ng_AugOct_long_JanApr_short": ((8, 9, 10), (1, 2, 3, 4)),
        "ng_SepOct_long_FebApr_short": ((9, 10), (2, 3, 4)),
    }
    rule_rows = []
    for nm, (lm, sm_) in rules.items():
        syms = ["XNGUSD"] if nm.startswith("ng") else ["XTIUSD", "XBRUSD"]
        for kind, data in [("fut", FUT), ("spot", SPOT)]:
            r = run_eval(month_rule_fn(lm, sm_), nm, "C_fixed_month_rule", data, kind=kind, symbols=syms)
            rule_rows.append(r["table"].assign(family="C_fixed_month_rule"))
    # carry-based and carry-filtered NG variants (futures only: carry is a futures concept)
    carry_variants = {
        "carry_sign": carry_sign_fn,
        "carry_deseason_sign": carry_deseason_fn(5),
        "ng_AugOct_long_carry_filtered": rule_with_carry_filter((8, 9, 10), ()),
        "ng_JanApr_short_carry_filtered": rule_with_carry_filter((), (1, 2, 3, 4)),
        "ng_AugOct_JanApr_carry_filtered": rule_with_carry_filter((8, 9, 10), (1, 2, 3, 4)),
    }
    for nm, fn in carry_variants.items():
        syms = SYMBOLS if nm.startswith("carry") else ["XNGUSD"]
        r = run_eval(fn, nm, "C_carry", FUT, kind="fut", symbols=syms)
        rule_rows.append(r["table"].assign(family="C_carry"))
    rules_t = pd.concat(rule_rows, ignore_index=True)
    rules_t.to_csv(os.path.join(OUT, "e04_fixed_rules.csv"), index=False)
    print("\n=== C. fixed rules")
    print(rules_t[["name", "symbol", "dataset", "sharpe", "is_sharpe", "oos_sharpe", "gross_sharpe", "cagr",
                   "max_dd", "turnover_py", "time_in_mkt"]].round(3).to_string(index=False))

    # ------------------------------------------------------------------ D
    eff = pd.concat([effect_tests(FUTC, "fut"), effect_tests(SPOT_S, "spot")], ignore_index=True)
    m = (eff.dataset == "fut") & (eff.period == "full") & eff.effect.ne("dow_anova")
    eff.loc[m, "p_bh"] = multipletests(eff.loc[m, "p_diff"], method="fdr_bh")[1]
    eff.loc[m, "p_holm"] = multipletests(eff.loc[m, "p_diff"], method="holm")[1]
    eff.to_csv(os.path.join(OUT, "e04_daily_effects.csv"), index=False)
    print("\n=== D. daily effects (futures, full) sorted by |t|")
    print(eff[m].sort_values("t_diff", key=abs, ascending=False)
          [["symbol", "effect", "n_on", "mean_on_bp", "mean_off_bp", "diff_bp", "t_diff", "p_diff", "p_bh",
            "vol_ratio"]].head(20).round(3).to_string(index=False))
    stab = eff[(eff.dataset == "fut") & eff.effect.ne("dow_anova")].pivot_table(
        index=["symbol", "effect"], columns="period", values="t_diff")
    print("\nstability of t_diff across halves:\n", stab.round(2).to_string())
    print("\nEIA-day vol ratio (fut, full):\n",
          eff[m & (eff.effect == "eia")][["symbol", "vol_ratio", "mean_on_bp", "t_diff"]].round(3).to_string(index=False))

    # ------------------------------------------------------------------ E
    daily_rows = []
    # a-priori directions (equity-style TOM / pre-holiday / post-holiday drift; index-roll & expiry pressure on
    # the front of the curve => short).  The EIA day has no directional prior, so it is walk-forward only.
    fixed_prior = {"tom": 1.0, "pre_hol": 1.0, "post_hol": 1.0, "exp_week": -1.0, "ltd": -1.0,
                   "opt_exp": -1.0, "roll_win": -1.0}
    for e, sgn in fixed_prior.items():
        r = run_eval(flag_fixed_fn(e, sgn), f"{e}_fixed_{'long' if sgn > 0 else 'short'}", "E_daily_fixed", FUTC)
        daily_rows.append(r["table"].assign(family="E_daily_fixed"))
    for e in EFFECTS:
        r = run_eval(flag_wf_fn(e), f"{e}_wf_sign", "E_daily_wf", FUTC)
        daily_rows.append(r["table"].assign(family="E_daily_wf"))
    for d in range(5):
        r = run_eval(flag_fixed_fn(f"dow{d}", 1.0), f"dow{d}_long_only", "E_dow_fixed", FUTC)
        daily_rows.append(r["table"].assign(family="E_dow_fixed"))
    r = run_eval(dow_wf_fn(), "dow_wf_sign_all_days", "E_dow_wf", FUTC)
    daily_rows.append(r["table"].assign(family="E_dow_wf"))
    daily_t = pd.concat(daily_rows, ignore_index=True)
    daily_t.to_csv(os.path.join(OUT, "e04_daily_strategies.csv"), index=False)
    print("\n=== E. daily-effect strategies (sorted by PORT/instrument net Sharpe)")
    print(daily_t.sort_values("sharpe", ascending=False)[["name", "symbol", "sharpe", "is_sharpe", "oos_sharpe",
                                                          "gross_sharpe", "turnover_py", "time_in_mkt"]]
          .head(25).round(3).to_string(index=False))

    # ------------------------------------------------------------------ F. multiple testing
    fn_lookup = {}
    for N, mode in variants:
        fn_lookup[f"wf_seasonal_N{N or 'exp'}_{mode}"] = (wf_seasonal_fn(N, mode), FUT)
    for nm, (lm, sm_) in rules.items():
        fn_lookup[nm] = (month_rule_fn(lm, sm_), FUT)
    for nm, fn in carry_variants.items():
        fn_lookup[nm] = (fn, FUT)
    for e, sgn in fixed_prior.items():
        fn_lookup[f"{e}_fixed_{'long' if sgn > 0 else 'short'}"] = (flag_fixed_fn(e, sgn), FUTC)
    for e in EFFECTS:
        fn_lookup[f"{e}_wf_sign"] = (flag_wf_fn(e), FUTC)
    for d in range(5):
        fn_lookup[f"dow{d}_long_only"] = (flag_fixed_fn(f"dow{d}", 1.0), FUTC)
    fn_lookup["dow_wf_sign_all_days"] = (dow_wf_fn(), FUTC)

    allv = pd.concat(ALL_EVALS, ignore_index=True)
    base = allv[(allv.dataset == "fut") & (allv.lag == 1) & (allv.cost_mult == 1.0)]
    base = base.drop_duplicates(subset=["name", "symbol"], keep="first")  # WF family: own-window rows first
    trials = base[base.symbol != "PORT"].copy()
    fam_map = {"B_wf_seasonal": "month-of-year (B+C)", "C_fixed_month_rule": "month-of-year (B+C)",
               "C_carry": "carry", "E_daily_fixed": "daily calendar (E)", "E_daily_wf": "daily calendar (E)",
               "E_dow_fixed": "daily calendar (E)", "E_dow_wf": "daily calendar (E)"}
    trials = trials[trials.family.isin(list(fam_map))].copy()  # standalone variants only (no overlays)
    trials["family_group"] = trials["family"].map(fam_map)
    n_trials = len(trials)
    sr_all = trials["sharpe"].dropna().tolist()
    print(f"\n=== F. multiple testing: {n_trials} per-instrument futures variants "
          f"({base.name.nunique()} strategy definitions); SR sd={np.std(sr_all):.3f}")

    def e_max(sd, n):
        return sd * ((1 - 0.5772) * stats.norm.ppf(1 - 1 / n) + 0.5772 * stats.norm.ppf(1 - 1 / (n * np.e)))

    cands = trials.sort_values("sharpe", ascending=False).head(10)
    cands = pd.concat([cands, trials[(trials.name == "eia_wf_sign") & (trials.symbol == "XNGUSD")],
                       trials[(trials.name == "crude_long_FebMay")]]).drop_duplicates(["name", "symbol"])
    mt_rows = []
    for _, row in cands.iterrows():
        fn, data = fn_lookup[row["name"]]
        st = first_live(fn, {row["symbol"]: data[row["symbol"]]}) if row["name"].startswith("wf_") else None
        rr = evaluate(fn, row["name"], data=data, symbols=[row["symbol"]], keep_series=True, start=st)
        x = rr["nets"][row["symbol"]]
        x = x[x.index >= st] if st else x
        sr_d = bt.sharpe(x)
        fam_sr = trials.loc[trials.family_group == row["family_group"], "sharpe"].dropna().tolist()
        lo, hi = bt.bootstrap_sharpe_ci(x, n=1000)
        mt_rows.append({
            "name": row["name"], "symbol": row["symbol"], "family_group": row["family_group"],
            "net_sharpe": sr_d, "t_stat": row["t_stat"], "years": row["years"],
            "boot95_lo": lo, "boot95_hi": hi,
            "n_trials_global": n_trials, "exp_max_sr_null_global": e_max(np.std(sr_all), n_trials),
            "dsr_global": bt.deflated_sharpe(sr_d, sr_all, len(x), float(x.skew()), float(x.kurt() + 3)),
            "n_trials_family": len(fam_sr), "exp_max_sr_null_family": e_max(np.std(fam_sr), len(fam_sr)),
            "dsr_family": bt.deflated_sharpe(sr_d, fam_sr, len(x), float(x.skew()), float(x.kurt() + 3)),
        })
    mt = pd.DataFrame(mt_rows)
    mt.to_csv(os.path.join(OUT, "e04_multiple_testing.csv"), index=False)
    print(mt.round(3).to_string(index=False))

    # selection check for the crude month rules: every contiguous 3- and 4-month long-only window
    win_rows = []
    for L in [3, 4]:
        for m0 in range(1, 13):
            months = tuple(((m0 - 1 + k) % 12) + 1 for k in range(L))
            r = evaluate(month_rule_fn(months, ()), f"long_{MONTHS[m0 - 1]}+{L}m", data=FUT,
                         symbols=["XTIUSD", "XBRUSD"])
            t = r["table"]
            for _, row in t.iterrows():
                win_rows.append({"window_len": L, "first_month": MONTHS[m0 - 1], "months": "-".join(
                    MONTHS[m - 1] for m in months), "symbol": row["symbol"], "sharpe": row["sharpe"],
                    "is_sharpe": row["is_sharpe"], "oos_sharpe": row["oos_sharpe"]})
    win = pd.DataFrame(win_rows)
    win["rank_in_len"] = win.groupby(["window_len", "symbol"])["sharpe"].rank(ascending=False)
    win.to_csv(os.path.join(OUT, "e04_crude_window_selection.csv"), index=False)
    print("\ncrude long-only month windows (PORT of WTI+Brent), sorted:")
    print(win[win.symbol == "PORT"].sort_values("sharpe", ascending=False).round(3).to_string(index=False))

    # cross-check notable daily effects on other energy futures (not used for selection)
    xc_rows = []
    from src.data import futures_daily
    for code, sym_cal in [("CRUDE_ICE", "XTIUSD"), ("HEATOIL", "XTIUSD"), ("GASOILINE", "XTIUSD"),
                          ("GASOIL", "XBRUSD"), ("GAS-LAST", "XNGUSD")]:
        x = ct.merge_holiday_rows(futures_daily(code)[["ret"]])
        x = x[x.index >= "1990-01-01"]
        fl = ct.calendar_flags(x.index, sym_cal)
        for e in ["pre_hol", "eia", "post_hol", "exp_week", "tom"]:
            on, off = x["ret"][fl[e] == 1], x["ret"][fl[e] == 0]
            tt = stats.ttest_ind(on, off, equal_var=False)
            xc_rows.append({"code": code, "calendar": sym_cal, "effect": e, "start": str(x.index[0].date()),
                            "n_on": len(on), "mean_on_bp": on.mean() * 1e4, "mean_off_bp": off.mean() * 1e4,
                            "t_diff": tt.statistic, "p_diff": tt.pvalue})
    xc = pd.DataFrame(xc_rows)
    xc.to_csv(os.path.join(OUT, "e04_daily_effects_crosscheck.csv"), index=False)
    print("\ncross-check on other energy futures:\n", xc.round(3).to_string(index=False))
    # pre-holiday breakdown by holiday (WTI, Brent futures)
    ph_rows = []
    hol = ct.nymex_holidays()
    names = ct.NYMEXCalendar().holidays("1985", "2027", return_name=True)
    for s_ in ["XTIUSD", "XBRUSD", "XNGUSD"]:
        f_ = FUTC[s_]
        fl = ct.calendar_flags(f_.index, s_)
        for d in f_.index[fl["pre_hol"] == 1]:
            nxt = hol[hol > d][0]
            ph_rows.append({"symbol": s_, "date": d, "holiday": names.get(nxt, "special closure"),
                            "ret_bp": f_.loc[d, "ret"] * 1e4})
    ph = pd.DataFrame(ph_rows)
    phs = ph.groupby(["symbol", "holiday"])["ret_bp"].agg(["mean", "median", "count"]).reset_index()
    phs.to_csv(os.path.join(OUT, "e04_pre_holiday_by_holiday.csv"), index=False)

    # ------------------------------------------------------------------ G. overlay on trend
    tilts = {
        "seasonal_wf_exp_tstat": wf_seasonal_fn(None, "tstat"),
        "seasonal_wf_N10_sign": wf_seasonal_fn(10, "sign"),
        "crude_FebMay_OctDec__ng_none": None,  # built below per symbol
    }
    crude_rule = month_rule_fn((2, 3, 4, 5), (10, 11, 12))

    def crude_rule_only(df):
        return crude_rule(df) if df["sym"].iloc[0] != "XNGUSD" else pd.Series(0.0, index=df.index)

    tilts["crude_FebMay_OctDec__ng_none"] = crude_rule_only
    pre_hol_long = flag_fixed_fn("pre_hol", 1.0)

    def pre_hol_crude_only(df):
        return pre_hol_long(df) if df["sym"].iloc[0] != "XNGUSD" else pd.Series(0.0, index=df.index)

    eia_wf = flag_wf_fn("eia")

    def eia_ng_only(df):
        return eia_wf(df) if df["sym"].iloc[0] == "XNGUSD" else pd.Series(0.0, index=df.index)

    tilts["pre_holiday_long__crude_only"] = pre_hol_crude_only
    tilts["eia_day_wf__ng_only"] = eia_ng_only
    ov_rows = []
    ov_series = {}
    trend_res = run_eval(TREND, "trend_only", "G_overlay", FUTC)
    ov_rows.append(trend_res["table"].assign(tilt="none", w=0.0))
    ov_series["trend_only"] = trend_res["port"]
    for tn, tfn in tilts.items():
        # standalone tilt (for correlation with trend)
        sa = evaluate(tfn, f"{tn}_standalone", data=FUTC, keep_series=True)
        for w in [0.5, 1.0]:
            fn = (lambda tfn, w: lambda d: TREND(d) + w * tfn(d))(tfn, w)
            nm = f"trend+{w}x{tn}"
            r = run_eval(fn, nm, "G_overlay", FUTC)
            t = r["table"].assign(tilt=tn, w=w)
            j = pd.concat([trend_res["port"], sa["port"]], axis=1).dropna()
            t["corr_tilt_vs_trend_port"] = j.corr().iloc[0, 1]
            ov_rows.append(t)
            ov_series[nm] = r["port"]
            # robustness
            for lag, cm in [(2, 1.0), (1, 2.0)]:
                rr = run_eval(fn, nm, "G_overlay_robust", FUTC, lag=lag, cost_mult=cm)
                ov_rows.append(rr["table"].assign(tilt=tn, w=w))
    for lag, cm in [(2, 1.0), (1, 2.0)]:
        rr = run_eval(TREND, "trend_only", "G_overlay_robust", FUTC, lag=lag, cost_mult=cm)
        ov_rows.append(rr["table"].assign(tilt="none", w=0.0))
    ov = pd.concat(ov_rows, ignore_index=True)
    ov.to_csv(os.path.join(OUT, "e04_trend_overlay.csv"), index=False)
    print("\n=== G. trend overlay (PORT)")
    print(ov[ov.symbol == "PORT"][["name", "lag", "cost_mult", "sharpe", "is_sharpe", "oos_sharpe", "cagr",
                                   "max_dd", "corr_tilt_vs_trend_port"]].round(3).to_string(index=False))
    # yearly paired difference test (trend+tilt minus trend), PORT
    diff_rows = []
    for nm, s in ov_series.items():
        if nm == "trend_only":
            continue
        j = pd.concat([s, ov_series["trend_only"]], axis=1, keys=["ov", "tr"]).dropna()
        d = j["ov"] - j["tr"]
        yd = (1 + j["ov"]).groupby(j.index.year).prod() - (1 + j["tr"]).groupby(j.index.year).prod()
        diff_rows.append({"name": nm, "sharpe_diff": bt.sharpe(j["ov"]) - bt.sharpe(j["tr"]),
                          "daily_diff_t": d.mean() / d.std() * np.sqrt(len(d)),
                          "years_overlay_better": int((yd > 0).sum()), "n_years": len(yd),
                          "corr_overlay_trend": j.corr().iloc[0, 1]})
    ovd = pd.DataFrame(diff_rows)
    ovd.to_csv(os.path.join(OUT, "e04_trend_overlay_diff.csv"), index=False)
    print(ovd.round(3).to_string(index=False))

    # ------------------------------------------------------------------ robustness of the best standalone
    rob_rows = []
    for nm in ["wf_seasonal_Nexp_sign", "wf_seasonal_Nexp_tstat", "wf_seasonal_N10_sign",
               "crude_FebMay_long_OctDec_short", "crude_long_FebMay", "ng_AugOct_long_JanApr_short",
               "pre_hol_fixed_long", "pre_hol_wf_sign", "eia_wf_sign"]:
        fn, data = fn_lookup[nm]
        syms = ["XNGUSD"] if nm.startswith("ng") else (["XTIUSD", "XBRUSD"] if nm.startswith("crude") else SYMBOLS)
        syms = ["XNGUSD"] if nm == "eia_wf_sign" else syms
        st = first_live(fn, {s: data[s] for s in syms}) if nm.startswith("wf_") else None
        for lag, cm in [(1, 1.0), (2, 1.0), (1, 2.0)]:
            r = run_eval(fn, nm, "robust", data, symbols=syms, lag=lag, cost_mult=cm, start=st)
            rob_rows.append(r["table"])
    rob = pd.concat(rob_rows, ignore_index=True)
    rob.to_csv(os.path.join(OUT, "e04_robustness.csv"), index=False)
    print("\n=== robustness (lag 2, 2x cost)")
    print(rob[["name", "symbol", "lag", "cost_mult", "sharpe", "is_sharpe", "oos_sharpe"]].round(3)
          .to_string(index=False))

    # ------------------------------------------------------------------ year-concentration check (crude rules)
    yc_rows, ycy = [], {}
    for nm, (lm, sm_) in [("crude_long_FebMay", ((2, 3, 4, 5), ())), ("crude_short_OctDec", ((), (10, 11, 12))),
                          ("crude_FebMay_long_OctDec_short", ((2, 3, 4, 5), (10, 11, 12)))]:
        r = evaluate(month_rule_fn(lm, sm_), nm, data=FUT, symbols=["XTIUSD", "XBRUSD"], keep_series=True)
        p_ = r["port"]
        yr = (1 + p_).groupby(p_.index.year).prod() - 1
        ycy[nm] = yr
        top = yr.sort_values(ascending=False).index
        yc_rows.append({"name": nm, "sharpe": bt.sharpe(p_), "pos_years": int((yr > 0).sum()), "n_years": len(yr),
                        "median_year_pct": yr.median() * 100, "best3_years": ",".join(map(str, top[:3])),
                        "sharpe_ex_best3": bt.sharpe(p_[~p_.index.year.isin(top[:3])]),
                        "sharpe_ex_best5": bt.sharpe(p_[~p_.index.year.isin(top[:5])])})
    yc = pd.DataFrame(yc_rows)
    yc.to_csv(os.path.join(OUT, "e04_crude_rule_year_concentration.csv"), index=False)
    pd.DataFrame(ycy).to_csv(os.path.join(OUT, "e04_crude_rule_yearly_returns.csv"))
    print("\n=== year concentration (crude rules, WTI+Brent PORT)\n", yc.round(3).to_string(index=False))

    # ------------------------------------------------------------------ all variants
    allv = pd.concat(ALL_EVALS, ignore_index=True)
    tidy(allv).to_csv(os.path.join(OUT, "e04_all_variants.csv"), index=False)

    # ------------------------------------------------------------------ charts
    charts(moy, ngd, eff, wf_series, ov_series)


# ================================================================================================
# charts
# ================================================================================================
def charts(moy, ngd, eff, wf_series, ov_series):
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D
    from matplotlib.patches import Patch

    # 1. month-of-year, futures, per instrument (bars = full sample; markers = halves)
    fig, axes = plt.subplots(1, 3, figsize=(13.5, 4.3), sharey=True)
    x = np.arange(12)
    for ax, s in zip(axes, SYMBOLS):
        sub = moy[(moy.dataset == "fut") & (moy.symbol == s)]
        full = sub[sub.period == "full"].set_index("month")["mean_pct"].reindex(range(1, 13))
        tfull = sub[sub.period == "full"].set_index("month")["t_stat"].reindex(range(1, 13))
        h1 = sub[sub.period == "1990-2007"].set_index("month")["mean_pct"].reindex(range(1, 13))
        h2 = sub[sub.period == "2008-2024"].set_index("month")["mean_pct"].reindex(range(1, 13))
        ax.bar(x, full.values, width=0.55, color=ps.SYM_COLOR[s], zorder=2)
        ax.scatter(x - 0.0, h1.values, marker="o", s=26, facecolor=ps.SURFACE, edgecolor=ps.INK2, lw=1.1, zorder=3)
        ax.scatter(x + 0.0, h2.values, marker="D", s=20, color=ps.INK, zorder=3)
        for i, (v, t) in enumerate(zip(full.values, tfull.values)):
            if abs(t) >= 2:
                ax.text(i, v + (0.6 if v >= 0 else -0.6), f"t={t:.1f}", ha="center",
                        va="bottom" if v >= 0 else "top", fontsize=7.5, color=ps.INK2)
        ax.axhline(0, color=ps.AXIS, lw=0.8, zorder=1)
        ax.set_xticks(x, [m[0] for m in MONTHS])
        ax.set_title(ps.SYM_LABEL[s], fontsize=10.5)
        ax.grid(axis="x", visible=False)
    axes[0].set_ylabel("mean monthly return of rolled futures, %")
    handles = [Patch(color=ps.DE_EMPH, label="1990-2024 mean (bar, instrument colour)"),
               Line2D([], [], marker="o", ls="", markerfacecolor=ps.SURFACE, markeredgecolor=ps.INK2,
                      label="1990-2007 mean"),
               Line2D([], [], marker="D", ls="", color=ps.INK, markersize=5, label="2008-2024 mean")]
    fig.legend(handles=handles, loc="lower center", ncol=3, bbox_to_anchor=(0.5, -0.06))
    ps.title(fig, "Month-of-year returns: weak, and they do not repeat across halves", y=1.06)
    ps.subtitle(fig, "Rolled futures incl. roll yield. Labels mark |t| >= 2 on the full sample; none survives "
                     "a 36-cell multiple-testing correction.", y=1.0)
    ps.save(fig, os.path.join(OUT, "e04_month_of_year.png"))

    # 2. NG spot vs futures by month + carry
    fig, axes = plt.subplots(1, 2, figsize=(12.5, 4.2))
    ax = axes[0]
    w = 0.36
    ax.bar(x - w / 2 - 0.02, ngd["spot_mean_pct"].values, width=w, color=ps.DE_EMPH, label="Henry Hub spot (EIA)",
           zorder=2)
    ax.bar(x + w / 2 + 0.02, ngd["fut_mean_pct"].values, width=w, color=ps.SYM_COLOR["XNGUSD"],
           label="Rolled futures (what a CFD earns)", zorder=2)
    ax.axhline(0, color=ps.AXIS, lw=0.8)
    ax.set_xticks(x, [m[0] for m in MONTHS])
    ax.set_ylabel("mean monthly return, %  (1997-2024)")
    ax.set_title("Spot shows a winter seasonal; futures do not", fontsize=10.5)
    ax.legend(loc="upper left")
    ax.grid(axis="x", visible=False)
    ax = axes[1]
    ax.bar(x, ngd["carry_ann_pct"].values, width=0.55, color=ps.SYM_COLOR["XNGUSD"], zorder=2)
    ax.axhline(0, color=ps.AXIS, lw=0.8)
    ax.set_xticks(x, [m[0] for m in MONTHS])
    ax.set_ylabel("mean annualised carry of held contract, %")
    ax.set_title("Why: the curve prices the season in (negative = contango)", fontsize=10.5)
    ax.grid(axis="x", visible=False)
    ps.title(fig, "US natural gas: the seasonal is in the spot price, not in tradeable futures returns", y=1.04)
    ps.save(fig, os.path.join(OUT, "e04_ng_spot_vs_futures.png"))

    # 3. daily effects t-stats (futures, full sample)
    sub = eff[(eff.dataset == "fut") & (eff.period == "full") & eff.effect.ne("dow_anova")].copy()
    order = EFFECTS + [f"dow{d}" for d in range(5)]
    fig, ax = plt.subplots(figsize=(9.5, 7.2))
    ypos = np.arange(len(order))
    h = 0.26
    for k, s in enumerate(SYMBOLS):
        v = sub[sub.symbol == s].set_index("effect")["t_diff"].reindex(order)
        ax.barh(ypos + (k - 1) * (h + 0.02), v.values, height=h, color=ps.SYM_COLOR[s], label=ps.SYM_LABEL[s],
                zorder=2)
    ntest = len(sub)
    bonf = stats.norm.ppf(1 - 0.025 / ntest)
    for xv, lab in [(1.96, "|t| = 1.96"), (bonf, f"Bonferroni ({ntest} tests), |t| = {bonf:.2f}")]:
        ax.axvline(xv, color=ps.INK2 if xv < 2.5 else ps.CRITICAL, lw=0.8)
        ax.axvline(-xv, color=ps.INK2 if xv < 2.5 else ps.CRITICAL, lw=0.8)
        ax.text(xv + 0.05, len(order) - 0.4, lab, fontsize=7.5, color=ps.INK2, va="top")
    ax.axvline(0, color=ps.AXIS, lw=0.8)
    ax.set_yticks(ypos, [EFFECT_LABEL[e] for e in order])
    ax.invert_yaxis()
    ax.set_xlabel("t-stat of (mean return on flagged days - mean on other days), rolled futures 1990-2024")
    ax.legend(loc="lower right")
    ax.grid(axis="y", visible=False)
    ps.title(fig, "Daily calendar effects: nothing clears a multiple-testing hurdle", y=1.02)
    ps.save(fig, os.path.join(OUT, "e04_daily_effects.png"))

    # 4. walk-forward seasonal vs trend vs overlay (PORT, cumulative net, log)
    fig, ax = plt.subplots(figsize=(11, 4.6))
    series = [("trend_only", "Trend only (multi-speed EWMAC)", ps.SERIES[0]),
              ("trend+0.5xseasonal_wf_exp_tstat", "Trend + 0.5 x walk-forward seasonal tilt", ps.SERIES[1]),
              ]
    for key, lab, col in series:
        s = ov_series[key]
        s = s[s.index >= "1996-01-01"]
        eq = (1 + s).cumprod()
        ax.plot(eq.index, eq.values, color=col, lw=1.3, label=lab)
        ax.text(eq.index[-1], eq.values[-1], f"  {eq.values[-1]:.1f}x", color=ps.INK2, fontsize=8, va="center")
    s = wf_series["wf_seasonal_Nexp_tstat"]
    s = s[s.index >= "1996-01-01"]
    eq = (1 + s).cumprod()
    ax.plot(eq.index, eq.values, color=ps.SERIES[2], lw=1.3, label="Walk-forward seasonal alone (expanding, t-stat)")
    ax.text(eq.index[-1], eq.values[-1], f"  {eq.values[-1]:.1f}x", color=ps.INK2, fontsize=8, va="center")
    ax.set_yscale("log")
    ax.set_ylabel("growth of 1 (net of costs, log scale)")
    ax.legend(loc="upper left")
    ps.title(fig, "Equal-weight 3-instrument portfolio, net of CFD costs, 1996-2024", y=1.03)
    ps.save(fig, os.path.join(OUT, "e04_walkforward_vs_trend.png"))


if __name__ == "__main__":
    main()
