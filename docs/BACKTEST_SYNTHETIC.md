# Kết quả backtest trên dữ liệu TỔNG HỢP (kiểm tra hồi quy)

> **Không phải bằng chứng hiệu quả thực tế.** Dữ liệu do chính bộ sinh/hàm feature của hệ thống tạo ra; tập test dùng seed và khách khác tập train. Dùng để phát hiện hồi quy khi sửa mô hình/chính sách. Số liệu thật: `python -m agentmon.backtest --csv <file> --domain PAY` (xem `DATA_REQUIREMENTS.md`).

## Ghi nhận tối ưu cấu hình v2.0 (phân hệ thanh toán, cùng tập test)

Điều kiện trigger `AMOUNT_OVER_KYA` đổi từ *số tiền ≥ ngưỡng* thành *số tiền ≥ ngưỡng **và** lệch thói quen (≥ 1,5 lần mức thường lệ) hoặc lịch sử mỏng* (`kya_above_min_ratio`).

| Chỉ số (KYA trở lên) | Trước | Sau |
|---|---|---|
| Tỷ lệ cảnh báo | 0,277 | 0,250 |
| Recall | 0,815 | 0,811 |
| Precision | 0,555 | 0,612 |
| Báo nhầm (FPR) | 0,152 | 0,119 |

Báo nhầm giảm khoảng 22% tương đối, recall gần như không đổi – trên dữ liệu tổng hợp; cần kiểm lại trên dữ liệu thật.

## Báo cáo backtest – PAY (synthetic)

* Thời điểm: 2026-11-13 05:27:28
* Nguồn dữ liệu: synthetic(seed=7)
* Train: 8827 giao dịch · Test: 3911 giao dịch (736 dương tính, tỷ lệ 0.1882)
* Phương pháp tách: Tập test là các khách sinh bằng seed khác (không trùng khách với train)

> ⚠ Dữ liệu tổng hợp do cùng bộ sinh/cùng hàm feature tạo ra: chỉ là kiểm tra hồi quy, KHÔNG chứng minh hiệu quả thực tế.

**AUC (chỉ ML):** 0.9408 · **AUC (điểm cuối):** 0.9479 · **AP:** 0.8476

| Mức quyết định | Ngưỡng | Tỷ lệ cảnh báo | Recall | Precision | Báo nhầm (FPR) |
|---|---|---|---|---|---|
| KYA_or_above | 0.35 | 0.2496 | 0.8111 | 0.6117 | 0.1194 |
| REVIEW_or_above | 0.65 | 0.0258 | 0.1359 | 0.9901 | 0.0003 |
| BLOCK | 0.85 | 0.01 | 0.053 | 1.0 | 0.0 |

**Trigger gây KYA cho giao dịch lành tính (nguồn báo nhầm chính, dùng để hiệu chỉnh chính sách):** NEW_BENEFICIARY=171, AMOUNT_OVER_KYA=75, NEW_DEVICE=59, DORMANT_WAKE=28, FIRST_ONLINE=18, NEW_COUNTRY=9, ATM_FOREIGN=1

Chưa gồm LLM Critic (chỉ nâng mức) và Hard Policy (chặn cứng theo hạn mức).

## Báo cáo backtest – FX (synthetic)

* Thời điểm: 2026-11-13 05:27:34
* Nguồn dữ liệu: synthetic(seed=7)
* Train: 9034 giao dịch · Test: 4004 giao dịch (845 dương tính, tỷ lệ 0.211)
* Phương pháp tách: Tập test là các khách sinh bằng seed khác (không trùng khách với train)

> ⚠ Dữ liệu tổng hợp do cùng bộ sinh/cùng hàm feature tạo ra: chỉ là kiểm tra hồi quy, KHÔNG chứng minh hiệu quả thực tế.

**AUC (chỉ ML):** 0.8705 · **AUC (điểm cuối):** 0.8727 · **AP:** 0.7601

| Mức quyết định | Ngưỡng | Tỷ lệ cảnh báo | Recall | Precision | Báo nhầm (FPR) |
|---|---|---|---|---|---|
| KYA_or_above | 0.35 | 0.1089 | 0.3941 | 0.7638 | 0.0326 |
| REVIEW_or_above | 0.65 | 0.014 | 0.0663 | 1.0 | 0.0 |
| BLOCK | 0.85 | 0.0027 | 0.013 | 1.0 | 0.0 |

**Trigger gây KYA cho giao dịch lành tính (nguồn báo nhầm chính, dùng để hiệu chỉnh chính sách):** DORMANT_WAKE=38, AMOUNT_OVER_KYA=29, FIRST_ONLINE=25

Chưa gồm LLM Critic (chỉ nâng mức) và Hard Policy (chặn cứng theo hạn mức).


## Mô hình AI bổ sung (dữ liệu TỔNG HỢP)
| Mô hình | AUC | AP | Ghi chú |
|---|---|---|---|
| Bot–người (Tầng 1) | 0.9914 | 0.9896 | recall tại FPR 1% = 0.857; ngưỡng 0,85: bắt 0.831, gắn nhầm người 0.0059 |
| Boosting giám sát – PAY | 0.9971 | 0.9957 | ngưỡng 0,85: cảnh báo 0.2071, precision 1.0, FPR 0.0 |
| Boosting giám sát – FX | 0.9396 | 0.9214 | ngưỡng 0,85: cảnh báo 0.1548, recall 0.814 |

Nhãn do chính bộ sinh dữ liệu gắn → số liệu mang tính vòng tròn; không phải bằng chứng hiệu quả thực.
