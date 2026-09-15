# DevConductor

> **AI 开发指挥台 · 从需求到可信提交**

> [本机部署指南与目录选择策略](docs/local-deployment.md) · [Codex 连接配置](docs/codex-connections.md) · [共享 Memory Hub 与 Codex Plugin](docs/memory-hub.md) · [更新日志](CHANGELOG.md)

DevConductor 是一个运行在本机的、多项目 AI 开发指挥台。

它通过 Project Profile 适配不同 Git 项目，把下面这些原本散落在对话、终端和文档里的步骤，收拢成一条可恢复、可人工审批的工作流：

> 需求输入 → 轻量执行单或完整讨论 / Plan → Git Worktree → 快速修改或标准执行 → 人工验收 → Commit → Bug 返修 → AI 沉淀审核

飞书 / Lark 链接，以及选择正文导入或附件必读的其他链接，先在讨论页准备文档材料；满足正文覆盖和附件策略后，再开始或恢复讨论。

每条任务还提供独立的 **Ask · 只读问答** 模块，可以随时询问当前实现、状态来源、相关文件和修改影响；Ask 不属于流程阶段，不会修改文件或改变任务状态。

控制台支持多个需求并行排队、任务切换、归档与恢复，也支持接入已经存在的需求文档、Plan 和 Worktree。

## 界面预览

### 从需求输入开始

通过任务队列切换多个需求，并沿左侧流程导航查看每个需求所处阶段。新需求可以粘贴链接、上传文档或直接粘贴正文，也可以接入已有需求文档、Plan 和 Worktree。

![需求接入与流程导航](docs/images/requirement-intake.png)

### 人工验收与测试门禁

执行完成后，控制台会给出最小人工验证路径、详细测试用例和关键日志筛选词；P0 / 必测项全部通过后才能进入 Commit。

![人工验收、测试案例与日志门禁](docs/images/manual-acceptance.png)

### 文字和截图一起反馈

人工验收返修与 Commit 后 Bug 修复都支持文字、截图或两者组合提交；图片可以选择、粘贴或拖入，只保存在本地任务运行目录，不会进入 Worktree 或 Commit。

![Bug 描述与问题截图输入](docs/images/feedback-with-screenshots.png)

## 主要能力

- 输入网页链接、上传文档或直接粘贴需求内容。
- 链接需求可使用通用正文导入或官方 Lark CLI，先保存原文和章节覆盖再进入讨论；读取方式和附件策略可按项目及任务设置，读取失败可单独重试。
- 新需求的 Worktree 基准从 Profile 主仓库实时读取，以分组下拉框展示本地分支和已有远端跟踪分支；不会自动 Fetch。
- 明确的小改动可选“轻量直改”，本地生成最小执行单并跳过 discussion、完整 Plan Agent 和逻辑 HTML。
- 模糊、跨模块或高风险需求保留只读 discussion / ask-first，再生成完整执行 Plan。
- 同时输出 Markdown Plan 和自包含的逻辑验收 HTML；HTML 自动绘制节点连线蓝图，展示需求主流程、判断条件与异常/回退分支，并与验收项对应。
- 创建 Worktree 前先展示真实 dry-run；也可以接入已有 Worktree。
- 任务顶部持续显示 Worktree 名称、状态、分支和路径，并支持复制路径；非当前流程阶段只允许回看。
- 项目级 Worktree 管理：从任务队列打开“清理 Worktree”，查看当前仓库的 linked Worktree；只允许清理位于 Profile `worktreesRoot`、Git 状态干净且未被未归档任务占用的目录。清理使用 `git worktree remove`，不使用 `--force`，不删除分支。
- 每个需求可绑定一个独立的 Codex App 人工聊天；默认沿用现有 Codex 环境，也可按需配置单个或多个连接，打开时沿用绑定方式。
- 快速修改复用后台执行 Thread，一轮完成实现和自检；人工聊天与后台执行隔离，避免多客户端争用同一个 writer。
- 在任务绑定的 Worktree 中执行 Codex 和项目 Skills。
- 将实施与 Code Review 分开，Review 不通过时进入定向修复。
- 生成人工验收最短路径、详细测试案例和关键日志筛选词。
- 人工验收返修和 Commit 后 Bug 修复都可附加多张截图，支持选择、粘贴、拖入、预览和单张删除。
- Commit 前逐项选择本次要提交的文件，并重新校验真实 Git 状态；可先只 Stage 当前选择的文件，未选文件保留在 Worktree。
- Commit 后发现问题时，复用当前 Worktree 和任务记忆，在 Bug 修复模块内完成定向修改、Review、复验和新 Commit，不重新执行 Plan。
- Commit 与 Bug 修复闭环后，可只读生成最多 5 条 AI 沉淀候选；候选按稳定事实、决策、手册、踩坑、验收规律、Skill 或自动化分类，并保留直接证据。
- 任务级“沉淀”阶段和跨任务“沉淀中心”支持保留、忽略、二次确认发布和取消共享；候选审核只更新 `.runtime`，只有单独点击“发布到共享记忆”才写入 Memory Hub。
- 已共享候选可以随时取消共享：远端记忆会转为 `deprecated` 并停止召回，本地保留原 Memory ID 与取消时间，之后仍可重新发布。
- 内置轻量 SQLite Memory Hub；DevConductor 工作流和可独立安装的 Codex Plugin 共用同一后端，按 Git `origin` 识别项目并支持手动覆盖，不使用本机路径作为共享身份。
- 每个任务提供独立 Ask 只读问答，可询问当前实现、状态来源、相关文件和修改影响范围，不改变任务阶段。
- 多需求队列可切换查看，支持归档、删除、恢复和有限并行。
- 可主动开启浏览器任务通知；任务开始、排队、进入新阶段、完成或需要处理时提醒。首次加载只建立状态基线，前台显示页面内提示，页面在后台时发送系统通知；点击通知可返回对应项目与任务。
- Project Hub 统一展示所有项目、全部任务和跨项目沉淀；左侧项目轨道可随时切换，后台任务不会因切换视图而停止。
- 可以从控制台扫描本地 Git 项目生成 Profile，也可以接入已有 Project Profile；添加前必须先查看 dry-run 预览。
- 每个项目由独立 Profile 配置，不在服务代码中写死路径。

## 运行环境

必需：

- Python 3.10 或更高版本
- Git，并支持 `git worktree`
- 可正常运行的 Codex CLI
- 一个本地 Git 项目

可选：

- Node.js：用于 `app.js` 语法检查和部分前端逻辑测试。
- 官方 [Lark CLI](https://github.com/larksuite/cli)：自动读取飞书 / Lark Wiki 或文档时需要，并须具备当前用户授权。`lark-shared`、`lark-wiki`、`lark-doc` Skills 可提供操作指导，缺失只显示诊断提示。
- 可访问来源文档的浏览器或其他工具：用于获取待导入正文，按该来源的权限要求使用。通用导入无需 Chrome 或 Codex 桌面；控制台未实现后台自动 Chrome 读取。
- 项目 Skills：Profile 中引用的 Skill 必须已能被 Codex 发现。

服务端只使用 Python 标准库，不需要执行 `pip install`。

## 目录结构

```text
DevConductor/
├── hub.py                         # 多项目 Hub、Worker 路由与全局并发门禁
├── server.py
├── source_reading.py               # 正文快照校验、覆盖门禁与读取错误分类
├── lark_source.py                  # Lark 原文及内嵌表格解析
├── codex_connections.py            # 后台与桌面 Codex 连接配置
├── memory_hub.py                  # 可独立部署的共享记忆 HTTP 服务
├── memory_client.py               # 工作流侧 Memory Hub 客户端
├── app.js
├── index.html
├── start.command
├── profiles/
│   └── example.json                  # 不含个人路径的通用 Profile 模板
├── schemas/                          # Codex 结构化输出协议
├── docs/                             # 部署、连接与共享记忆说明
│   └── examples/plan-blueprint.html   # Plan 逻辑蓝图样式示例
├── scripts/
│   └── create_git_worktree.py        # 通用 Git Worktree provider
├── skills/
│   └── project-flow-setup/            # 为新项目生成 Profile 的 Skill
├── plugins/
│   └── devconductor-memory/       # 可独立安装的 Codex Memory Plugin
└── tests/
```

运行时状态保存在：

```text
.runtime/<project-id>/tasks/
.runtime/<project-id>/tasks/<task-id>/source/  # 正文版本快照与 Lark 原始读取结果
.runtime/hub/projects.json         # 工具目录外 Profile 的本机路径引用
.runtime/hub/logs/                 # 各项目 Worker 日志
.runtime/hub/job-slots/            # 跨项目并发锁
.runtime/memory/memory.db          # 本机 Memory Hub 数据库
.runtime/memory/api-key            # 自动生成的本机 API Key
```

不同 Profile 的任务队列和任务记忆互相隔离，`.runtime/` 已加入 `.gitignore`。

## 5 分钟快速开始

如果要把工具安装到另一台电脑，或需要规划主仓库、文档和隔离执行目录，请先阅读 [本机部署与目录选择策略](docs/local-deployment.md)。现有项目无需移动；没有现成规范时才使用本机托管目录。

### 1. 获取代码

```bash
git clone https://github.com/CandyAlla/project-flow-console.git dev-conductor
cd dev-conductor
```

兼容说明：产品品牌已更新为 DevConductor；GitHub 仓库地址、`$project-flow-setup` Skill 名称和 `PROJECT_FLOW_*` 环境变量暂时保留旧技术标识，现有安装目录和任务数据不需要迁移。

### 2. 安装配置 Skill

Skill 的唯一源文件位于本工具目录：

```text
skills/project-flow-setup
```

推荐使用软链接让 Codex 自动发现它：

```bash
mkdir -p ~/.codex/skills
ln -s "$PWD/skills/project-flow-setup" ~/.codex/skills/project-flow-setup
```

如果目标路径已存在，先检查它是否已经指向当前工具，不要直接覆盖。安装后新建一个 Codex 任务，即可调用 `$project-flow-setup`。

### 3. 为项目生成 Profile

在 Codex 中输入：

```text
使用 $project-flow-setup 配置 /absolute/path/to/your-project
```

Skill 会先只读扫描：

- Git 根目录、当前分支和未完成的 Git 操作
- `AGENTS.md`、工程手册与项目事实入口
- `Doc/Skills`、`Docs/Skills`、`.codex/skills` 等 Skill 目录
- 文档、Worktree、Plan 和 HTML 的建议路径
- 已有目录规范与 `~/ProjectFlowData/<project-id>` 托管 fallback
- 是否存在 `.gitmodules`

它会先执行 dry-run。确认路径、分支和 Skill 链正确后，再生成：

```text
profiles/<project-id>.json
```

也可以不通过 Codex，直接运行确定性脚本：

```bash
python3 skills/project-flow-setup/scripts/configure_project.py \
  /absolute/path/to/your-project \
  --dry-run

python3 skills/project-flow-setup/scripts/configure_project.py \
  /absolute/path/to/your-project
```

常用的自定义示例：

```bash
python3 skills/project-flow-setup/scripts/configure_project.py \
  /absolute/path/to/your-project \
  --name "My Project" \
  --id my-project \
  --base develop \
  --docs-root /absolute/path/to/MyProjectDocs \
  --worktrees-root /absolute/path/to/worktrees \
  --verification-source "Application Log" \
  --verification-source "Test Report" \
  --dry-run
```

使用 `--help` 查看全部参数：

```bash
python3 skills/project-flow-setup/scripts/configure_project.py --help
```

### 4. 启动多项目控制台

macOS 推荐直接运行：

```bash
./start.command
```

未设置 `PROJECT_FLOW_PROFILE` 时，`start.command` 默认启动 Project Hub。Hub 自动发现 `profiles/*.json`，项目 Worker 在首次进入项目或汇总跨项目数据时按需启动。

即使当前还没有任何 Profile，Hub 也可以启动；页面会直接进入“所有项目”，通过“＋ 添加项目”完成第一次配置。

如果 4318 上已经有旧的单项目服务在运行，`start.command` 会直接打开它，不会为了切换 Hub 而中断正在执行的任务；等任务完成并正常停止旧服务后，再次启动即可进入 Hub。

也可以直接运行：

```bash
python3 hub.py --port 4318
```

打开 `http://127.0.0.1:4318/` 后：

1. 左侧最窄的项目轨道用于切换项目；顶部“⌂”进入所有项目首页。
2. 所有项目首页可以查看全部任务和跨项目沉淀。
3. 点击“＋ 添加项目”，可扫描 Git 项目或填写已有 Profile 绝对路径。
4. 扫描只读预览通过后，点击“确认添加”才会生成或登记 Profile；不会创建 Worktree、执行 Plan 或修改项目代码。

每个项目继续使用独立的 Profile、Worker 进程、任务目录、Codex 会话和 Git 写锁。切换项目只改变当前视图，不会停止其他项目正在运行的任务。

同一个项目运行目录同一时间只允许一个控制器占用；如果已经有单项目服务或另一个 Hub Worker 在运行，新进程会拒绝启动该项目，避免两个进程同时写 `task.json`。

### 5. 单项目兼容启动

需要保持旧的单项目入口时，显式设置 Profile：

```bash
PROJECT_FLOW_PROFILE="$PWD/profiles/my-project.json" python3 server.py
```

也可以临时覆盖端口：

```bash
PROJECT_FLOW_PROFILE="$PWD/profiles/my-project.json" \
python3 server.py --port 4320
```

macOS 可以使用：

```bash
PROJECT_FLOW_PROFILE="$PWD/profiles/my-project.json" ./start.command
```

服务只监听 `127.0.0.1`。启动日志会打印实际地址，例如：

```text
My Project · DevConductor: http://127.0.0.1:4318/
```

在浏览器打开该地址即可。

单项目模式与已有任务数据保持兼容，但不会显示项目轨道和所有项目首页。

## 多项目架构与并发

DevConductor 使用 `Project Hub + 每项目独立 Worker`：

```text
Browser
  └── Project Hub :4318
        ├── Project A Worker → Profile A → Repo / Worktrees / .runtime/A
        ├── Project B Worker → Profile B → Repo / Worktrees / .runtime/B
        └── Project C Worker → Profile C → Repo / Worktrees / .runtime/C
```

Hub 只负责项目注册、API 路由、聚合视图和全局并发门禁。实际需求流程仍由原有单项目 `server.py` 执行，因此不会在一个进程里动态替换 `REPO_ROOT`、`TASK_ROOT` 或 Git 上下文。

默认并发限制：

- 单项目最多 8 个后台任务。
- 所有项目合计最多 16 个后台任务。
- 同一个项目的 Git 写操作继续使用该 Worker 内的独占锁。

可以在启动 Hub 前调整：

```bash
PROJECT_FLOW_PROJECT_CONCURRENCY=8 \
PROJECT_FLOW_GLOBAL_CONCURRENCY=16 \
python3 hub.py
```

项目 Worker 不是常驻 Agent。没有阶段正在执行时，它只保存和提供任务状态；每条需求的上下文仍由 `task-memory.json`、Plan 路径与 Hash、Codex session / Thread 和 Git 指纹恢复。

## 如何使用控制台

| 阶段 | 发生什么 | 写入边界 |
|---|---|---|
| 需求输入 | 输入链接、文件、正文，或接入已有文档和 Worktree | 上传文件仅进入本地任务目录 |
| 文档读取（讨论前置） | 选择导入或 Lark CLI 的链接先准备原文，核对正文覆盖和附件策略；保存后单独开始讨论 | 正文、覆盖记录和原始接口结果仅保存到本地任务目录 |
| 讨论澄清 | 标准需求由 Codex 读取项目事实并提出 1–3 个高返工问题；轻量直改跳过 | 严格只读 |
| Plan 验收 | 标准需求生成 Markdown Plan 和逻辑 HTML；轻量直改本地生成最小执行单 | 服务落地草案，不实施代码 |
| Worktree | 先预览，再创建或绑定隔离 Worktree | 需要单独点击批准 |
| 执行 | 在 Worktree 内执行 Plan 和项目 Skill 链 | 不自动 Commit、Push、Merge |
| 人工验收 | 展示最小验证步骤、详细用例和验收日志；问题反馈可填写文字或附截图 | 用户逐项确认 P0 / 必测项；截图仅进入任务运行目录 |
| Commit | 刷新 Git 摘要、逐项选择文件并校验状态指纹；可单独 Stage | Stage 只暂存选中文件；Commit 需要单独确认，只提交选中项，未选文件保留 |
| Bug 修复 | 根据文字、截图或两者组合，在本模块内完成定向修改、Review、人工复验和新 Commit | 不重新执行 Plan；复用当前 Worktree，不重写旧 Commit |
| AI 沉淀 | 从任务记忆引用、Plan Hash、Commit、变更文件和验证证据中生成 0–5 条候选，并逐条审核 | 严格只读；候选与审核状态仅保存到 `.runtime`，不自动发布 |
| Ask | 基于当前任务、Plan、持久记忆和 Worktree 回答实现问题 | 严格只读，不修改文件，不改变流程阶段 |

任务在后台运行时可以切换查看其他需求。服务重启后，进行中的操作会标记为中断，已有文档和 Worktree 改动会保留，可从对应阶段重试。

左侧导航区分“当前”阶段与只读回看。回看非当前阶段时，输入和执行入口会锁定，可点击“返回当前阶段”继续处理；返修使流程退回执行时，页面会跟随实际阶段。任务顶部的 Worktree 信息栏可用于确认本次执行目录和分支，路径生成后即可复制。

任务队列顶部的“开启任务通知”会请求浏览器系统通知权限。通知默认关闭；只有用户授权后才启用。控制台页面需要保持打开，系统通知才会持续工作；页面处于前台时只显示 Toast，后台时才弹系统通知，多标签页会通过本地租约避免重复提醒。

## 轻量直改与标准需求

新建任务时先选择需求处理方式：

| 需求处理方式 | Codex 前置轮次 | 产物 | 适合场景 |
|---|---:|---|---|
| 标准需求（默认） | discussion + Plan | 完整 Plan Markdown 与逻辑验收 HTML | 链接/文档输入、方案有分支、跨模块或高风险需求 |
| 轻量直改 | 0 | 根据粘贴内容本地生成最小 Markdown 执行单 | 参数、文案、局部 UI 和边界明确的小改动 |

轻量直改只接受最多 12000 字符的粘贴内容。创建任务时不会启动 Codex，而是直接展示 Worktree dry-run；确认创建 Worktree 后，再用快速执行模式启动一次持久后台执行 Thread 完成修改与自检。它仍保留 Worktree 隔离、人工验收、Commit 指纹校验和不自动 Push/Merge 的边界。

## Codex App 联动与两种执行模式

任务创建后，页面顶部会出现“Codex App 人工聊天”面板。点击“新建聊天并在 Codex App 打开”后，控制台会通过官方 [Codex App Server](https://learn.chatgpt.com/docs/app-server.md) 协议创建独立人工聊天，并记录到当前任务：

```text
task.sessions.codexApp
task.codexApp.threadId
task.codexApp.deepLink
task.codexApp.cwd
```

人工聊天与快速模式使用的后台执行 Thread 相互隔离。创建人工聊天时会启动一次短生命周期 App Server，写入名称和项目目录后等待进程完全退出、释放 thread writer，再跳转到 Codex App；已经绑定的人工聊天再次打开时不会由控制服务 `thread/resume`，因此不会和桌面 App 争用 writer。

后台快速执行每轮使用独立的 App Server 进程。每轮结束（包括失败、停止和超时）后，控制服务会关闭该进程并等待 writer 释放，避免后台进程长期阻止 Codex App 归档。持久会话 ID 和历史仍保留，下一轮按需 `thread/resume`；其他并行任务不受影响。

Worktree 已准备完成且目录有效时，人工聊天连接该 Worktree；否则连接 Project Profile 的 `repoRoot`。如果绑定后项目目录发生变化，控制台会在新目录创建新的人工聊天并保留旧聊天。后台快速执行仍使用 `task.sessions.app` / `task.app`，不会被人工聊天的“新建”或“断开”操作清空。

已连接后还可以选择：

- **新建聊天**：在同一项目目录创建并绑定新的独立人工聊天，确认 writer 已释放后打开 Codex App；旧聊天保留在 App 中。
- **断开连接**：只解除当前需求与人工聊天的绑定；不会归档或删除旧聊天，也不会清除后台快速执行上下文。

任务正在执行时，人工聊天的打开、新建和断开会被禁用，避免同时切换目录或会话。断开后再次打开会创建新的独立人工聊天；快速模式仍按需创建或恢复后台执行 Thread。

| 模式 | 执行方式 | 独立 Review | 适合场景 |
|---|---|---|---|
| 快速修改（默认） | 持久 `codex app-server` Thread，一轮实现并自检 | 跳过；页面明确标记 `skipped` | 小改动、验收返修、定向 Bug 修复 |
| 标准流程 | 原有 `codex exec` 实施会话，再运行独立只读 Review | 保留 | 大改动、共享逻辑、高风险需求 |

两种模式都会保留：

- 当前 Worktree 的写入边界。
- 最小人工验证步骤、详细测试案例和关键日志。
- P0 / 必测人工验收门禁。
- Commit 前真实 Git 状态与指纹复核。
- 不自动 Push 或 Merge。
- 标准流程的 Code Review 采用“无新进展超时 + 绝对上限”；有命令、消息或检查事件时自动续期。

快速模式只是省去第二个独立 Review，不会把“未 Review”伪装成“Review 通过”。用户停止快速任务时，服务中断当前需求的 Turn，并在收尾时关闭该轮独立 App Server；其他任务继续运行。

已有 `.runtime`、任务、Worktree 以及 discussion / execution / review / ask session 会在加载时兼容迁移；不使用快速模式时，原有标准流程行为保持不变。

快速 Turn 默认采用两级超时：连续 600 秒没有新的命令、消息或文件进度时自动停止；持续有进度时自动续期，但单轮绝对不超过 1800 秒。无进度超时可配置为 120–1800 秒，绝对上限可配置为 600–3600 秒；页面仍可随时手动停止：

```bash
PROJECT_FLOW_QUICK_TIMEOUT=600 \
PROJECT_FLOW_QUICK_HARD_TIMEOUT=1800 \
PROJECT_FLOW_PROFILE="$PWD/profiles/my-project.json" \
python3 server.py
```

标准流程的 Code Review 默认连续 600 秒没有新事件才停止，绝对上限为 1800 秒；可单独配置：

```bash
PROJECT_FLOW_REVIEW_TIMEOUT=600 \
PROJECT_FLOW_REVIEW_HARD_TIMEOUT=1800 \
PROJECT_FLOW_PROFILE="$PWD/profiles/my-project.json" \
python3 server.py
```

Review 超时只会中断 Review，不会回滚实施结果或 Worktree 改动。页面会保留“继续上次 Code Review”入口：如果 Git 状态没有变化，则续接上次 Review；如果状态发生变化，则自动放弃旧 Review 会话并重新读取当前范围。

人工验收返修若停在“执行已部分完成”，且已有人工验收清单，可以选择：

- 继续现有修改并完成自检：从当前 Git Diff 和断点补齐剩余工作。
- 接受当前断点，返回人工验收：等待执行停止后，点击此按钮并确认。本轮自动自检仍视为未完整结束，Review 标记为 `skipped`；原验收勾选会保留，但验收通过状态会重置，仍需完成门禁并再次确认。

普通执行断点或缺少验收清单时不提供“接受当前断点”入口。提交人工验收前，页面会先读取最新任务状态；如果任务已回到执行中，则刷新到当前阶段，等待执行结束后再验收。

Ask 只读问答默认连续 120 秒没有新进度才停止；持续有命令、消息或检查事件时自动续期，默认绝对上限为 600 秒。无进度超时可配置为 60–600 秒，绝对上限可配置为 300–1800 秒，且不低于无进度超时。Ask 禁用子代理，并要求最多执行 8 次有明确路径范围的只读检查，优先使用当前任务记忆和最近变更文件。失败或超时后会解除旧 Ask 会话绑定，下一次提问从干净会话开始：

```bash
PROJECT_FLOW_ASK_TIMEOUT=120 \
PROJECT_FLOW_ASK_HARD_TIMEOUT=600 \
PROJECT_FLOW_PROFILE="$PWD/profiles/my-project.json" \
python3 server.py
```

沉淀提炼也采用两级超时：默认连续 600 秒没有新进度才停止；有命令、消息或检查事件时自动续期，单轮绝对上限为 1800 秒。可单独配置无进度超时（120–1800 秒）和绝对上限（600–3600 秒）：

```bash
PROJECT_FLOW_KNOWLEDGE_TIMEOUT=600 \
PROJECT_FLOW_KNOWLEDGE_HARD_TIMEOUT=1800 \
PROJECT_FLOW_PROFILE="$PWD/profiles/my-project.json" \
python3 server.py
```

沉淀阶段仍然只读，不会修改项目文件或 Git；超时后已有结果和 Worktree 改动会保留。

## 接入已有文档和 Worktree

控制台支持两种已有资产入口：

### 已有需求文档

- 填写需求文档绝对路径。
- 填写已有 linked Worktree 的绝对路径。
- 校验通过后，从只读讨论阶段继续。

### 已有执行 Plan

- Plan 必须是 UTF-8 Markdown。
- Plan 必须位于所填 Worktree，或 Profile 配置的 `docsRoot` 内。
- Worktree 必须属于 Profile 中的同一个主仓库。
- 校验通过后直接进入执行授权阶段，不重新生成 Plan。

服务会拒绝：

- 把主仓库本身当作 Worktree。
- 其他 Git 仓库的 Worktree。
- detached HEAD。
- 分支已经变化的已绑定 Worktree。
- 存在未完成 Merge、Rebase、Cherry-pick 或 Revert 的仓库。

## Project Profile

Profile 是控制台与项目之间唯一的配置协议。核心示例：

```json
{
  "schemaVersion": 1,
  "id": "my-project",
  "name": "My Project",
  "workspaceRoot": "/absolute/path/to/workspace",
  "repoRoot": "/absolute/path/to/workspace/my-project",
  "repositoryUrl": "https://github.com/team/my-project.git",
  "docsRoot": "/absolute/path/to/workspace/MyProjectDocs",
  "worktreesRoot": "/absolute/path/to/workspace/worktrees",
  "htmlTaskRoot": "/absolute/path/to/workspace/MyProjectDocs/Tasks/进行中",
  "defaultBaseBranch": "develop",
  "worktreeNamePrefix": "MyProject",
  "planRelativeDir": "Docs/plans/active",
  "projectFacts": [
    "AGENTS.md",
    "Docs/index.md",
    "Docs/Skills/README.md"
  ],
  "planTemplate": "Docs/rules/plan-template.md",
  "sourceReading": {
    "defaultReader": "auto",
    "attachmentPolicy": "optional"
  },
  "skills": {
    "discussion": ["discussion-only", "ask-first"],
    "plan": ["clear-html"],
    "execution": ["workmission", "change-guard"],
    "acceptanceFix": ["change-guard"],
    "review": ["code-review"]
  },
  "verification": {
    "sources": ["Application Log", "Test Report"],
    "policy": "AI 运行可自动化测试；设备验证由用户完成。"
  },
  "capabilities": {
    "initializeSubmodules": false
  },
  "memory": {
    "enabled": true,
    "endpoint": "http://127.0.0.1:4328",
    "teamId": "my-team",
    "apiKeyEnv": "DEVCONDUCTOR_MEMORY_API_KEY",
    "maxItems": 8,
    "maxChars": 6000,
    "timeoutMs": 1500
  },
  "port": 4318
}
```

关键规则：

- 所有根目录必须使用绝对路径。
- `repoRoot` 必须是准确的 Git 根目录。
- `repositoryUrl` 默认从 Git `origin` 自动读取，也可手动覆盖；SSH、HTTPS 和 scp 风格地址会规范化为同一个项目 key，本机绝对路径不会参与共享身份。
- `worktreesRoot` 不能等于或位于 `repoRoot` 内部。
- `htmlTaskRoot` 必须位于 `docsRoot` 内。
- `planRelativeDir`、`projectFacts` 和 `planTemplate` 必须是仓库内相对路径，不能包含 `..`。
- Skill 名必须是小写 kebab-case，并且已经能被 Codex 发现。
- `sourceReading` 可省略，默认自动选择链接读取方式、附件可选。设置只作为新任务默认值，具体规则见[链接文档读取](#链接文档读取)。
- Profile 是声明式数据，不能包含任意 shell、Hook 或 Git provider 命令。

完整字段说明见 [Project Profile Schema](skills/project-flow-setup/references/profile-schema.md)。

## 多任务与并行

默认最多同时运行 8 个后台任务，其余任务进入队列。可以在启动前调整为 1–8：

```bash
PROJECT_FLOW_CONCURRENCY=8 \
PROJECT_FLOW_PROFILE="$PWD/profiles/my-project.json" \
python3 server.py
```

每条需求拥有独立的：

- 状态记录
- Codex discussion / execution / review / ask 会话槽
- 后台快速执行 Thread 槽与独立 Codex App 人工聊天槽
- 持久任务记忆
- Plan、HTML 和 Worktree 绑定信息

它不是“每个需求常驻一个一直运行的 Agent”。后台 Worker 只在阶段执行时占用资源，任务上下文通过结构化状态、Codex session id、Plan 和 Git 指纹恢复。

为避免每轮反复发送完整上下文，DevConductor 使用增量 Prompt：稳定执行规则保存在工具 Skill 的版本化契约中；持久任务事实写入任务目录下的 `task-memory.json`，Prompt 只传绝对路径和 SHA-256；每轮只补充新增要求、Review findings、受影响文件和需要重新确认的验收项。旧任务会在服务启动时自动生成记忆引用，不需要迁移。

## 共享 Memory Hub

`start.command` 默认在 `127.0.0.1:4328` 启动本机 Memory Hub。各工作流阶段会限量召回当前 Task、Project、Team 与已批准全局记忆；后端不可用时自动退化到当前代码、Plan、Git 和本地 `task-memory.json`，不会卡住任务。

已共享记忆可在任务沉淀卡片或跨项目沉淀中心点击“取消共享”。DevConductor 会先要求 Memory Hub 将远端状态改为 `deprecated`，确认成功后才清空本地发布标记；取消后不会再参与正常召回，并可使用同一候选重新发布。

真实记忆、SQLite 数据库、API Key、任务状态、聊天和日志都不提交到本仓库。GitHub 中只包含 Memory Hub 功能代码、Profile Schema、Codex Plugin 与部署说明。团队共享部署、权限边界、备份和 Plugin 配置见 [共享 Memory Hub 与 Codex Plugin](docs/memory-hub.md)。

## 链接文档读取

链接需求支持以下读取方式：

- **正文导入（`manual_import`）**：从有权限的浏览器、文档工具或其他渠道读取精确链接，再导入标题、完整正文和覆盖情况；无需 Chrome、特定插件或 Codex 桌面。控制台提供可复制的只读读取提示，不会自动操作 Chrome。
- **官方 Lark CLI（`lark_cli`）**：支持 `feishu.cn`、`larksuite.com` 和 `larkoffice.com` 的 `/docx/`、`/wiki/` 文档链接。服务使用现有飞书用户授权，执行固定的 `docs +fetch`，并尝试用 `sheets +csv-get` 读取可解析的内嵌表格。后台 Codex 在只读沙箱中核验已保存材料的正文覆盖。
- **Codex 直接只读（`codex_read_only`）**：适用于普通公开链接，在讨论中直接读取。飞书 / Lark 链接或要求附件必读时，须先通过导入或 Lark CLI 准备材料。

### 项目默认值与任务选择

Profile 可选配置 `sourceReading`；省略时为 `defaultReader: "auto"`、`attachmentPolicy: "optional"`。新任务可覆盖读取方式和附件策略，创建后将具体选择保存在任务的 `source` 中。

| `defaultReader` | 飞书 / Lark 链接 | 其他链接 |
| --- | --- | --- |
| `auto` | 正文导入 | 附件可选时 Codex 直接只读；附件必读时正文导入 |
| `manual_import` | 正文导入 | 正文导入 |
| `lark_cli` | 官方 Lark CLI | 回退为正文导入 |
| `codex_read_only` | 回退为正文导入 | 附件可选时 Codex 直接只读；附件必读时回退为正文导入 |

以上回退仅用于解析项目默认值。用户显式选择不适用于该链接或附件策略的读取方式时，后端会报错。`sourceReading` 只接受枚举配置，不支持任意 shell、provider 命令、可执行文件或凭据路径。

附件策略独立于读取方式：

- **可选（`optional`，默认）**：未读附件和引用保留提示；正文非空、覆盖完整且没有缺失正文章节时可进入讨论，不把未读内容视为已知事实。
- **必读（`required`）**：必须补齐全部未读附件和引用；`missingAttachments` 非空会阻断讨论和规划。正文完整性要求仍然适用。

Profile 默认值变更只影响新任务。旧任务没有保存附件策略时沿用 `optional`；旧 `chrome_mcp` 任务继续使用正文导入流程。

### 准备和使用材料

选择正文导入时：

1. 从有权限的渠道读取精确链接，对照目录补齐虚拟化或懒加载章节，保留正文中的表格、列表和代码块。
2. 填写文档标题、完整正文、已读章节、缺失正文章节和未读附件；附件必读时也须取得全部附件及引用内容。
3. 保存正文与覆盖情况。未保存草稿只在当前页面内存中，刷新或关闭页面会丢失；也可以先保存部分材料，稍后补齐。
4. 材料满足当前策略后，点击“使用材料”开始或恢复讨论。导入内容及覆盖情况由用户核对，不代表系统重新访问并核验了来源文档。

选择 Lark CLI 时，创建任务后自动开始读取与覆盖核验，材料就绪后同样需要点击“使用材料”才会开始讨论。无法读取的图片、画板、Base、表格或引用保留在未读列表；是否阻断由当前附件策略决定。页面显示后续讨论使用的后台连接名称，桌面聊天选择不会改变它。后台 Codex 认证与飞书用户授权分别检查，详见 [连接配置与读取环境](docs/codex-connections.md)。

讨论阶段且任务空闲时，可显式切换正文导入 / Lark CLI，并调整附件策略。切换读取方式会保留原讨论及正文历史，但需要重新读取或保存后才能继续；调整附件策略会重新判断已保存材料是否就绪。已有独立材料步骤的任务不能切回 Codex 直接只读来跳过材料门禁。新正文必须先用于讨论，才能生成 Plan。

正文最多 240000 个字符；每次保存生成任务目录下的 `source/document-<revision>.md`，快照元数据保存在 `task.json`。Lark 原始读取结果另存为 `source/lark-read-<id>.json`。后续 Discussion 和 Plan 使用同一份正文文件并核对 SHA-256，不重复在线读取。读取重试或方式切换不会迁移旧讨论会话。

### Lark CLI 环境与故障恢复

Lark CLI 可用性以实际可执行文件和飞书 `user` 授权为准，只有 `bot` 可用时不能读取。`lark-shared`、`lark-wiki`、`lark-doc` Skills 缺失仅显示诊断提示，不阻断固定命令读取。CLI 或授权未就绪时，可恢复环境后重试，也可在讨论空闲时显式切换正文导入。

安装并完成当前用户授权：

```bash
npx @larksuite/cli@latest install
lark-cli config init --new
lark-cli auth login --recommend
lark-cli auth status --json
```

如需在其他 Agent 任务中使用 Lark 操作指导，可选安装相关 Skills：

```bash
npx skills add larksuite/cli -y -g
```

可通过 `PROJECT_FLOW_LARK_CLI_BIN` 指定 `lark-cli` 的绝对路径。授权链接由用户本人打开确认，凭据保存在 CLI 环境中。状态预检通过后仍需实际文档权限；内嵌表格可能需要 `sheets:spreadsheet:read`，缺少时记录未读项，不自动扩大权限。

读取失败可单独重试，并保留已有材料和讨论会话。页面区分 Lark 凭据访问、Codex 认证及文档登录或权限问题。正文为空、截断或正文章节缺失始终阻断材料门禁；附件按当前策略处理。服务执行固定的只读命令，导入只写本地任务材料，读取器不会自动切换或扩大授权。

## Git 安全边界

内置 Worktree provider 会：

- 校验 Git 根目录、当前分支、基准 ref 和未完成 Git 操作。
- 展示当前主仓库状态和已有 Worktree。
- 先输出 dry-run，再执行 `git worktree add`。
- 创建后核对 Worktree 根、分支和 HEAD。
- 仅在 Profile 开启时初始化并验证 Submodule。

它不会：

- Fetch、Pull、Push 或 Merge。
- 切换主仓库分支。
- 修改 Git config。
- 删除或覆盖已经存在的 Worktree。
- 自动提交代码。

控制台的 Stage / Commit 操作也有独立门禁：人工验收通过后，用户逐项选择文件。Stage 会重新读取文件列表和 Git 状态指纹，只执行 `git add`，不会创建 Commit；Commit 会再次校验并只提交选中项。如果状态发生变化或所选路径已失效，操作会被拒绝并要求重新确认；未选文件继续保留在 Worktree。

## 本地服务安全

- 只监听 `127.0.0.1`。
- 拒绝非 localhost Host。
- 修改类 API 需要当前服务生成的会话令牌。
- 上传和请求体有大小限制。
- 反馈截图仅支持 PNG、JPEG、WebP，一次最多 6 张、单张最多 4 MB、总计最多 8 MB。
- 反馈截图保存在 `.runtime/<project-id>/tasks/<task-id>/feedback-images/`，标准模式通过 Codex CLI `--image` 读取，快速模式通过 App Server `localImage` 输入读取；不复制到 Worktree，也不会进入 Commit。
- Codex 阶段使用明确的 read-only 或 workspace-write sandbox。
- 需求网页、文档和粘贴内容一律按不可信输入处理。

这个工具会在用户点击授权后运行 Codex、创建 Worktree 和执行 Commit。使用前仍应检查 Project Profile、目标仓库和 Worktree 路径。

## 测试

运行完整测试：

```bash
python3 -m unittest discover -s tests -v
```

补充语法检查：

```bash
node --check app.js
python3 -m py_compile \
  hub.py \
  server.py \
  codex_connections.py \
  source_reading.py \
  lark_source.py \
  scripts/create_git_worktree.py \
  skills/project-flow-setup/scripts/configure_project.py
```

测试覆盖控制器门禁、任务队列、归档恢复、Git 指纹、人工验收、Commit、返修、后台执行 Thread 复用、Codex App 人工聊天隔离、快速模式、旧任务迁移、Profile 校验、配置脚本，以及通用 Worktree provider。

文档读取测试覆盖正文与来源校验、附件策略、读取方式与项目默认值、固定 CLI 命令、取消与超时、讨论恢复及规划门禁；另有 Ask 会话恢复、具体错误展示和返修断点验收测试。Lark / Codex 读取使用模拟结果，前端测试检查界面逻辑；这些测试不替代真实账号、凭据环境、浏览器或跨机器端到端验收。

## 常见问题

### HTML 文档支持蓝图绘制吗？

标准需求的 Plan 生成会要求 HTML 包含内联 SVG 逻辑蓝图。默认采用暖米白文档与深森林绿点阵、大网格画布；紧凑矩形节点包含状态小标签、职责标题和 1–2 行说明，按实际阶段、职责归属或前后关系分区，以正交连线、箭头和分支标签说明关系，避免大菱形流程图。图下提供完整文字等价说明，以及节点职责、边界和对应验收项。

蓝图支持离线查看；320px 窄屏下正文不横向溢出，蓝图可单独原生滚动，打印使用白底完整图。HTML 预览的 CSP 禁止脚本，因此只使用可用的原生控件和锚点，不添加无效的缩放、拖拽或全屏按钮，不需要安装图表库。

可直接打开 [蓝图样式示例](docs/examples/plan-blueprint.html) 查看效果；示例展示控制台的方案验收过程，实际生成时绘制的是各自需求的业务逻辑。更新服务后，新增的标准 Plan 生成会采用这套要求；已落地的 HTML 不会自动改写。轻量直改仍跳过完整 Plan 和 HTML。

### 正文已保存，页面仍提示无法讨论怎么办？

先确认保存的材料显示正文覆盖完整、没有缺失正文章节；附件必读时还需补齐全部未读附件和引用。若刚切换读取方式，须重新读取或保存材料。若服务已更新且材料已经就绪，但旧标签页仍显示过时提示，先保存导入草稿，再刷新页面（macOS：`⌘R`），然后点击“使用材料”；重新读取文档不会更新旧页面中的脚本。

若仍有读取错误，展开“查看真实状态记录”核对具体原因。Codex 认证缺失、Lark 钥匙串访问失败和文档权限不足需要分别处理，不能仅凭“读取失败”判断为飞书未登录。

### 为什么最多只有八个后台任务？

默认并行数是 8，避免多个 Codex 和 Git 操作无限制抢占本机资源。通过 `PROJECT_FLOW_CONCURRENCY` 可调整为 1–8；使用 Project Hub 时，还会受全局并发上限 16 的限制。

### Profile 已存在，配置脚本拒绝写入怎么办？

先比较 dry-run 输出与已有 Profile。只有确认需要替换时才使用 `--force`，脚本默认不会覆盖已有配置。

### 服务重启后任务还在吗？

在。任务记录位于 `.runtime/<project-id>/tasks`。重启时正在运行的阶段会变成 `interrupted`，已有 Worktree 改动不会被清理。

### Codex 提示缺少环境变量，反复重试仍失败怎么办？

未配置连接文件时，后台和人工聊天沿用服务启动时的 Codex 环境，界面只显示默认环境，不提供无效的登录切换选项。

需要单独配置后台或桌面连接时，可使用 `.runtime/codex-connections.json` 的 v2 格式。连接可以只有一条，也可使用多个自定义 ID；`backgroundConnection` 单独决定后台连接，桌面仅展示配置了打开方式的连接。已有的双入口配置通过兼容适配器继续支持。配置示例、凭据处理及入口要求见 [Codex 连接配置](docs/codex-connections.md)。

人工聊天保存实际连接 ID，再次打开沿用绑定；连接不可用时显示原因，不自动改用另一个账号。凭据只注入对应子进程，不写入任务记录或日志。

如果错误包含 `Missing environment variable`，请检查 Codex 当前 provider 的 `env_key`，并确保启动 DevConductor 的进程已导出这个变量。Hub 启动项目 Worker 时继承自身环境，Worker 再将环境传给 Codex；在另一个终端或 Codex App 中配置变量不会更新已经运行的 Hub。

等后台任务结束后，停止旧服务，再从已配置该变量的终端运行 `./start.command`，刷新页面后重试。旧服务仍在时，`start.command` 只会打开现有页面。密钥应通过环境变量提供，不要填进需求、Profile 或任务日志。具体配置见 [Codex 官方配置参考](https://developers.openai.com/codex/config-reference/)。

控制台会保留 Codex JSON 失败事件及 stderr 的具体原因；失败后仍可展开“查看真实状态记录”查看该阶段日志。

### 快速模式为什么更快？

平台现在有两层提速：新建时选择“轻量直改”，可省去 discussion 和完整 Plan/HTML 两个前置 Agent 轮次；执行时选择“快速修改”，会复用当前需求的后台执行 Thread，把实现和自检合并为一轮，不再等待第二个独立 Review。人工验收和 Commit 门禁仍然保留；共享逻辑或高风险改动建议使用标准需求与标准执行。

### 不打开 Codex App 还能使用吗？

可以。标准流程继续使用原有 `codex exec`。选择快速模式时，服务会自动创建或恢复后台执行 Thread；“打开 Codex App”使用另一个独立人工聊天，即使完全不打开也不影响执行流程。

### 会自动 Push 或合并吗？

不会。当前流程最多执行本地 Commit，Push 和 Merge 不在控制台授权范围内。

### 可以不让控制台执行 Commit 吗？

可以。你可以人工提交，然后点击“确认已人工提交”。控制台只记录当前 HEAD，不会再次执行 Git Commit。

## GitHub 发布前检查

本地 Project Profile 通常包含机器绝对路径，因此 `.gitignore` 默认排除 `profiles/*.json`，只提交 `profiles/example.json`。

建议发布前完成：

1. 确认只提交不含个人路径的 `profiles/example.json`。
2. 确认 `.runtime/`、上传文档、任务状态和日志没有进入 Git。
3. 搜索用户名、绝对路径、项目私有地址和内部 Skill 名称。
4. 补充合适的 `LICENSE`；当前工具没有替你选择开源许可证。
5. 在一个临时 Git 项目上重新执行 dry-run、Profile 生成和完整测试。

## License

尚未指定。发布到 GitHub 前请根据项目用途添加合适的许可证文件。
