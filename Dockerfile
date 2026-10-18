# syntax=docker/dockerfile:1

# ---------- 阶段 1：构建前端 ----------
FROM node:20-alpine AS web
WORKDIR /web
ARG NPM_REGISTRY=https://registry.npmjs.org
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --registry=$NPM_REGISTRY --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---------- 阶段 2：运行后端 ----------
FROM python:3.12-slim
WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HUB_DISABLE_XET=1

# 国内构建可传：--build-arg PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
ARG PIP_INDEX_URL=https://pypi.org/simple
COPY requirements.txt .
RUN pip install --index-url $PIP_INDEX_URL -r requirements.txt

COPY app ./app
COPY mcp_servers ./mcp_servers
COPY mcp_servers.json ./
COPY samples ./samples
COPY --from=web /web/dist ./frontend/dist

EXPOSE 8000
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
