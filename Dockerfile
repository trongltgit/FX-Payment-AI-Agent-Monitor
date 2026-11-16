FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
# Người dùng không phải root; thư mục dữ liệu/log/mô hình ghi được
RUN useradd -r -u 10001 app && mkdir -p /app/data /app/logs /app/models && chown -R app:app /app
USER app
ENV PORT=5000 WEB_CONCURRENCY=2 AGENTMON_DB=/app/data/agentmon.db AGENTMON_MODEL_DIR=/app/models
EXPOSE 5000
# Kiểm tra TCP (không gọi HTTP để không kích hoạt bộ lọc bot/ban IP của chính ứng dụng)
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
  CMD python -c "import socket,os;socket.create_connection(('127.0.0.1',int(os.environ.get('PORT','5000'))),3).close()"
CMD ["sh", "-c", "gunicorn app:app -b 0.0.0.0:${PORT} -w ${WEB_CONCURRENCY} --timeout 60 --access-logfile -"]
