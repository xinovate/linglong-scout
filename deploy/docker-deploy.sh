#!/usr/bin/env bash
# Linglong Scout — Docker 部署参考
# 在服务器上手动执行，替换 systemd 部署
#
# 前置：SearXNG / RSSHub / Redis / Cloudflare Tunnel 已在主机运行

set -euo pipefail

INSTALL_DIR="/opt/linglong-scout"
REPO_URL="https://github.com/xinovate/linglong-scout.git"

echo "=== 1. 拉取代码 ==="
if [ -d "$INSTALL_DIR" ]; then
    cd "$INSTALL_DIR"
    git pull
else
    git clone "$REPO_URL" "$INSTALL_DIR"
    cd "$INSTALL_DIR"
fi

echo "=== 2. 放置配置文件 ==="
if [ ! -f .scout.yml ]; then
    echo "ERROR: 请先创建 .scout.yml（参考 deploy/.scout.yml.example）"
    exit 1
fi
if [ ! -f .env ]; then
    echo "ERROR: 请先创建 .env（参考 deploy/.env.example）"
    exit 1
fi

echo "=== 3. 构建镜像 ==="
docker compose build

echo "=== 4. 停止旧服务 ==="
systemctl stop linglong-mcp 2>/dev/null || true
systemctl disable linglong-mcp 2>/dev/null || true

echo "=== 5. 启动容器 ==="
docker compose up -d

echo "=== 6. 验证 ==="
sleep 3
docker compose ps
echo ""
echo "--- Health check ---"
curl -s -o /dev/null -w "HTTP %{http_code}\n" http://127.0.0.1:9900/mcp/scout --connect-timeout 5

echo ""
echo "=== 部署完成 ==="
echo "Cloudflare Tunnel 应自动连接到 127.0.0.1:9900"
echo "日志：docker compose logs -f"
