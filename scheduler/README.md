# 可选 Cloudflare 备用定时器

默认关闭，尚未部署。仅在 GitHub 原生 `schedule` 长期不触发时使用。

每 15 分钟检查公开状态；全部 17 个模型在最近 12 分钟内已有记录时跳过，GitHub 检测仍在运行或排队时也跳过。否则调用 GitHub 的 `workflow_dispatch`。推理、历史和 Pages 仍在 GitHub，AnyRouter 密钥不离开仓库 Secrets。HTTP 入口始终返回 404，不能用公开 URL 消耗模型额度。

接入步骤：

1. 用户登录 Cloudflare，使用 Workers Free。创建 `anyrouter-monitor-timer`，上传 `worker.mjs` 或使用官方 Wrangler 部署此目录。
2. 用户在 GitHub 创建有到期日的 fine-grained token，只选择 `anyrouter-healthcheck` 仓库，授予 **Actions: Read and write**。该权限能触发及管理此仓库 Actions，不仅限于某个工作流；不需要 Contents 写入或 Secrets 读取权限。
3. 用户将令牌直接保存到 Worker Secret `GITHUB_ACTIONS_TOKEN`。不要发到聊天、写进代码、配置或日志。配置 `DISPATCH_ENABLED=true` 才开始触发。
4. 配置 UTC cron `0,15,30,45 * * * *`（香港时间分钟相同）。Cloudflare Cron 配置可能需要最多 15 分钟传播。
5. 从 Cloudflare 日志确认 `dispatched`，在 GitHub 确认检测和部署成功，再验证下一轮 Cron。稳定后移除 GitHub 原生 cron，使用单一定时器，避免两个平台同时启动检测。手动运行仍可使用。

它只触发检测，不能保证 GitHub 执行器或 AnyRouter 可用。页面仍保留 30 分钟过期判断。令牌到期/权限不足会明确失败，需要用户更新 Secret。

测试（不调用网络）：`node --test tests/scheduler.test.mjs`。

参考：[Cloudflare Cron](https://developers.cloudflare.com/workers/configuration/cron-triggers/)、[GitHub workflow dispatch 权限](https://docs.github.com/en/rest/actions/workflows#create-a-workflow-dispatch-event)。
