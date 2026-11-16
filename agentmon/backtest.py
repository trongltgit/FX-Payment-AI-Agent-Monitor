"""Backtest/đánh giá mô hình – trả lời câu hỏi "cơ sở đánh giá là gì?".

Chạy:
  python -m agentmon.backtest --synthetic                       # kiểm tra hồi quy trên dữ liệu tổng hợp, tách seed/khách
  python -m agentmon.backtest --csv data.csv --domain PAY       # dữ liệu thật: tách THEO THỜI GIAN (train quá khứ → test tương lai)
  python -m agentmon.backtest --csv data.csv --domain PAY --save-model   # huấn luyện lại trên toàn bộ dữ liệu sau khi đánh giá

Kết quả: reports/backtest_<domain>_<ngày>.json và .md. Dữ liệu tổng hợp KHÔNG phải bằng chứng hiệu quả thực tế.
"""
import argparse
import json
import os
import time

from agentmon import dataio, ml

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "reports")


def _md(res):
    L = [f"# Báo cáo backtest – {res['domain']} ({res['mode']})", "",
         f"* Thời điểm: {res['generated_at']}", f"* Nguồn dữ liệu: {res['source']}",
         f"* Train: {res['train']['n']} giao dịch · Test: {res['test']['n']} giao dịch ({res['test'].get('n_positive', 0)} dương tính, "
         f"tỷ lệ {res['test'].get('positive_rate')})", f"* Phương pháp tách: {res['split']}", ""]
    if res.get("warning"):
        L += [f"> ⚠ {res['warning']}", ""]
    t = res["test"]
    if "auc_final" in t:
        L += [f"**AUC (chỉ ML):** {t['auc_ml_only']} · **AUC (điểm cuối):** {t['auc_final']} · **AP:** {t['ap_final']}", ""]
    L += ["| Mức quyết định | Ngưỡng | Tỷ lệ cảnh báo | Recall | Precision | Báo nhầm (FPR) |", "|---|---|---|---|---|---|"]
    for k in ("KYA_or_above", "REVIEW_or_above", "BLOCK"):
        m = t[k]
        L.append(f"| {k} | {m['threshold']} | {m['alert_rate']} | {m['recall']} | {m['precision']} | {m['false_positive_rate']} |")
    if t.get("kya_false_positive_by_trigger"):
        L += ["", "**Trigger gây KYA cho giao dịch lành tính (nguồn báo nhầm chính, dùng để hiệu chỉnh chính sách):** " +
              ", ".join(f"{k}={v}" for k, v in t["kya_false_positive_by_trigger"].items())]
    L += ["", "Chưa gồm LLM Critic (chỉ nâng mức) và Hard Policy (chặn cứng theo hạn mức).", ""]
    return "\n".join(L)


def run(domain, csv_path=None, synthetic=False, train_frac=0.7, save_model=False, seed=7):
    os.makedirs(OUT, exist_ok=True)
    if synthetic:
        tr = ml.generate(domain, 45, 170, seed, with_scores=True)
        te = ml.generate(domain, 20, 170, seed + 5000, with_scores=True)
        split, source, mode = "Tập test là các khách sinh bằng seed khác (không trùng khách với train)", f"synthetic(seed={seed})", "synthetic"
        warn = "Dữ liệu tổng hợp do cùng bộ sinh/cùng hàm feature tạo ra: chỉ là kiểm tra hồi quy, KHÔNG chứng minh hiệu quả thực tế."
    else:
        txns, rep = dataio.load_csv(csv_path, domain)
        if rep["rows"] < 500:
            raise SystemExit(f"Quá ít dữ liệu ({rep['rows']} dòng) – cần tối thiểu vài nghìn giao dịch (xem docs/DATA_REQUIREMENTS.md).")
        rows = dataio.build_rows(txns, domain)
        cut = rows[int(len(rows) * train_frac)][5]
        tr = [r for r in rows if r[5] < cut and r[1] == 0]          # huấn luyện chỉ trên giao dịch KHÔNG gian lận trong quá khứ
        te = [r for r in rows if r[5] >= cut]
        split = f"Theo thời gian: train = {train_frac:.0%} đầu (chỉ giao dịch không nhãn gian lận), test = phần sau (cắt tại ts={int(cut)})"
        source, mode = f"csv:{os.path.basename(csv_path)} ({rep['rows']} dòng, {rep['customers']} khách, {rep['span_days']} ngày)", "real-data"
        warn = "" if rep["positives"] else "Không có nhãn gian lận → không tính được recall/precision; chỉ có tỷ lệ cảnh báo."
        if rep["positives"] and rep["positives"] < 30:
            warn = f"Chỉ có {rep['positives']} nhãn dương – kết quả không ổn định về mặt thống kê."
    info, pkg = ml.fit(domain, tr, seed, source=source, save=False)
    test = ml.evaluate_rows(pkg, te)
    res = {"domain": domain, "mode": mode, "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"), "source": source, "split": split,
           "warning": warn, "model_version_candidate": info["version"], "train": {"n": len(tr)}, "test": test}
    tag = f"{domain}_{time.strftime('%Y%m%d_%H%M%S')}"
    with open(os.path.join(OUT, f"backtest_{tag}.json"), "w", encoding="utf-8") as fh:
        json.dump(res, fh, ensure_ascii=False, indent=1)
    with open(os.path.join(OUT, f"backtest_{tag}.md"), "w", encoding="utf-8") as fh:
        fh.write(_md(res))
    if save_model and not synthetic:
        full = [r for r in rows if r[1] == 0]
        res["saved_model"] = ml.fit(domain, full, seed, source=source, holdout=te)["version"]
    return res


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--domain", choices=["FX", "PAY"], default="PAY")
    ap.add_argument("--csv")
    ap.add_argument("--synthetic", action="store_true")
    ap.add_argument("--train-frac", type=float, default=0.7)
    ap.add_argument("--save-model", action="store_true")
    a = ap.parse_args()
    if not a.csv and not a.synthetic:
        ap.error("Cần --csv <file> hoặc --synthetic")
    r = run(a.domain, a.csv, a.synthetic, a.train_frac, a.save_model)
    print(_md(r))
