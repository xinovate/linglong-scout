---
description: 安全要求 — 认证、密钥管理、输入校验、SSRF 防护、恒定时间比较
globs:
  - "**/*.py"
---

# 安全要求

## ⭐ 安全特性必须"形似且神似"（高频盲区）

AI 写安全代码的典型缺陷：**防护看起来在，实际可绕过**。下列每条都是强制检查项，python-reviewer 必查。

## 认证

### Token 比较 — 恒定时间

- 所有 token / 密钥 / 密码比较**必须用 `secrets.compare_digest(a, b)`**
- **禁止用 `==` 比较** —— 时序攻击可逐字节爆破
- Redis 侧比较（`r.exists(token)`）OK，Redis 内部是恒定时间

```python
import secrets

# 错
return token == self._static_token

# 对
return secrets.compare_digest(token, self._static_token)
```

### Token 存储

- Token 在 Redis 存为 hash 含 `issued_at` / `last_used` / `expires_at`，不要只存字符串 `"active"`
- 必须有 TTL 或可吊销机制，泄漏的 token 不能永久有效
- 自动生成的 token **禁止明文打印到日志** —— 写到 `0600` 权限文件或要求交互式初始化

## 密钥管理

- 所有第三方服务密钥（LLM、DB、API）从环境变量或密钥管理服务加载
- 禁止在源码中硬编码密钥
- `.env`、凭据文件、密钥文件必须 gitignore
- 日志中 URL 的查询参数脱敏 key/token 字段

## 输入校验

- 系统边界（HTTP 请求、MCP 工具参数、外部 API 响应）必须校验
- 校验规则：类型正确、范围合理、长度限制
- URL 参数过滤：只允许 `https://`，禁止 `file://`、`javascript:` 等危险协议
- 文件名过滤 `..`、`/`、`\`，禁止路径穿越
- 内部函数之间信任调用，不重复校验

## ⭐ SSRF 防护 — 必须 DNS 解析后校验（高频盲区）

只查字面 host 字符串的 SSRF 校验**形似神不似**，可被 DNS rebinding 绕过。

```python
import ipaddress
import socket

def is_safe_url(url: str) -> bool:
    """Reject private/internal IPs AFTER DNS resolution."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return False
    # 必须解析 DNS，不能只查字面 host
    try:
        infos = socket.getaddrinfo(parsed.hostname, None)
    except socket.gaierror:
        return False
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            return False
    return True
```

- 必须覆盖：私有段（10/8、172.16/12、192.168/16）、loopback（127/8）、link-local（169.254/16）、metadata（169.254.169.254）、IPv6 ULA（fc00::/7）、IPv6 link-local（fe80::/10）
- `allow_internal` 逃生舱只限管理员配置的受信源，必须显式传参

## 网络安全

- 所有外部 HTTP 调用必须设置超时（连接超时 + 读取超时）
- 禁止关闭 SSL 证书验证（`verify=False`），即使测试环境
- 服务对外：绑定 `127.0.0.1`，外部通过反代/Tunnel 访问

## 敏感数据

- 错误响应不暴露内部路径、堆栈、服务器版本信息
- 临时文件用 `tempfile` 模块创建，不手动拼接 `/tmp/`
