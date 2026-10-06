# AnyRouter 模型状态

每 15 分钟实际调用截图中的 17 个模型，记录 API 可用性、请求总耗时与 token 用量，使用 GitHub Actions + GitHub Pages 免费托管。

**这不是 AnyRouter 官方状态页。** 结果只代表你的密钥从探测节点调用时的体验，不验证模型身份。模型 ID 原样来自截图。已从 GitHub 运行器完成全部 17 个模型的首轮鉴权调用，Haiku 4.5 返回有效回复；其他模型的失败和限制同样保留在历史中，实时结果以状态页为准。

## 部署

仓库：<https://github.com/tonywang1201/anyrouter-healthcheck>

状态页：<https://tonywang1201.github.io/anyrouter-healthcheck/>。

1. 在仓库 **Settings → Secrets and variables → Actions → New repository secret** 中添加 `ANYROUTER_API_KEY`。建议使用单独的探测密钥，并在 AnyRouter 后台设置可接受的额度限制。不要把密钥放在配置文件、代码、网页或聊天中。
2. 在 **Settings → Pages → Source** 选择 **GitHub Actions**。
3. 在 **Actions → Monitor and publish → Run workflow** 中先填写一个模型 ID，确认接口协议、权限和回复可用；再留空运行全部模型。
4. 此后在每小时第 13、28、43、58 分钟自动探测，避开整点高峰。修改 `interval_minutes` 时也应修改工作流的 cron 表达式。Actions 中自动检测显示为 **Scheduled model probe**；手动检测显示为 **Manual model probe**；代码发布显示为 **Publish code changes**。

代码发布到 `main`；探测数据自动保存到 `monitor-data`。机器人写入数据后直接部署 Pages，避免依赖机器人提交再次触发工作流。没有密钥时，代码 push 仍可部署页面；手动或定时探测则明确失败，避免出现任务成功但没有新数据的情况。不会生成假成功记录。代码 push 只发布页面，不自动消耗 API 额度。

需要 `contents: write` 将数据保存到 `monitor-data`，以及 `pages: write` / `id-token: write` 部署 Pages。如果你的账户或组织禁止这些权限，需要调整相应仓库策略。标准运行器在公开仓库免费，私有仓库有免费分钟额度；使用默认 `github.io` 域名无需购买域名。

GitHub 定时任务可能延迟或漏跑；公开仓库连续 60 天没有活动时可能自动停用。页面展示最后检测时间，并在记录超过 30 分钟后将当前状态改为“未知”。日常有数据提交时仓库保持活动；如果长期没有密钥或检测工作流失败，请检查 Actions 是否启用。GitHub-hosted runners 的区域和网络出口不保证固定。

如果仓库长期没有任何 `schedule` 事件，先检查默认分支、工作流启用状态和 Actions 策略；仅有手动运行成功不能证明定时已恢复。需要绕过 GitHub 定时触发时，可使用 [Cloudflare 备用定时器](scheduler/README.md)，默认关闭且尚未部署。

## 调整模型和协议

编辑 `config/models.json`。仅监测配置中列出的模型，不自动扫描或增加模型。

| `protocol` | 默认端点 | 回复校验 | 输出限制 |
| --- | --- | --- | --- |
| `messages` | `/v1/messages` | `type: message`、assistant 角色、非空 text 内容 | `max_tokens` |
| `responses` | `/v1/responses` | `status: completed`、非空 message/output_text | `max_output_tokens` |
| `chat_completions` | `/v1/chat/completions` | assistant 角色、非空 message 内容 | `max_completion_tokens` 或 `max_tokens` |

各模型可以覆盖 `base_url`（HTTPS origin）、`path`、`auth`（`bearer` 或 `x-api-key`）、`api_key_env`、`parameters`。Messages 默认使用 Bearer 令牌，同时携带 `anthropic-version: 2023-06-01`；如果后台示例要求 `x-api-key`，请修改对应模型的 `auth`。

[AnyRouter 使用指南](https://docs.anyrouter.top/)主要面向 Claude Code；普通 API 请求不一定对所有列出的模型开放。服务明确要求特定客户端时，记录“客户端受限”，不冒充该客户端。HTTP 400/422 只表示请求被拒绝，可能涉及模型、客户端或参数，不能仅凭状态码确定是参数错误。

示例：

```json
{
  "id": "claude-haiku-4-5-20251001",
  "provider": "Anthropic",
  "protocol": "messages",
  "path": "/v1/messages",
  "auth": "bearer",
  "parameters": {"max_tokens": 32}
}
```

`base_url` 不带 `/v1`，完整端点使用 `path` 设置。`parameters` 可增加接口支持的推理参数，但不能覆盖模型名、输入消息和 `stream`。始终使用非流式请求。配置必须有 1–8192 的输出 token 上限，不会自动重试或切换协议，避免额外调用消耗和把错误掩盖成成功。

GPT 和 Gemini 的默认输出预算为 1024，给推理 token 留出空间；仍可能因推理耗尽预算而判为“生成未完成”。请依据 AnyRouter 的实际参数支持和实测结果调整，而不是把所有模型都限制为 1–2 tokens。Responses 不完整但有部分文本的回复也不会标为成功。

默认并发 2，每个请求的网络期限 60 秒，回复体上限 128KB。不跟随 HTTP 重定向，不转发密钥到其他站点。网络 DNS 解析受系统解析器影响；GitHub 作业同时设置 20 分钟总超时。

如使用多个密钥，请在工作流 Probe models 步骤的 `env` 下添加对应的 `secrets` 映射；默认工作流只映射 `ANYROUTER_API_KEY`。

## 本地运行

检测器仅使用 Python 3.12 标准库；网页仅使用原生 JavaScript / SVG，不依赖 CDN、npm 安装或第三方图表服务。Node 24 用于前端逻辑测试。

```powershell
python -m healthcheck validate
python -m unittest discover -s tests -v
node --test tests/status.test.mjs

# 无 API 消耗的演示，明确标识为演示数据，不写入真实 data 目录
python -m healthcheck demo
python -m http.server 8765 --bind 127.0.0.1 --directory .preview
```

打开 <http://127.0.0.1:8765/> 查看演示。生成真实页面：

```powershell
python -m healthcheck build
python -m http.server 8766 --bind 127.0.0.1 --directory site
```

探测前请通过本机的凭据管理或终端设置环境变量 `ANYROUTER_API_KEY`。不要将真实密钥写进命令历史或项目文件。程序不会自动读取 `.env`。

```powershell
# 环境变量配置好后，先测试一个模型
python -m healthcheck check --model claude-haiku-4-5-20251001
python -m healthcheck build

# 调用全部模型
python -m healthcheck check
python -m healthcheck build
```

参数：`--config` 指定模型配置，`--data-dir` 指定记录目录，`--output` 指定生成页面目录；`--model` 可以重复传入。缺少所有需要的密钥时检测命令退出失败，不改变历史。如果只有部分模型没有相应密钥，其他模型照常探测，缺少密钥的模型记录为“未知”。

## 口径、历史与公开数据

- **可用**：HTTP 2xx 且协议有效、有非空生成文本；不要求回复精确等于 OK。
- **失败**：超时、网络错误、5xx、接口/模型不存在、请求不兼容、空回复、非 JSON、回复结构异常或 Responses 未完成。
- **账号受限**：401、JSON 403、429、402 或明确的余额/密钥错误。HTML 403 单独归为访问/WAF 错误。分类反映请求表现，无法确定限流发生在用户账户、网关还是上游。
- **未知**：没有检测、检测器错误、未配置密钥，或距最近一条记录超过 30 分钟。页面每 30 秒重新判断记录是否过期，每 5 分钟刷新数据。
- **采样成功率**：成功数 / 已完成调用数，含账号受限，排除未知。未采样不进入分母，也不算成功。
- **采样覆盖率**：从该模型开始检测以来，应采样的 15 分钟时段中取得已完成调用记录的时段比例。同一时段手动重跑只算一次覆盖。
- **P50 / P95**：仅统计成功请求的总耗时；不是首 token 时间。图表保留失败点，成功曲线在失败和缺失采样之间断开。

每天按 UTC 日期保存一份记录，页面显示香港时间。保留包含今天在内最近 90 个 UTC 日期的明细，更早的 JSON 明细转换为每日汇总；Git 历史仍保留以前提交的记录，归档不等于从 Git 中删除。每日汇总保存成功/失败/受限/未知次数、成功延迟总和与数量、token 用量累加。

公开文件：

- `data/status.json`：17 个模型的最近结果、24h/7d/30d 统计、检测时间和历史文件清单。
- `data/history/YYYY-MM-DD.json`：逐次检测结果。
- `data/daily.json`：每日汇总下载。

只公开固定类别、时间、模型 ID、HTTP 状态、耗时和数值 token 字段。密钥、请求头、提示词、生成文本、原始错误文本不进入历史或检测日志。`site/` 和 `.preview/` 为忽略的构建目录，生产部署只上传 `site/`。

17 个模型每 15 分钟探测，计划约 **1,632 次/天、48,960 次/30 天**。手动探测额外计数；实际费用按 AnyRouter 计费，思考 token 和最低收费规则也可能影响消耗。

参考：[GitHub Actions 计费](https://docs.github.com/en/billing/concepts/product-billing/github-actions)、[定时工作流限制](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows)、[Pages 部署](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages)。
