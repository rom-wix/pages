"""E08 - Machine-learning baseline: can an off-the-shelf model predict next-day / next-week direction better
than simple trend?  Walk-forward, expanding window, yearly retraining (first test year 2005), 5-day purge.

Features (all known at close t; calendar facts about t+1 are known in advance):
  own:    vol-normalised log returns over 1,2,5,10,20,60,120,250 days; vol ratios 5/60, 20/120, 20/250 and
          log vol level; distance from 10/20/50/100/200-day moving averages (in vol units); multi-speed EWMAC
          trend forecast; carry level, 5/20-day carry change, carry z-score, de-seasonalised carry
  cal:    day-of-week, month, EIA-report / pre-holiday / turn-of-month flags of the target day t+1
  cross:  the other two instruments' vol-normalised returns (1,5,20,60d); WTI-Brent spread change (5,20d);
          heating-oil and gasoline (crack-spread proxies): vol-normalised returns (1,5,20d) and 20-day return
          relative to WTI
Targets:  y1 = 1[ret(t+1) > 0];  y5 = 1[sum log-ret(t+1..t+5) > 0]
Models:   L2 logistic regression (C=0.05, standardised features) and a small regularised LightGBM;
          fitted per instrument and pooled across the three instruments (instrument dummies)
Trading:  position signal = (p - 0.5) / expanding mean |p - 0.5| (clipped to +/-2), vol-targeted by evaluate();
          compared with trend (multi-speed EWMAC) and a 50/50 blend on the same 2005-2024 window.
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
from sklearn.linear_model import LogisticRegression  # noqa: E402
from sklearn.metrics import log_loss, roc_auc_score  # noqa: E402
import lightgbm as lgb  # noqa: E402

from src import backtest as bt  # noqa: E402
from src import calendar_tools as ct  # noqa: E402
from src import plotstyle as ps  # noqa: E402
from src import signals as sg  # noqa: E402
from src.data import SYMBOLS, futures_daily  # noqa: E402
from src.evaluate import evaluate, get_dataset  # noqa: E402

OUT = os.path.join(ROOT, "results")
pd.set_option("display.width", 250)
pd.set_option("display.max_columns", 40)

FIRST_TEST_YEAR = 2005
PURGE = 5
LR_C = 0.05
LGB_PARAMS = dict(n_estimators=300, learning_rate=0.02, num_leaves=8, max_depth=3, min_child_samples=200,
                  subsample=0.7, subsample_freq=1, colsample_bytree=0.7, reg_lambda=5.0, verbose=-1,
                  random_state=0, n_jobs=4)
FUT = get_dataset("fut")
TREND = lambda d: sg.multi_ewmac(d["tri"], d["ret"])  # noqa: E731


# ================================================================================================
# features
# ================================================================================================
def own_features(df: pd.DataFrame, sym: str) -> pd.DataFrame:
    r = df["ret"]
    lp = np.log(df["tri"])
    vol = r.ewm(span=36, min_periods=20).std()
    f = pd.DataFrame(index=df.index)
    for k in [1, 2, 5, 10, 20, 60, 120, 250]:
        f[f"ret_{k}"] = (lp - lp.shift(k)) / (vol * np.sqrt(k))
    sd = {n: r.rolling(n, min_periods=max(3, n // 2)).std() for n in [5, 20, 60, 120, 250]}
    f["vr_5_60"] = np.log(sd[5] / sd[60])
    f["vr_20_120"] = np.log(sd[20] / sd[120])
    f["vr_20_250"] = np.log(sd[20] / sd[250])
    f["logvol_20"] = np.log(sd[20] * np.sqrt(252))
    for n in [10, 20, 50, 100, 200]:
        f[f"ma_dist_{n}"] = (lp - lp.rolling(n, min_periods=n).mean()) / (vol * np.sqrt(n))
    f["ewmac"] = TREND(df)
    c = df["carry"].clip(-3, 3)
    f["carry"] = c
    f["carry_d5"] = c - c.shift(5)
    f["carry_d20"] = c - c.shift(20)
    f["carry_z"] = (c - c.rolling(250, min_periods=120).mean()) / c.rolling(250, min_periods=120).std()
    cm = c.groupby([c.index.year, c.index.month]).mean().unstack()
    base = cm.shift(1).rolling(5, min_periods=3).mean()          # same month, previous years only
    keys = pd.MultiIndex.from_arrays([c.index.year, c.index.month])
    f["carry_deseason"] = c.values - base.stack().reindex(keys).values
    # calendar facts of the target day t+1 (published in advance)
    nf = ct.next_row_flags(df.index, sym)
    f["dow_next"] = nf["dow"].values
    f["month_next"] = np.r_[df.index.month[1:], df.index.month[-1:]]
    f["eia_next"] = nf["eia"].values
    f["pre_hol_next"] = nf["pre_hol"].values
    f["tom_next"] = nf["tom"].values
    return f


def cross_features(target_idx: pd.DatetimeIndex, sym: str) -> pd.DataFrame:
    """Other instruments' state at the same close (all settle ~19:30 London), forward-filled onto the
    target's calendar (never backward)."""
    f = pd.DataFrame(index=target_idx)

    def vn(code_df, ks):
        r = code_df["ret"]
        lp = np.log(code_df["tri"])
        vol = r.ewm(span=36, min_periods=20).std()
        return {k: (lp - lp.shift(k)) / (vol * np.sqrt(k)) for k in ks}

    others = [s for s in SYMBOLS if s != sym]
    for o in others:
        for k, v in vn(FUT[o], [1, 5, 20, 60]).items():
            f[f"x_{o}_ret_{k}"] = v.reindex(target_idx, method="ffill")
    w, b = np.log(FUT["XTIUSD"]["tri"]), np.log(FUT["XBRUSD"]["tri"])
    spread = (w - b.reindex(w.index, method="ffill")).dropna()
    for k in [5, 20]:
        f[f"x_wti_brent_spread_d{k}"] = (spread - spread.shift(k)).reindex(target_idx, method="ffill")
    wti_lp = np.log(FUT["XTIUSD"]["tri"])
    for code, nm in [("HEATOIL", "ho"), ("GASOILINE", "rb")]:
        d = futures_daily(code)[["ret", "tri"]]
        for k, v in vn(d, [1, 5, 20]).items():
            f[f"x_{nm}_ret_{k}"] = v.reindex(target_idx, method="ffill")
        lp = np.log(d["tri"])
        rel = (lp - lp.shift(20)).reindex(wti_lp.index, method="ffill") - (wti_lp - wti_lp.shift(20))
        f[f"x_{nm}_crack_rel_20"] = rel.reindex(target_idx, method="ffill")
    return f


def build_panel():
    frames = []
    for s in SYMBOLS:
        df = FUT[s]
        X = pd.concat([own_features(df, s), cross_features(df.index, s)], axis=1)
        lr = np.log1p(df["ret"])
        y1 = (df["ret"].shift(-1) > 0).astype(float)
        fwd5 = sum(lr.shift(-j) for j in range(1, 6))
        y5 = (fwd5 > 0).astype(float)
        y1[df["ret"].shift(-1).isna()] = np.nan
        y5[fwd5.isna()] = np.nan
        X["y1"], X["y5"] = y1, y5
        X["fwd1"], X["fwd5"] = df["ret"].shift(-1), fwd5
        X["sym"] = s
        X["pos"] = np.arange(len(X))
        # warm-up: need the 250-day features
        X = X.iloc[260:]
        frames.append(X)
    P = pd.concat(frames)
    P.index.name = "date"
    return P


# ================================================================================================
# walk-forward
# ================================================================================================
CAT_COLS = ["dow_next", "month_next"]


def feature_cols(P):
    drop = {"y1", "y5", "fwd1", "fwd5", "sym", "pos"}
    return [c for c in P.columns if c not in drop]


def design(X: pd.DataFrame, cols, pooled: bool, for_lr: bool):
    Z = X[cols].copy()
    if for_lr:
        for c in CAT_COLS:
            d = pd.get_dummies(Z[c].astype("Int64"), prefix=c, drop_first=True).astype(float)
            Z = pd.concat([Z.drop(columns=c), d], axis=1)
    if pooled:
        Z = pd.concat([Z, pd.get_dummies(X["sym"], prefix="sym").astype(float)], axis=1)
    return Z


def fit_predict(model, Xtr, ytr, Xte):
    if model == "lr":
        mu, sd = Xtr.mean(), Xtr.std().replace(0, 1.0)
        A = ((Xtr - mu) / sd).fillna(0.0).clip(-6, 6)
        B = ((Xte - mu) / sd).fillna(0.0).clip(-6, 6)
        m = LogisticRegression(C=LR_C, max_iter=2000)
        m.fit(A.values, ytr.values)
        p_tr = m.predict_proba(A.values)[:, 1]
        p_te = m.predict_proba(B.values)[:, 1]
        imp = pd.Series(m.coef_[0], index=Xtr.columns)
    else:
        m = lgb.LGBMClassifier(**LGB_PARAMS)
        m.fit(Xtr, ytr)
        p_tr = m.predict_proba(Xtr)[:, 1]
        p_te = m.predict_proba(Xte)[:, 1]
        imp = pd.Series(m.booster_.feature_importance("gain"), index=Xtr.columns)
    return p_tr, p_te, imp


def walk_forward(P, model, target, pooled):
    cols = feature_cols(P)
    preds, imps = [], []
    years = range(FIRST_TEST_YEAR, int(P.index.year.max()) + 1)
    for Y in years:
        test_mask = P.index.year == Y
        if not test_mask.any():
            continue
        # purge: drop the last PURGE rows of each instrument before its first test date
        tr_parts = []
        for s in SYMBOLS:
            ps_ = P[P.sym == s]
            first_test_pos = ps_.loc[ps_.index.year == Y, "pos"]
            if first_test_pos.empty:
                continue
            cut = first_test_pos.iloc[0] - PURGE
            tr_parts.append(ps_[ps_["pos"] < cut])
        TR = pd.concat(tr_parts)
        TE = P[test_mask]
        TR = TR.dropna(subset=[target])
        groups = [None] if pooled else SYMBOLS
        for g in groups:
            tr = TR if g is None else TR[TR.sym == g]
            te = TE if g is None else TE[TE.sym == g]
            if len(te) == 0 or len(tr) < 500:
                continue
            Xtr = design(tr, cols, pooled, model == "lr")
            Xte = design(te, cols, pooled, model == "lr").reindex(columns=Xtr.columns, fill_value=0.0)
            p_tr, p_te, imp = fit_predict(model, Xtr, tr[target], Xte)
            out = pd.DataFrame({"sym": te["sym"].values, "p": p_te, "y": te[target].values,
                                "fwd1": te["fwd1"].values, "fwd5": te["fwd5"].values,
                                "ewmac": te["ewmac"].values, "year": Y,
                                "train_abs_edge": np.mean(np.abs(p_tr - 0.5)), "n_train": len(tr),
                                "train_base_rate": tr[target].mean()}, index=te.index)
            preds.append(out)
            imps.append(imp.rename(f"{Y}_{g}"))
    pr = pd.concat(preds).sort_index()
    im = pd.concat(imps, axis=1)
    return pr, im


# ================================================================================================
# evaluation
# ================================================================================================
def auc_se(auc, n_pos, n_neg):
    """Hanley-McNeil standard error of the AUC."""
    q1, q2 = auc / (2 - auc), 2 * auc ** 2 / (1 + auc)
    return np.sqrt((auc * (1 - auc) + (n_pos - 1) * (q1 - auc ** 2) + (n_neg - 1) * (q2 - auc ** 2))
                   / (n_pos * n_neg))


def class_metrics(pr, name, target):
    rows = []
    for s, g in list(pr.groupby("sym")) + [("ALL", pr)]:
        g = g.dropna(subset=["y"])
        if target == "y5":
            # non-overlapping evaluation: every 5th prediction per instrument
            g = pd.concat([x.iloc[::5] for _, x in g.groupby("sym")]) if s == "ALL" else g.iloc[::5]
        y, p = g["y"].values, g["p"].values
        n = len(y)
        acc = ((p > 0.5) == (y == 1)).mean()
        base = y.mean()
        auc = roc_auc_score(y, p)
        se = auc_se(auc, int(y.sum()), int(n - y.sum()))
        ll = log_loss(y, np.clip(p, 1e-6, 1 - 1e-6))
        ll0 = log_loss(y, np.clip(g["train_base_rate"].values, 1e-6, 1 - 1e-6))
        tr_auc = roc_auc_score(y, g["ewmac"].values)
        tr_acc = ((g["ewmac"].values > 0) == (y == 1)).mean()
        rows.append({"model": name, "target": target, "symbol": s, "n_eval": n,
                     "base_rate_up": base, "accuracy": acc, "acc_always_up": max(base, 1 - base),
                     "acc_minus_best_naive": acc - max(base, 1 - base), "acc_se": np.sqrt(0.25 / n),
                     "auc": auc, "auc_se": se, "auc_z": (auc - 0.5) / se,
                     "logloss": ll, "logloss_baserate": ll0, "logloss_gain": ll0 - ll,
                     "trend_sign_accuracy": tr_acc, "trend_auc": tr_auc})
    return rows


def ml_signal(pr):
    """signal_t = (p_t - 0.5) / expanding mean |p - 0.5| of *earlier* OOS predictions, clipped to +/-2.
    The first test year is scaled by the training-set mean |p - 0.5|."""
    out = {}
    for s, g in pr.groupby("sym"):
        e = g["p"] - 0.5
        sc = e.abs().expanding().mean().shift(1)
        first = g["train_abs_edge"].iloc[0]
        sc = sc.fillna(first)
        sc[g["year"] == g["year"].min()] = first
        out[s] = (e / sc.replace(0, np.nan)).clip(-2, 2).fillna(0.0)
    return out


def make_fn(sig_by_sym, mix_trend=0.0):
    def fn(df):
        s = df["sym"].iloc[0]
        ml = sig_by_sym[s].reindex(df.index).fillna(0.0)
        if mix_trend > 0:
            tr = TREND(df)
            return (1 - mix_trend) * ml + mix_trend * tr
        return ml
    return fn


def paired_sharpe_diff(a: pd.Series, b: pd.Series, n=2000, block=20, seed=0):
    """Stationary (Politis-Romano) paired bootstrap of SR(a) - SR(b): same resampled days for both."""
    j = pd.concat([a, b], axis=1).dropna()
    x, y = j.iloc[:, 0].to_numpy(), j.iloc[:, 1].to_numpy()
    T = len(x)
    rng = np.random.default_rng(seed)
    out = np.empty(n)
    t = np.arange(T)
    for k in range(n):
        new = rng.random(T) < 1.0 / block
        new[0] = True
        starts = rng.integers(0, T, size=T)
        bid = np.cumsum(new) - 1
        first = np.flatnonzero(new)
        idx = (starts[first][bid] + (t - first[bid])) % T
        xa, ya = x[idx], y[idx]
        out[k] = (xa.mean() / xa.std() - ya.mean() / ya.std()) * np.sqrt(252)
    obs = (x.mean() / x.std() - y.mean() / y.std()) * np.sqrt(252)
    return obs, float(np.quantile(out, 0.025)), float(np.quantile(out, 0.975)), float((out <= 0).mean())


def carry_z_signal(df):
    c = df["carry"].clip(-3, 3)
    z = (c - c.rolling(250, min_periods=120).mean()) / c.rolling(250, min_periods=120).std()
    return (z / 1.0).clip(-2, 2).fillna(0.0) / 0.8  # ~unit mean |signal|


def static_drift_signal(df):
    """What the pooled models' instrument dummies amount to: sign of the instrument's average daily
    return over all *past* data (expanding), i.e. long crude / short gas most of the time."""
    m = df["ret"].expanding(min_periods=500).mean().shift(1)
    return np.sign(m).fillna(0.0)


def main():
    ps.apply()
    P = build_panel()
    cols = feature_cols(P)
    print(f"panel: {len(P)} rows, {len(cols)} features; first test year {FIRST_TEST_YEAR}")
    FUTS = {s: FUT[s].assign(sym=s) for s in SYMBOLS}

    variants = [(m, t, pooled) for m in ["lr", "lgbm"] for t in ["y1", "y5"] for pooled in [False, True]]
    all_preds, cm_rows, strat_rows, imps, corr_rows, sig_store, ports = [], [], [], {}, [], {}, {}
    trend = evaluate(TREND, "trend_multi_ewmac", data=FUTS, start=f"{FIRST_TEST_YEAR}-01-01", keep_series=True)
    strat_rows.append(trend["table"].assign(model="trend", target="", pooled="", lag=1, blend=0.0))
    trend2 = evaluate(TREND, "trend_multi_ewmac", data=FUTS, start=f"{FIRST_TEST_YEAR}-01-01", lag=2)
    strat_rows.append(trend2["table"].assign(model="trend", target="", pooled="", lag=2, blend=0.0))
    ports["trend"] = trend["port"]
    for model, target, pooled in variants:
        name = f"{model}_{target}_{'pooled' if pooled else 'per_instr'}"
        pr, im = walk_forward(P, model, target, pooled)
        pr["variant"] = name
        all_preds.append(pr)
        imps[name] = im
        cm_rows += class_metrics(pr, name, target)
        sig = ml_signal(pr)
        sig_store[name] = sig
        for blend, lag in [(0.0, 1), (0.0, 2), (0.5, 1), (0.5, 2)]:
            r = evaluate(make_fn(sig, blend), name, data=FUTS, start=f"{FIRST_TEST_YEAR}-01-01", lag=lag,
                         keep_series=True)
            t = r["table"].assign(model=model, target=target, pooled=pooled, lag=lag, blend=blend)
            strat_rows.append(t)
            if lag == 1:
                ports[f"{name}|blend{blend}"] = r["port"]
            if blend == 0.0 and lag == 1:
                for s in SYMBOLS + ["PORT"]:
                    a = r["port"] if s == "PORT" else r["nets"][s]
                    b = trend["port"] if s == "PORT" else trend["nets"][s]
                    j = pd.concat([a, b], axis=1).dropna()
                    j = j[j.index >= f"{FIRST_TEST_YEAR}-01-01"]
                    sig_corr = np.nan
                    if s != "PORT":
                        tr_sig = TREND(FUTS[s]).reindex(sig[s].index)
                        sig_corr = np.corrcoef(sig[s].values, tr_sig.fillna(0).values)[0, 1]
                    corr_rows.append({"variant": name, "symbol": s, "corr_daily_net_vs_trend": j.corr().iloc[0, 1],
                                      "corr_signal_vs_trend_signal": sig_corr})
        print(f"done {name}")
    # simple non-ML factor benchmarks on the same window
    bench = {"carry_z": carry_z_signal, "static_drift": static_drift_signal,
             "trend+carry_z": lambda d: 0.5 * TREND(d) + 0.5 * carry_z_signal(d),
             "trend+carry_z+drift": lambda d: (TREND(d) + carry_z_signal(d) + static_drift_signal(d)) / 3}
    for bn, bfn in bench.items():
        for lag in [1, 2]:
            r = evaluate(bfn, f"bench_{bn}", data=FUTS, start=f"{FIRST_TEST_YEAR}-01-01", lag=lag, keep_series=True)
            strat_rows.append(r["table"].assign(model="benchmark", target="", pooled="", lag=lag, blend=0.0))
            if lag == 1:
                ports[f"bench_{bn}"] = r["port"]
        r = evaluate(bfn, f"bench_{bn}", data=FUTS, start=f"{FIRST_TEST_YEAR}-01-01", cost_mult=2.0)
        strat_rows.append(r["table"].assign(model="benchmark", target="", pooled="", lag=1, blend=0.0, cost_mult=2.0))
        r = evaluate(bfn, f"bench_{bn}", data=FUTS, start=f"{FIRST_TEST_YEAR}-01-01", cost_mult=0.0, fin=0.0)
        strat_rows.append(r["table"].assign(model="benchmark", target="", pooled="", lag=1, blend=0.0, cost_mult=0.0))
    # 2x costs for every ML variant (standalone and blend) and trend
    for name, sig in sig_store.items():
        for blend in [0.0, 0.5]:
            for cm in [2.0, 0.0]:
                r = evaluate(make_fn(sig, blend), name, data=FUTS, start=f"{FIRST_TEST_YEAR}-01-01", cost_mult=cm,
                             fin=0.0 if cm == 0.0 else None)
                strat_rows.append(r["table"].assign(model=name.split("_")[0], target=name.split("_")[1],
                                                    pooled="pooled" in name, lag=1, blend=blend, cost_mult=cm))
    for cm in [2.0, 0.0]:
        r = evaluate(TREND, "trend_multi_ewmac", data=FUTS, start=f"{FIRST_TEST_YEAR}-01-01", cost_mult=cm,
                     fin=0.0 if cm == 0.0 else None)
        strat_rows.append(r["table"].assign(model="trend", target="", pooled="", lag=1, blend=0.0, cost_mult=cm))

    preds = pd.concat(all_preds)
    preds.to_csv(os.path.join(OUT, "e08_oos_predictions.csv"))
    CM = pd.DataFrame(cm_rows)
    CM.to_csv(os.path.join(OUT, "e08_classification_metrics.csv"), index=False)
    ST = pd.concat(strat_rows, ignore_index=True)
    ST["cost_mult"] = ST["cost_mult"].fillna(1.0) if "cost_mult" in ST else 1.0
    ST.to_csv(os.path.join(OUT, "e08_strategy_results.csv"), index=False)
    CR = pd.DataFrame(corr_rows)
    CR.to_csv(os.path.join(OUT, "e08_correlations.csv"), index=False)
    print("\n=== classification (OOS 2005-2024; y5 on non-overlapping 5-day samples)")
    print(CM[["model", "target", "symbol", "n_eval", "base_rate_up", "accuracy", "acc_minus_best_naive", "acc_se",
              "auc", "auc_z", "logloss_gain", "trend_sign_accuracy", "trend_auc"]].round(4).to_string(index=False))
    print("\n=== strategies (PORT) 2005-2024")
    sp = ST[ST.symbol == "PORT"]
    print(sp[["name", "blend", "lag", "cost_mult", "sharpe", "cagr", "max_dd", "sr_2000-2009", "sr_2010-2019",
              "sr_2020-2029"]].round(3).to_string(index=False))
    print("\n=== per instrument, lag 1, no blend")
    si = ST[(ST.symbol != "PORT") & (ST.lag == 1) & (ST.blend == 0.0)]
    print(si[["name", "symbol", "sharpe", "gross_sharpe", "turnover_py", "cost_py"]].round(3).to_string(index=False))
    print("\n=== correlations with trend\n", CR.round(3).to_string(index=False))

    # feature importance (average over years), pooled models
    fi_rows = []
    for name, im in imps.items():
        m = im.abs().mean(axis=1) if name.startswith("lr") else im.mean(axis=1)
        m = m / m.sum()
        for f, v in m.sort_values(ascending=False).items():
            fi_rows.append({"variant": name, "feature": f, "importance_share": v})
    FI = pd.DataFrame(fi_rows)
    FI.to_csv(os.path.join(OUT, "e08_feature_importance.csv"), index=False)
    print("\n=== top features (LGBM pooled)")
    for nm in ["lgbm_y1_pooled", "lgbm_y5_pooled"]:
        print(nm, FI[FI.variant == nm].head(12)[["feature", "importance_share"]].round(3).to_string(index=False))

    # bootstrap CI for PORT Sharpe and the blend-minus-trend difference
    boot_rows = []
    tr_port = ports["trend"][ports["trend"].index >= f"{FIRST_TEST_YEAR}-01-01"]
    tc_port = ports["bench_trend+carry_z"][ports["bench_trend+carry_z"].index >= f"{FIRST_TEST_YEAR}-01-01"]
    for key, s_ in ports.items():
        s_ = s_[s_.index >= f"{FIRST_TEST_YEAR}-01-01"]
        lo, hi = bt.bootstrap_sharpe_ci(s_, n=1000)
        row = {"series": key, "sharpe": bt.sharpe(s_), "ci95_lo": lo, "ci95_hi": hi,
               "corr_vs_trend": pd.concat([s_, tr_port], axis=1).dropna().corr().iloc[0, 1]}
        if key != "trend":
            d, dlo, dhi, p0 = paired_sharpe_diff(s_, tr_port)
            row.update({"sr_minus_trend": d, "diff_ci95_lo": dlo, "diff_ci95_hi": dhi, "p_diff_le_0": p0})
        if key not in ("trend", "bench_trend+carry_z"):
            d, dlo, dhi, p0 = paired_sharpe_diff(s_, tc_port)
            row.update({"sr_minus_trend_carry": d, "tc_diff_ci95_lo": dlo, "tc_diff_ci95_hi": dhi,
                        "p_tc_diff_le_0": p0})
        boot_rows.append(row)
    BO = pd.DataFrame(boot_rows)
    # deflated Sharpe of each standalone ML variant against the 8 standalone ML variants tried
    ml_keys = [k for k in ports if k.endswith("|blend0.0")]
    trial_sr = [bt.sharpe(ports[k][ports[k].index >= f"{FIRST_TEST_YEAR}-01-01"]) for k in ml_keys]
    for k in ml_keys:
        x = ports[k][ports[k].index >= f"{FIRST_TEST_YEAR}-01-01"]
        BO.loc[BO.series == k, "dsr_vs_8_ml_variants"] = bt.deflated_sharpe(bt.sharpe(x), trial_sr, len(x),
                                                                            float(x.skew()), float(x.kurt() + 3))
    BO.to_csv(os.path.join(OUT, "e08_port_bootstrap.csv"), index=False)
    print("\n=== PORT Sharpe bootstrap + difference vs trend\n", BO.round(3).to_string(index=False))

    # AUC by year (for the chart)
    ay = []
    for name, g in preds.groupby("variant"):
        for (s, y), x in g.groupby(["sym", "year"]):
            x = x.dropna(subset=["y"])
            if x["y"].nunique() == 2 and len(x) > 30:
                ay.append({"variant": name, "symbol": s, "year": y, "auc": roc_auc_score(x["y"], x["p"]),
                           "trend_auc": roc_auc_score(x["y"], x["ewmac"]), "n": len(x)})
    AY = pd.DataFrame(ay)
    AY.to_csv(os.path.join(OUT, "e08_auc_by_year.csv"), index=False)

    summary_table(ST, CM, CR)
    charts(ports, AY, FI, CM)


def summary_table(ST, CM, CR):
    rows = []
    base = ST[(ST.lag == 1) & (ST.cost_mult == 1.0)]
    lag2 = ST[(ST.lag == 2) & (ST.cost_mult == 1.0)]
    c2 = ST[(ST.lag == 1) & (ST.cost_mult == 2.0)]
    c0 = ST[(ST.lag == 1) & (ST.cost_mult == 0.0)]
    bench_label = {"bench_carry_z": "Carry z-score alone (simple, no ML)",
                   "bench_static_drift": "Static drift: sign of past mean return (long crude / short NG)",
                   "bench_trend+carry_z": "50/50 trend + carry z-score (simple, no ML)",
                   "bench_trend+carry_z+drift": "Trend + carry z + static drift, equal weight (simple)"}
    for _, r in base.iterrows():
        if r["model"] == "trend":
            strat, verdict = "Trend: multi-speed EWMAC (reference)", "reference"
        elif r["model"] == "benchmark":
            strat, verdict = bench_label[r["name"]], "benchmark"
        else:
            pooled = "pooled" if r["pooled"] in (True, "True") else "per-instrument"
            strat = (f"{'LogReg L2' if r['model'] == 'lr' else 'LightGBM'}, "
                     f"{'next-day' if r['target'] == 'y1' else 'next-5-day'} target, {pooled}")
            if r["blend"] > 0:
                strat = "50/50 blend: trend + " + strat
            verdict = ""
        key = (r["name"], r["blend"], r["symbol"])

        def pick(df):
            x = df[(df.name == key[0]) & (df.blend == key[1]) & (df.symbol == key[2])]
            return x["sharpe"].iloc[0] if len(x) else np.nan
        c = CM[(CM.model == r["name"]) & (CM.symbol == (r["symbol"] if r["symbol"] != "PORT" else "ALL"))]
        is_ml = r["model"] in ("lr", "lgbm")
        rows.append({"strategy": strat, "variant": r["name"], "blend": r["blend"], "instrument": r["symbol"],
                     "period": f"{r['start'][:4]}-{r['end'][:4]}", "net_sharpe": r["sharpe"],
                     "sr_2005_2007": r["is_sharpe"], "sr_2008_2024": r["oos_sharpe"],
                     "sr_2010s": r.get("sr_2010-2019"), "sr_2020s": r.get("sr_2020-2029"),
                     "net_sharpe_lag2": pick(lag2), "net_sharpe_2x_cost": pick(c2),
                     "gross_sharpe": pick(c0), "cagr": r["cagr"], "max_dd": r["max_dd"],
                     "turnover_py": r.get("turnover_py") if r["symbol"] != "PORT" else base[
                         (base.name == r["name"]) & (base.blend == r["blend"]) & (base.symbol != "PORT")][
                         "turnover_py"].mean(),
                     "oos_accuracy": c["accuracy"].iloc[0] if len(c) and is_ml and r["blend"] == 0 else np.nan,
                     "oos_auc": c["auc"].iloc[0] if len(c) and is_ml and r["blend"] == 0 else np.nan,
                     "verdict": verdict})
    T = pd.DataFrame(rows)
    T.to_csv(os.path.join(OUT, "e08_summary_table.csv"), index=False)
    print("\n=== SUMMARY (PORT rows)\n", T[T.instrument == "PORT"].drop(columns=["strategy"]).round(3)
          .to_string(index=False))
    return T


def charts(ports, AY, FI, CM):
    import matplotlib.pyplot as plt

    # 1. PORT equity: trend vs best ML vs blend
    fig, ax = plt.subplots(figsize=(11, 4.6))
    items = [("trend", "Trend only (multi-speed EWMAC)", ps.SERIES[0]),
             ("lr_y5_pooled|blend0.0", "Best ML: logistic next-5-day, pooled", ps.SERIES[1]),
             ("lgbm_y1_pooled|blend0.0", "LightGBM next-day, pooled", ps.SERIES[2]),
             ("bench_trend+carry_z", "Simple 50/50 trend + carry z (no ML)", ps.SERIES[3])]
    for key, lab, col in items:
        s = ports[key]
        s = s[s.index >= f"{FIRST_TEST_YEAR}-01-01"]
        eq = (1 + s).cumprod()
        ax.plot(eq.index, eq.values, color=col, lw=1.3, label=f"{lab} (SR {bt.sharpe(s):.2f})")
        ax.text(eq.index[-1], eq.values[-1], f"  {eq.values[-1]:.2f}x", color=ps.INK2, fontsize=8, va="center")
    from matplotlib.ticker import FixedLocator, FuncFormatter, NullLocator
    ax.set_yscale("log")
    ax.yaxis.set_major_locator(FixedLocator([0.5, 0.75, 1, 1.5, 2, 3, 4, 5]))
    ax.yaxis.set_minor_locator(NullLocator())
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:g}"))
    ax.set_ylabel("growth of 1, net of costs (log scale)")
    ax.legend(loc="upper left")
    ps.title(fig, "Walk-forward ML vs trend and a two-factor rule, 3-instrument portfolio, 2005-2024", y=1.06)
    ps.subtitle(fig, "All ML predictions out-of-sample (expanding window, yearly refit, 5-day purge). "
                     "15% vol target, CFD costs + 2.5% financing.", y=1.0)
    ps.save(fig, os.path.join(OUT, "e08_equity.png"))

    # 2. AUC by year (pooled models, all instruments averaged) vs trend
    fig, axes = plt.subplots(1, 2, figsize=(12.5, 4.2), sharey=True)
    AY = AY[AY.year <= 2023]  # 2024 = Jan-Mar only
    for ax, tgt in zip(axes, ["y1", "y5"]):
        for key, lab, col in [(f"lgbm_{tgt}_pooled", "LightGBM pooled", ps.SERIES[1]),
                              (f"lr_{tgt}_pooled", "Logistic pooled", ps.SERIES[2])]:
            a = AY[AY.variant == key].groupby("year")["auc"].mean()
            ax.plot(a.index, a.values, color=col, lw=1.3, marker="o", markersize=4, label=lab)
        t = AY[AY.variant == f"lgbm_{tgt}_pooled"].groupby("year")["trend_auc"].mean()
        ax.plot(t.index, t.values, color=ps.SERIES[0], lw=1.3, marker="o", markersize=4,
                label="Trend forecast as a score")
        ax.axhline(0.5, color=ps.AXIS, lw=0.9)
        ax.set_title("Next-day direction" if tgt == "y1" else "Next-5-day direction (overlapping, daily)",
                     fontsize=10.5)
        ax.set_xlabel("test year")
        ax.set_xticks(range(2005, 2024, 3))
    axes[0].set_ylabel("out-of-sample AUC (mean of 3 instruments)")
    axes[0].legend(loc="lower left", fontsize=8)
    ps.title(fig, "Within each year, out-of-sample AUC hovers around 0.5 - ML and trend alike", y=1.06)
    ps.subtitle(fig, "AUC computed within each calendar year, averaged over WTI, Brent and NG (2005-2023).", y=1.0)
    ps.save(fig, os.path.join(OUT, "e08_auc_by_year.png"))

    # 3. feature importance (LightGBM pooled, next-day and next-5-day)
    fig, axes = plt.subplots(1, 2, figsize=(12.5, 5.0))
    for ax, key in zip(axes, ["lgbm_y1_pooled", "lgbm_y5_pooled"]):
        f = FI[FI.variant == key].head(15).iloc[::-1]
        ax.barh(f["feature"], f["importance_share"] * 100, color=ps.SERIES[0], height=0.6)
        ax.set_title(("Next-day" if "y1" in key else "Next-5-day") + " LightGBM (pooled): top 15 by gain",
                     fontsize=10.5)
        ax.set_xlabel("share of total gain, %")
        ax.grid(axis="y", visible=False)
    ps.title(fig, "What the trees use: volatility, carry, crack spreads and trend state - no dominant signal",
             y=1.04)
    fig.tight_layout()
    ps.save(fig, os.path.join(OUT, "e08_feature_importance.png"))


if __name__ == "__main__":
    main()
