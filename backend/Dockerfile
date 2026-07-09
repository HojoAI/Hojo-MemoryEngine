# 已迁移至仓库根目录 Dockerfile（uv + bookworm）
# 构建：cd .. && docker build -t memory-engine-api:latest -f Dockerfile .
FROM python:3.12-slim-bookworm
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
RUN pip install uv && uv sync --no-dev
COPY src ./src
ENV PATH="/app/.venv/bin:$PATH" PYTHONPATH=/app/src
EXPOSE 6030
CMD ["uvicorn", "memory_engine.main:app", "--host", "0.0.0.0", "--port", "6030"]
