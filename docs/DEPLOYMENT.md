# Triển khai

## Hồ sơ triển khai (DEPLOY_PROFILE)
| Hồ sơ | Dùng cho | Khác biệt chính |
|---|---|---|
| `demo` | Trình diễn nội bộ | Dữ liệu mô phỏng; không bắt buộc telemetry/nonce; Anti-Bot fail-open (có ghi nhận) |
| `pilot` | Chạy thử có kiểm soát | Bắt buộc telemetry kênh trực tuyến; fail-closed; readiness chỉ cảnh báo |
| `production` | Vận hành thật | Bắt buộc nonce; ngưỡng dò thẻ chặt hơn; **ứng dụng từ chối khởi động nếu còn BLOCKER** |

Kiểm tra bất kỳ lúc nào: `GET /api/agent/hq/readiness` (vai trò HQ) hoặc `python -c "from agentmon import profiles;print(profiles.readiness())"`.
Cấu hình cũ `PRICING_ENVIRONMENT=production` được hiểu là **pilot**; muốn hồ sơ production phải đặt rõ `DEPLOY_PROFILE=production`.

## Gói đã có
`Dockerfile` (non-root, gunicorn, healthcheck TCP), `docker-compose.yml` (web + Redis + volume), `render.yaml` (demo), `Procfile`, `.env.example`, `Makefile`, `.github/workflows/ci.yml`.

## Docker (khuyến nghị cho pilot)
```bash
cp .env.example .env        # điền SECRET_KEY, API_SIGNING_SECRET, CARD_VAULT_KEY (ngẫu nhiên ≥ 32 ký tự), DEMO_PASSWORD nếu demo
docker compose up --build   # http://localhost:5000
```
Dữ liệu (`data/`), log (`logs/`), mô hình (`models/`) nằm trong volume; sao lưu `data/` và `models/MANIFEST.json` + `models/archive/`.

## Render (chỉ demo)
`render.yaml` dùng store trong RAM và 1 worker; đĩa tạm thời nên dữ liệu mất khi khởi động lại. Không dùng cho production.

## On-premise
`gunicorn app:app -b 127.0.0.1:5000 -w 2` sau nginx (HTTPS, `TRUSTED_PROXY=1`), Redis bắt buộc khi > 1 worker. Chạy bằng systemd; thư mục dữ liệu chỉ tài khoản dịch vụ được ghi.

## Điều kiện để lên production (chưa có trong gói)
| Hạng mục | Hiện trạng | Việc cần làm |
|---|---|---|
| CSDL | SQLite (WAL) | PostgreSQL/Oracle; khóa đồng thời liên máy bằng advisory lock theo `customer_id` |
| Dữ liệu khách/thẻ | `mock_db`, vault thẻ thử nghiệm | Tích hợp core banking, CIF, switch thẻ, HSM/KMS cho `CARD_VAULT_KEY` |
| Mô hình | Huấn luyện trên dữ liệu tổng hợp | Huấn luyện/kiểm chứng trên dữ liệu thật (`DATA_REQUIREMENTS.md`) |
| Kiểm thử | 100+ test đơn vị/tích hợp | Test tải, pentest độc lập, DR/backup, giám sát (metrics/alert) |
| Quy trình | — | Phê duyệt thay đổi mô hình, quản trị ngưỡng, đánh giá định kỳ |

`tools/security_smoke.py` (45 kiểm tra) được tài liệu vận hành cũ nhắc tới **không có trong gói đã nhận**; hiện kiểm thử bảo mật tự động nằm ở `tests/` và `tools/attack_matrix.py`.
