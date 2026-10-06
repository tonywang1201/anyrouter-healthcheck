# 定时监测排障记录（2026-10-06–07）

首轮观测时间：2026-10-06 15:46 UTC / 香港时间 23:46。此记录描述现象，不断言 GitHub 内部的具体故障原因。

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

## 后续原生调度排查

- 15:49 UTC 提交 `f421498`：将模型工作流重新注册为 `probe.yml`，新 ID `376577663`，状态 `active`，cron 为 `8,23,38,53 * * * *`。原权限与检测代码保留。
- 15:53 UTC 提交 `84a6315`：增加不使用密钥、不调用模型的最小 `cron-diagnostic.yml`，ID `376581041`，状态 `active`；每 5 分钟运行一次，用于观察 `schedule` 事件是否送达。
- [最小诊断手动运行](https://github.com/tonywang1201/anyrouter-healthcheck/actions/runs/37491431849)于 15:54 UTC 成功；截至 15:58 UTC，整个仓库仍没有任何 `schedule` 事件。
- 公开提交 API 确认 cron 修改提交的作者和提交者均关联到仓库拥有者 `tonywang1201`。
- 约 16:01–16:03 UTC（香港时间次日 00:01–00:03）通过指向同一提交的临时分支切换并还原默认分支，尝试刷新定时分支/账号绑定。已确认默认分支恢复 `main`，临时分支已删除。
- [新工作流全模型手动验证](https://github.com/tonywang1201/anyrouter-healthcheck/actions/runs/37492828693)于 16:04 UTC 启动，不能代替自动调度验收。
- 上述全模型手动验证成功，最后模型检测时间为 `2026-10-06T16:05:06.744Z` / 香港时间 `2026-10-07 00:05:06`。
- 16:11 UTC 提交 `37f056c`：最小诊断工作流改为标准表达式 `*/5 * * * *`，排除逗号分钟列表的可能影响。
- **2026-10-06 19:01:36 UTC / 香港时间 2026-10-07 03:01:36 再次检查：整个仓库 `schedule` 运行总数仍为 0。** 最小诊断与真实探测两个已启用工作流均没有收到定时事件。最新手动检测已接近 3 小时，不能将这种持续中断描述为已经修复。
- 同时直接读取线上 `data/status.json`，其 `last_run_at` 仍为 `2026-10-06T16:05:06.744Z`，`generated_at` 为 `2026-10-06T16:11:22.94Z`。这说明已发布数据没有新的采样，不只是浏览器未刷新。

## 当前结论与下一步

故障位置已缩小到定时事件未创建运行这一阶段。检测脚本、密钥与 Pages 发布在手动运行中有效；仓库设置、默认分支、工作流启用状态、合法 cron、最小诊断、重新注册与默认分支重置均已核对，仍没有定时事件。没有证据证明某个模型调用或页面缓存造成此现象，也不能从公开证据确定 GitHub 内部的具体原因。

按用户选择继续只使用 GitHub。保留原生定时和最小诊断；下一项验收必须是真正的 `schedule` 运行成功并产生新模型时间，手动运行和代码发布不算恢复。可将本报告及两个工作流链接提交给 GitHub Support/Community，请其检查仓库定时事件注册与投递。报告尚未发送。

页面另外增加可见的数据同步时间，并在标签页恢复可见时立即读取数据；同步时间不会覆盖真实检测时间，过期规则仍为 30 分钟。

当前定时事件核对接口（覆盖新旧工作流及最小诊断）：

```text
GET https://api.github.com/repos/tonywang1201/anyrouter-healthcheck/actions/runs?event=schedule&per_page=3
```

没有扩大仓库默认权限，也没有通过延长页面记录有效期掩盖中断。页面仍在 30 分钟没有新记录后显示未知，并说明数据已过期。Cloudflare 备用定时器的代码已准备好，默认关闭且尚未部署。

GitHub 官方说明定时事件可能延迟或丢弃；手动检测成功不能证明定时事件已送达。若持续没有新事件，可将以上公开证据提供给 GitHub Support/Community，或接入独立定时器。此报告尚未发送给任何人，不含凭据及 API 原始响应。

参考：[GitHub 工作流排障](https://docs.github.com/en/actions/how-tos/troubleshoot-workflows#scheduled-workflows-running-at-unexpected-times)、[schedule 事件](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)。
