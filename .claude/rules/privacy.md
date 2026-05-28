# 隐私规约

## 核心规则

文档、代码、配置中禁止出现真实私人信息和基础设施细节。

## 禁止内容

- 服务器 IP 地址、内网域名
- 生产域名、SSL 证书路径
- API Key、Token、密码（含占位示例）
- 第三方服务端口映射（如 `SearXNG:8088`、`RSSHub:1200`）
- LLM 提供商名称、API 端点、模型名（除非为通用占位符）
- 个人路径、用户名、主机名

## 允许的替代写法

| 禁止 | 替代 |
|------|------|
| `redacted-server-ip` | `localhost` 或 `your-server-ip` |
| `redacted-domain` | `your-domain.example.com` |
| `https://open.bigmodel.cn/api/anthropic` | `https://api.example.com/v1` |
| `glm-5.1` | `gpt-4o` 或通用模型名 |
| 真实 API Key | 环境变量引用 `${VAR_NAME}` 或 `your-secret-key` |

## 适用范围

- 源码默认值：用 `localhost` / `None`，真实值走 `.scout.yml` 或环境变量
- 配置模板（`.scout.example.yml`、`deploy/.env.example`）：用通用占位符
- 测试文件：用 `localhost` / `example.com`
- 文档和日志：用描述性文字替代具体值（"服务器上" 而非 "redacted-server-ip 上"）
- 部署配置模板：域名和路径用 `your-*` 占位符

## 检查时机

- 新增文件时检查是否包含私人信息
- 复制外部配置到仓库时脱敏
- 写日志时避免记录具体基础设施细节
