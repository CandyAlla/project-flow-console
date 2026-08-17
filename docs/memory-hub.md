# DevConductor 共享 Memory Hub 与 Codex Plugin

Memory Hub 是 DevConductor 自带的轻量共享后端。它只负责保存和检索已经结构化的工程记忆；DevConductor 控制台、Codex Plugin、项目仓库和 Worktree 仍然彼此独立。

```text
DevConductor 工作流 ─┐
                    ├── HTTP + API Key ── Memory Hub ── SQLite
Codex Memory Plugin ─┘
```

两种入口共用同一套 Team、Project、Task、Scope 和 Memory ID。项目身份默认来自 Git `origin`，也允许在 Project Profile、添加项目界面或 `DEVCONDUCTOR_REPOSITORY_URL` 中覆盖。本机绝对路径永远不会参与共享身份。

## 一、什么会共享

默认召回范围是：当前用户的 private、当前 Task、当前 Git Project、当前 Team，以及已批准的 global 记忆。

适合保存：

- 稳定工程事实
- 已确认的架构或产品决策
- 可复用操作手册
- 已证实的踩坑与规避方式
- 稳定验收规则
- Skill / 自动化候选

不会自动上传：

- 完整聊天或 Codex Session
- `task.json`、`task-memory.json`、Plan 全文
- 源码仓库或未审核 Diff
- 本机绝对路径
- API Key、Token、账号信息
- 原始日志、截图或上传文档

DevConductor 中“保留候选”只保存本机审核结果；必须再次点击“发布到共享记忆”才会写入后端。Codex Plugin 的 `memory_capture` 也只应在用户明确授权后调用；未完成审核时使用 `memory_publish_candidate`，候选不会参与普通召回。

已经发布的候选可以在任务沉淀卡片或跨项目沉淀中心点击“取消共享”。取消不是删除数据库记录，而是将远端状态从 `active` 改为 `deprecated`；只有 Memory Hub 确认成功后，本地界面才会清空发布标记，并保留原 Memory ID 和取消时间。取消后的条目不再参与正常召回，但可以从原候选重新发布，并复用同一个 Memory ID。

## 二、本机模式

直接运行：

```bash
python3 memory_hub.py
```

默认地址与文件：

```text
http://127.0.0.1:4328
.runtime/memory/memory.db
.runtime/memory/api-key
```

`start.command` 会自动启动本机 Memory Hub；如需连接已有远端后端，可关闭自动启动：

```bash
DEVCONDUCTOR_MEMORY_AUTOSTART=0 ./start.command
```

本机首次启动会生成权限为 `0600` 的 API Key 文件。数据库、WAL、Key 和真实记忆都在 `.runtime`，已被 Git 忽略。

## 三、团队共享模式

团队部署只运行 `memory_hub.py`，不要把 `hub.py` / `server.py` 控制台公开给其他电脑。建议在受控服务器上让 Memory Hub 继续监听回环地址，再通过带 TLS 的反向代理或私有网络入口访问。

```bash
export DEVCONDUCTOR_MEMORY_API_KEY="replace-with-a-long-random-team-key"
export DEVCONDUCTOR_MEMORY_DB="/srv/devconductor-memory/memory.db"
python3 memory_hub.py --host 127.0.0.1 --port 4328
```

如果直接监听非回环地址，服务会强制要求 `DEVCONDUCTOR_MEMORY_API_KEY`。HTTP 本身不提供 TLS；不要把明文端口直接暴露到互联网。

同事的 Profile 使用相同后端和 Team ID：

```json
{
  "repositoryUrl": "https://github.com/team/game-client.git",
  "memory": {
    "enabled": true,
    "endpoint": "https://memory.example.com",
    "teamId": "game-studio",
    "apiKeyEnv": "DEVCONDUCTOR_MEMORY_API_KEY",
    "maxItems": 8,
    "maxChars": 6000,
    "timeoutMs": 1500
  }
}
```

每台电脑单独设置 Key，禁止把 Key 写入 Profile：

```bash
export DEVCONDUCTOR_MEMORY_API_KEY="same-authorized-team-key"
export DEVCONDUCTOR_MEMORY_USER_ID="stable-member-id"
```

当前轻量版使用一个后端 API Key 作为服务访问门禁，并以 `teamId` 作为逻辑查询命名空间；`teamId` 本身不是安全授权边界。一个后端实例建议只服务一个互信团队。需要多租户、逐成员撤权、审计或 SSO 时，应在反向代理或后续认证层扩展，不要把一个团队 Key 发布到公共仓库。

## 四、Git 项目身份

以下地址会得到同一个 `projectKey`：

```text
git@github.com:Team/Game.git
ssh://git@github.com/Team/Game.git
https://github.com/team/game.git
→ github.com/team/game
```

添加项目时，控制台默认运行只读的 `git remote get-url origin`。如果 origin 指向镜像、Fork 或公司代理地址，可以填写“共享项目 Git 地址”覆盖。没有 origin 且没有覆盖时，共享记忆保持关闭，本地流程照常工作。

## 五、Codex Plugin

Plugin 位于：

```text
plugins/devconductor-memory
```

它包含：

- `SessionStart`、`UserPromptSubmit`、`PostCompact` 的限量自动召回 Hook
- `memory_search` / `knowledge_search`
- `memory_read`
- `memory_capture`
- `memory_publish_candidate`
- 写入门禁与数据边界 Skill

安装或从本仓库加载 Plugin 后，在启动 Codex 前设置：

```bash
export DEVCONDUCTOR_MEMORY_ENDPOINT="https://memory.example.com"
export DEVCONDUCTOR_MEMORY_API_KEY="replace-with-your-team-key"
export DEVCONDUCTOR_MEMORY_TEAM_ID="game-studio"
export DEVCONDUCTOR_MEMORY_USER_ID="stable-member-id"
```

如果一个本地 checkout 的 origin 不适合作为共享身份，可额外设置：

```bash
export DEVCONDUCTOR_REPOSITORY_URL="https://github.com/team/game-client.git"
```

Hook 失败、超时或后端不可用时会静默退化，不会阻塞 Codex。需要确认是否实际召回时，主动调用 `memory_search`。

## 六、Scope 与状态

| Scope | 可召回范围 |
|---|---|
| `private` | 同一 Team 下当前 `userId` |
| `task` | 当前 Project + Task |
| `project` | 同一规范化 Git 项目 |
| `team` | 同一 Team 的所有项目 |
| `global-candidate` | 候选用途，不进入普通召回 |
| `global` | 同一后端中已批准的全局知识 |

Memory 状态：

- `candidate`：待审核，不召回
- `active`：已批准，可召回
- `deprecated`：已取消共享或废弃，不召回；从原候选重新发布时可恢复为 `active`

## 七、备份与 GitHub 边界

停止 Memory Hub 后备份 SQLite 文件及其所在目录：

```text
/srv/devconductor-memory/memory.db
```

如果服务仍在运行，使用 SQLite 在线备份机制或同时处理 WAL，不要只复制主 `.db` 文件。

可以提交到 `project-flow-console` GitHub 的内容：Memory Hub 源码、Plugin、Schema、示例 Profile、部署文档和测试。

不能提交的内容：真实记忆数据库、WAL、API Key、任务运行态、Profile 中的个人绝对路径、Codex Session、日志、截图和私有项目地址。默认 `.gitignore` 已排除 `.runtime/`，发布前仍应执行一次敏感信息检查。

## 八、健康检查

Memory Hub 健康检查不返回数据或密钥：

```bash
curl --fail http://127.0.0.1:4328/health
```

DevConductor `/api/health` 会显示当前项目的 `repositoryKey`、Memory endpoint、Team ID 和是否已找到 API Key，但不会返回 Key 内容。
