# GitHub Community / Support 投稿草稿（尚未发送）

以下为拟提交的完整英文标题和正文。只有经仓库拥有者明确授权，才会对外发布。正文仅包含公开仓库和执行记录，无密钥、令牌、模型原始回复或私有账号资料。

## Title

New public repository: schedule creates zero runs while workflow_dispatch and push succeed

## Body

Repository: https://github.com/tonywang1201/anyrouter-healthcheck

The repository was created on 2026-10-06 at 12:41 UTC. It is public, not a fork, not archived, and its default branch is `main`.

Both scheduled workflows are on `main` and have API state `active`:

- Model probe: https://github.com/tonywang1201/anyrouter-healthcheck/blob/main/.github/workflows/probe.yml
- Minimal diagnostic: https://github.com/tonywang1201/anyrouter-healthcheck/blob/main/.github/workflows/cron-diagnostic.yml

The minimal diagnostic uses `*/5 * * * *` and only prints the event name and UTC time. It does not check out code, access secrets, call the model API, or use job conditions or a concurrency group.

The model probe is scheduled at minutes 8, 23, 38, and 53 each hour. Its cron was initially a minute list and has now been resubmitted as four separate hourly entries without increasing its frequency.

As of 2026-10-06 19:15 UTC, the repository-wide endpoint below returned `total_count: 0` and an empty `workflow_runs` array:

https://api.github.com/repos/tonywang1201/anyrouter-healthcheck/actions/runs?event=schedule&per_page=5

Manual dispatch and push work:

- Minimal diagnostic, manual success: https://github.com/tonywang1201/anyrouter-healthcheck/actions/runs/37517265728
- Full model probe and Pages deployment, manual success: https://github.com/tonywang1201/anyrouter-healthcheck/actions/runs/37517271140
- Code publication success: https://github.com/tonywang1201/anyrouter-healthcheck/actions/runs/37516082473

Checks and attempted repairs:

- Actions are enabled, all actions are allowed, and there are no repository Actions event policies in the UI.
- The account authenticated for these repairs is the repository owner. Cron-changing commits map to that same account.
- We changed the cron, disabled/re-enabled workflows, and renamed the original probe file to register a new workflow ID.
- We temporarily changed the default branch to another branch at the same commit and restored `main`; the temporary branch has been deleted.
- At approximately 19:12 UTC we disabled and re-enabled repository Actions through the REST API, restored its original permissions, and disabled/re-enabled both scheduled workflows. The manual validations linked above were run after this reset.
- At approximately 19:14 UTC the repository owner resubmitted the model cron using the contents API: https://github.com/tonywang1201/anyrouter-healthcheck/commit/601d4c591c7d965cd76bc733ec462f5e7f354eb6

We understand that schedule is best effort and may be delayed or dropped. However, neither the real probe nor the minimal diagnostic has produced even one schedule event since repository creation, so there are no scheduled-job failure logs to investigate.

Could GitHub check whether scheduled event registration and delivery are working for this repository, or advise a specific repository/account setting we have missed? We are trying to retain native GitHub scheduling and are not treating manual runs as a successful repair.

Additional public chronology: https://github.com/tonywang1201/anyrouter-healthcheck/blob/main/docs/scheduler-diagnostics.md
