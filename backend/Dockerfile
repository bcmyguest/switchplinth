FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_CACHE_DIR=/tmp/uv-cache
WORKDIR /app
COPY pyproject.toml README.md uv.lock* ./
RUN pip install --no-cache-dir uv && uv sync --no-dev --no-install-project
COPY src ./src
RUN uv sync --no-dev
EXPOSE 8000
CMD ["uv", "run", "switchplinth"]
