# Giải trình quyết định (audit trail)

Mỗi quyết định lưu trong bảng `actions`:
* Cột tra cứu nhanh: `anomaly, behavior, velocity, final_risk, decision, status, hard_reason, reasons, triggers, reason_public, llm,
  fraud_class, fraud_types, model_version, trace_hash, channel_type, device_id`.
* `details.trace` (JSON, schema `decision-trace/1`) – đủ để **tái lập** quyết định:

| Khối | Nội dung |
|---|---|
| `model` | domain, `version`, `sha256` file mô hình, thời điểm huấn luyện, số mẫu, nguồn dữ liệu, `used_for_this_decision` |
| `scoring` | trọng số (`ml 0,40 / hành vi 0,30 / velocity 0,30`; `blend 0,70 mean + 0,30 max`), ngưỡng KYA/REVIEW/BLOCK **tại thời điểm đó**, thành phần điểm |
| `features` | vector đặc trưng đã đưa vào mô hình |
| `baseline` | số giao dịch lịch sử, trung bình, độ lệch, tỷ lệ, z-score, baseline mỏng hay không |
| `limits_effective`, `policy_global` | hạn mức hiệu lực MIN(TSC, Chi nhánh, Agent) và danh mục MCC/quốc gia |
| `hard_violations`, `triggers`, `decision_path` | vi phạm chặn cứng, trigger KYA, từng bước dẫn tới quyết định (kể cả LLM nâng mức, fail-closed) |
| `llm` | cấu hình, có gọi hay không, khuyến nghị |
| `fraud` | phân loại (`FRAUD_SUSPECTED / ANOMALY_UNCONFIRMED / NORMAL`) + loại gian lận kèm bằng chứng |
| `context` | số dư khả dụng, suspicion, watchlist, probation, số lệnh 24h, `cross_domain_n5` |

`trace_hash` = SHA-256 của trace chuẩn hóa. `GET /api/agent/actions/<id>/explain` (nhân viên/TSC; **không** cho khách) trả trace và tính lại hash → `integrity_ok`.
Không lưu PAN/CVV (đã che trước khi chấm điểm). Khách chỉ thấy `reason_public`.

**Tái lập chính xác bản mô hình cũ:** đặt `AGENTMON_MODEL_ARCHIVE=1` để mỗi lần huấn luyện lưu `models/archive/<version>.joblib`; đối chiếu `sha256` trong trace/MANIFEST.
**Giới hạn:** bản ghi cũ (dữ liệu mẫu/trước v1.1) không có trace; `fraud_*` là phân loại dựa trên luật, chưa hiệu chỉnh trên nhãn thật (`docs/FRAUD_TAXONOMY.md`).
