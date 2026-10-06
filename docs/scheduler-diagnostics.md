# 定时监测排障记录（2026-10-06）

观测时间：15:46 UTC / 香港时间 23:46。此记录描述现象，不断言 GitHub 内部的具体故障原因。

- 公开仓库：`tonywang1201/anyrouter-healthcheck`，创建于 `2026-10-06T12:41:12Z`，非 fork、未归档，默认分支 `main`。
- 工作流：`.github/workflows/monitor.yml`，ID `376407062`，公开 API 返回 `state: active`。
- Actions 允许所有 Actions；没有 Actions 事件策略。Pages 来源为 GitHub Actions。手动运行已验证仓库 Secret、数据写入和 Pages 发布权限有效。
- 默认分支中的原始 cron 为 `7,22,37,52 * * * *`；创建后一直没有 `schedule` 运行。
- 约 15:26 UTC 在网页禁用后重新启用工作流，并提交 `2f98b62`，将 cron 改为 `13,28,43,58 * * * *`。
- 此后预期时间包括 15:28 UTC、15:43 UTC。截至观测时间，UI 和公开 API 中仍没有任何 `schedule` 事件运行；没有可检查的定时失败日志。
- [手动检测 #12](https://github.com/tonywang1201/anyrouter-healthcheck/actions/runs/37488073169)（`workflow_dispatch`）成功；模型数据最后检测时间为 `2026-10-06T15:31:24Z`。
- [代码发布 #13](https://github.com/tonywang1201/anyrouter-healthcheck/actions/runs/37489333668)（`push`）成功；当前代码 `6b00285`。15 个 Python 测试、8 个页面逻辑测试、5 个备用定时器测试通过。

可匿名读取的证据接口：

```text
GET https://api.github.com/repos/tonywang1201/anyrouter-healthcheck/actions/workflows/monitor.yml
GET https://api.github.com/repos/tonywang1201/anyrouter-healthcheck/actions/workflows/monitor.yml/runs?event=schedule&per_page=3
```

第二个接口在观测时返回 `total_count: 0`、`workflow_runs: []`。也可查看[只筛选定时事件的执行列表](https://github.com/tonywang1201/anyrouter-healthcheck/actions/workflows/monitor.yml?query=event%3Aschedule)。

没有扩大仓库默认权限，也没有通过延长页面记录有效期掩盖中断。页面仍在 30 分钟没有新记录后显示未知，并说明数据已过期。Cloudflare 备用定时器的代码已准备好，默认关闭且尚未部署。

GitHub 官方说明定时事件可能延迟或丢弃；手动检测成功不能证明定时事件已送达。若持续没有新事件，可将以上公开证据提供给 GitHub Support/Community，或接入独立定时器。此报告尚未发送给任何人，不含凭据及 API 原始响应。

参考：[GitHub 工作流排障](https://docs.github.com/en/actions/how-tos/troubleshoot-workflows#scheduled-workflows-running-at-unexpected-times)、[schedule 事件](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)。
