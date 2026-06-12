FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml .
COPY src/ src/

RUN pip install --no-cache-dir -i https://mirrors.aliyun.com/pypi/simple/ .

EXPOSE 9900

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:9900/health')" || exit 1

CMD ["python", "-m", "linglong.mcp"]
