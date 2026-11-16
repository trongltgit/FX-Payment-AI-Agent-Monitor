"""Nạp dữ liệu giao dịch THẬT (CSV) → bảng đặc trưng, bằng đúng hàm feature của hệ thống.

Mỗi dòng CSV là một giao dịch lịch sử của khách (không nhất thiết do Agent). Tái hiện theo thứ tự thời gian từng khách:
baseline = giao dịch trước đó của khách; attempts = giao dịch trong 24 giờ trước. Nhãn (tùy chọn) dùng ĐỂ ĐÁNH GIÁ, không dùng để huấn luyện
(Isolation Forest không giám sát) – mô hình huấn luyện chỉ trên giao dịch KHÔNG có nhãn gian lận.
Định nghĩa cột và nguồn dữ liệu: docs/DATA_REQUIREMENTS.md, mẫu: docs/templates/*.csv.
"""
import csv
import datetime as dt

from agentmon import features as F
from agentmon import policy
from agentmon.constants import PAY_KINDS

COMMON = ["txn_id", "customer_id", "ts", "domain", "kind"]
FX_COLS = COMMON + ["pair", "side", "notional_usd", "leverage", "segment", "balance_vnd", "fraud_label", "label_source"]
PAY_COLS = COMMON + ["amount_vnd", "channel_type", "beneficiary_account", "merchant_id", "mcc", "country", "three_ds", "device_id",
                     "segment", "balance_vnd", "fraud_label", "label_source"]
LABEL_SOURCES = ("chargeback", "fraud_case", "customer_dispute", "kya_denied", "review_rejected", "")


class DataError(Exception):
    pass


def _ts(v):
    v = str(v).strip()
    try:
        return float(v)
    except ValueError:
        pass
    try:
        d = dt.datetime.fromisoformat(v.replace("Z", "+00:00"))
        if d.tzinfo is None:
            d = d.replace(tzinfo=dt.timezone(dt.timedelta(hours=7)))
        return d.timestamp()
    except ValueError:
        raise DataError(f"ts không hợp lệ: {v!r} (dùng epoch giây hoặc ISO-8601)")


def _f(v, default=None):
    v = (v or "").strip() if isinstance(v, str) else v
    if v in (None, ""):
        return default
    return float(v)


def load_csv(path, domain, usd_vnd=26200.0):
    """Đọc + kiểm tra CSV. Trả (rows, report). Dòng lỗi bị bỏ và được thống kê, không dừng toàn bộ."""
    need = FX_COLS if domain == "FX" else PAY_COLS
    rows, bad, reasons = [], 0, {}
    with open(path, newline="", encoding="utf-8-sig") as fh:
        rd = csv.DictReader(fh)
        miss = [c for c in COMMON if c not in (rd.fieldnames or [])]
        amt_col = "notional_usd" if domain == "FX" else "amount_vnd"
        if amt_col not in (rd.fieldnames or []):
            miss.append(amt_col)
        if miss:
            raise DataError("Thiếu cột bắt buộc: " + ", ".join(miss))
        for i, r in enumerate(rd, start=2):
            try:
                if r["domain"].strip().upper() != domain:
                    continue
                a = {"ts": _ts(r["ts"]), "domain": domain, "kind": r["kind"].strip().upper(), "customer_id": r["customer_id"].strip(),
                     "txn_id": r["txn_id"].strip(), "segment": (r.get("segment") or "STANDARD").strip().upper(),
                     "balance_vnd": _f(r.get("balance_vnd")),
                     "label": int(r["fraud_label"]) if (r.get("fraud_label") or "").strip() in ("0", "1") else None,
                     "label_source": (r.get("label_source") or "").strip()}
                if a["label"] is not None and a["label_source"] not in LABEL_SOURCES:
                    raise DataError(f"label_source không hợp lệ: {a['label_source']}")
                a["hour"] = F.local_hour(a["ts"])
                if domain == "FX":
                    if a["kind"] != "FX_TRADE":
                        raise DataError("kind FX phải là FX_TRADE")
                    usd = _f(r["notional_usd"])
                    lev = _f(r.get("leverage"), 1.0)
                    if not usd or usd <= 0 or lev < 1:
                        raise DataError("notional_usd/leverage không hợp lệ")
                    a.update(pair=(r.get("pair") or "").upper(), side=(r.get("side") or "").upper(), amount_usd=usd, leverage=lev,
                             amount_vnd=usd * usd_vnd, margin_vnd=usd * usd_vnd / lev)
                else:
                    if a["kind"] not in PAY_KINDS:
                        raise DataError(f"kind PAY không hợp lệ: {a['kind']}")
                    amt = _f(r["amount_vnd"])
                    if not amt or amt <= 0:
                        raise DataError("amount_vnd không hợp lệ")
                    a.update(amount_vnd=amt, margin_vnd=None, channel_type=(r.get("channel_type") or "").upper() or None,
                             beneficiary=(r.get("beneficiary_account") or "").strip() or None, merchant=(r.get("merchant_id") or "").strip() or None,
                             mcc=(r.get("mcc") or "").strip() or None, country=(r.get("country") or "").strip().upper() or None,
                             three_ds=(r.get("three_ds") or "").strip().lower() in ("1", "true", "yes"),
                             device_id=(r.get("device_id") or "").strip() or None)
                rows.append(a)
            except (DataError, ValueError, KeyError) as e:
                bad += 1
                k = str(e)[:60]
                reasons[k] = reasons.get(k, 0) + 1
    rows.sort(key=lambda x: x["ts"])
    labeled = sum(1 for r in rows if r["label"] is not None)
    pos = sum(1 for r in rows if r["label"] == 1)
    rep = {"rows": len(rows), "skipped": bad, "skip_reasons": reasons, "customers": len({r["customer_id"] for r in rows}),
           "labeled": labeled, "positives": pos, "span_days": round((rows[-1]["ts"] - rows[0]["ts"]) / 86400, 1) if rows else 0,
           "expected_columns": need}
    return rows, rep


def build_rows(txns, domain, with_scores=True, max_hist=150):
    """Tái hiện theo thời gian → [(vec, label, beh, vel, trigger_codes, ts)]. Chỉ dùng giao dịch KHÔNG bị gắn gian lận làm baseline."""
    from collections import defaultdict
    by = defaultdict(list)
    for t in txns:
        by[t["customer_id"]].append(t)
    out = []
    dflt = policy.DEFAULTS[domain]
    for cid, lst in by.items():
        lst.sort(key=lambda x: x["ts"])
        hist, att = [], []
        for t in lst:
            seg = t["segment"] if t["segment"] in dflt["segments"] else "STANDARD"
            limits = dict(dflt["segments"][seg])
            limits["_global"] = dflt["global"]
            bal = t["balance_vnd"] if t["balance_vnd"] else (F._cap(F.Ctx(domain, 0, limits=limits), t) * 50 * (26200 if domain == "FX" else 1))
            last = hist[-1]["ts"] if hist else None
            ctx = F.Ctx(domain, t["ts"], hist[-max_hist:], [x for x in att if t["ts"] - x["ts"] < 86400], bal, limits, set(),
                        online_exec_any=len(hist), last_exec_ts=last)
            ctx.cum = {"day": sum(x.get("amount_usd") or 0 for x in att if t["ts"] - x["ts"] < 86400) if domain == "FX" else 0.0}
            vec = F.feature_vector(t, ctx)
            lab = t["label"] if t["label"] is not None else 0
            if with_scores:
                beh, _ = F.behavior_score(t, ctx)
                vel, _ = F.velocity_score(t, ctx)
                out.append((vec, lab, beh, vel, tuple(sorted(x[0] for x in F.triggers(t, ctx))), t["ts"]))
            else:
                out.append((vec, lab, 0.0, 0.0, (), t["ts"]))
            att.append({"ts": t["ts"], "amount_vnd": t.get("amount_vnd"), "decision": "ALLOW", "merchant": t.get("merchant")})
            if t["label"] != 1:
                hist.append(t)
    out.sort(key=lambda r: r[5])
    return out


TEMPLATE_PAY = ("txn_id,customer_id,ts,domain,kind,amount_vnd,channel_type,beneficiary_account,merchant_id,mcc,country,three_ds,device_id,segment,balance_vnd,fraud_label,label_source\n"
                "T0001,C001,2026-01-05T09:12:00+07:00,PAY,TRANSFER,3000000,,1234567890,,,,,,STANDARD,120000000,0,\n"
                "T0002,C001,2026-01-06T20:40:00+07:00,PAY,ATM_WITHDRAWAL,2000000,ATM,,ATM0101,6011,VN,,,STANDARD,118000000,0,\n"
                "T0003,C002,2026-01-07T02:15:00+07:00,PAY,WALLET_PAYMENT,4500000,WALLET,,M777,5732,VN,,DEV-ABC123,VIP,900000000,1,chargeback\n")
TEMPLATE_FX = ("txn_id,customer_id,ts,domain,kind,pair,side,notional_usd,leverage,segment,balance_vnd,fraud_label,label_source\n"
               "F0001,C001,2026-01-05T10:00:00+07:00,FX,FX_TRADE,USDVND,BUY,15000,2,STANDARD,500000000,0,\n"
               "F0002,C001,2026-01-05T10:00:20+07:00,FX,FX_TRADE,USDVND,BUY,15000,2,STANDARD,500000000,0,\n"
               "F0003,C002,2026-01-06T03:30:00+07:00,FX,FX_TRADE,GBPUSD,SELL,95000,18,VIP,2000000000,1,fraud_case\n")
