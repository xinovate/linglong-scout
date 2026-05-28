# 安全要求

## 认证

- MCP 远程端点：Token 认证，通过 `TokenAuthMiddleware` 实现
- Token 来源：Redis 优先，静态降级。格式：`linglong-<模块>-<随机串>`
- Redis 存储：key = token 值，value = `"active"`，无 TTL
- Token 和 API Key 禁止提交到 git，使用环境变量或 Redis

## API Key 管理

- 所有第三方服务密钥（智谱、SearXNG、RSSHub、Embedding）从环境变量加载
- systemd 服务文件用 `Environment=` 指令，不在 Python 源码中硬编码
- 本地开发：密钥可放 `.scout.yml`（已 gitignore）或环境变量
- 密钥轮换：Redis 中的 Token 支持写入新值后删除旧值，无停机切换

## 输入校验

- 系统边界（HTTP 请求、MCP 工具参数、外部 API 响应）必须校验
- 校验规则：类型正确、范围合理、长度限制
- URL 参数过滤：只允许 `https://` 协议，禁止 `file://`、`javascript:` 等危险协议
- 内部函数之间信任调用，不重复校验

## 网络安全

- SearXNG：nginx 反向代理 + API Key 校验
- RSSHub：`ACCESS_KEY` 参数保护
- MCP 服务：绑定 `127.0.0.1`，外部通过 nginx 反代或 Cloudflare Tunnel 访问
- 所有外部 HTTP 调用必须设置超时（连接超时 + 读取超时）
- 禁止关闭 SSL 证书验证（`verify=False`），即使测试环境

## 敏感数据

- 禁止在日志中记录 API Key、Token、用户凭据
- `.env`、凭据文件、密钥文件禁止提交到 git
- 日志中涉及 URL 时脱敏查询参数中的 key/token 字段
- 错误响应不暴露内部路径、堆栈、服务器版本信息

## 依赖安全

- 定期运行 `pip audit` 或 `safety check` 检查已知漏洞
- 锁定依赖版本（`requirements.txt` 或 `pyproject.toml` 指定下界）
- 新增第三方依赖前评估：维护状态、下载量、已知 CVE

## Cloudflare Tunnel

- 远程 MCP 使用 Cloudflare Tunnel（出站连接），无需开放入站端口
- SSL 在 Cloudflare 终止，Tunnel → 本地服务走 HTTP localhost
- 部署细节见 `docs/operations.md`

## 文件系统

- 文件操作限制在项目目录内，禁止路径穿越（`../../../etc/passwd`）
- 用户提供的文件名过滤 `..`、`/`、`\` 等危险字符
- 临时文件用 `tempfile` 模块创建，不手动拼接 `/tmp/` 路径
