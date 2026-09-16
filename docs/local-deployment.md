# DevConductor 本机部署指南

这份指南用于把 DevConductor 分享给其他人，让每位使用者在自己的电脑上运行独立实例。

兼容说明：GitHub 仓库地址、`$project-flow-setup` Skill 名称和 `PROJECT_FLOW_*` 环境变量暂时保留旧技术标识；已有安装不需要重命名目录或迁移任务数据。

推荐模式是：共享同一个 GitHub 工具仓库，但每个人分别维护自己的 Project Profile、任务状态、项目仓库和 Worktree。不要把控制台部署成一台多人共用的远程服务。

需要跨电脑、跨成员共享稳定工程记忆时，只共享独立的 Memory Hub，不共享控制台本身。Memory Hub 的部署、API Key、SQLite 备份和 Codex Plugin 配置见 [共享 Memory Hub 与 Codex Plugin](memory-hub.md)。

## 一、部署模型

每位使用者的电脑上包含四类内容：

1. `dev-conductor`：可通过 Git 更新的公共工具代码。
2. 主项目仓库：实际开发项目的主 Git checkout。
3. `worktrees`：控制台为需求创建的隔离执行目录，底层使用 Git Worktree，但不要求使用者手工管理。
4. `docs` 与 `.runtime`：需求文档、验收 HTML，以及只属于当前电脑的任务状态。

控制台只监听 `127.0.0.1`，其他电脑无法直接访问。页面中的 Codex、Worktree 和 Commit 操作都发生在当前使用者自己的电脑上。

## 二、目录选择策略

不要要求所有同事采用同一套项目目录。`project-flow-setup` 的选择顺序是：

| 优先级 | 场景 | 处理方式 |
|---|---|---|
| 1 | 用户显式填写目录 | 使用填写的绝对路径，并执行安全校验 |
| 2 | 项目已有文档或外部 Worktree 目录 | 保留项目原位并复用已有规范 |
| 3 | 没有可识别的项目规范 | 使用本机 `~/ProjectFlowData/<project-id>` 托管目录 |

Skill 只在发现多个可信候选目录、且选择会改变行为时询问。Dry-run 不移动项目、不创建 Worktree，也不创建托管目录。

### 普通同事：保持项目原位

这是没有 Git Worktree 使用习惯时的默认方案：

```text
/Users/alice/Projects/
└── my-game/                            # repoRoot，原项目保持不动

/Users/alice/ProjectFlowData/
└── my-game/
    ├── docs/                           # docsRoot
    │   └── tasks/active/               # htmlTaskRoot
    └── worktrees/                      # worktreesRoot，由控制台管理
        ├── MyGame-add-login-a1b2/
        └── MyGame-fix-payment-c3d4/

/Users/alice/Developer/tools/
└── dev-conductor/                      # DevConductor 工具代码
```

对应的 Profile 路径如下：

| Profile 字段 | 示例 |
|---|---|
| `workspaceRoot` | `/Users/alice/Projects` |
| `repoRoot` | `/Users/alice/Projects/my-game` |
| `docsRoot` | `/Users/alice/ProjectFlowData/my-game/docs` |
| `htmlTaskRoot` | `/Users/alice/ProjectFlowData/my-game/docs/tasks/active` |
| `worktreesRoot` | `/Users/alice/ProjectFlowData/my-game/worktrees` |

同事只需要在页面点击“创建隔离执行目录”。控制台负责创建、绑定和校验 Git Worktree；原项目分支不会被自动切换。

### 已有团队目录：直接复用

如果项目已有类似结构，Skill 应优先识别并复用：

```text
/Users/alice/CompanyWorkspace/
├── Client/                             # repoRoot
├── ClientDocs/                         # 已有 docsRoot
└── worktrees/                          # 已有 worktreesRoot
```

不需要为了匹配文档示例移动 `Client`，也不需要另建 `ProjectFlowData`。Dry-run 会展示检测结果，由使用者确认后写入 Profile。

### 新项目：可选的整理结构

只有新项目或团队本来就希望整理目录时，才建议使用同级结构：

```text
/Users/alice/Developer/
├── tools/dev-conductor/
└── workspaces/my-game/                 # workspaceRoot
    ├── repo/                           # repoRoot
    ├── docs/                           # docsRoot
    │   └── tasks/active/               # htmlTaskRoot
    └── worktrees/                      # worktreesRoot
```

关键约束只有一个：`worktrees` 必须在 `repo` 外；目录名称和现有项目位置不需要统一。

项目内的执行 Plan 使用仓库相对路径，例如：

```json
"planRelativeDir": "Docs/plans/active"
```

创建 Worktree 后，正式 Plan 会放到该 Worktree 的 `Docs/plans/active` 中；逻辑验收 HTML 和控制台文档仍保存在外部 `docsRoot`。

## 三、路径规则

配置前必须确认以下规则：

- Profile 中的根目录使用展开后的绝对路径，例如 `/Users/alice/Developer/...`。
- 不要在 Profile JSON 中写 `~`、`$HOME`、`${USER}` 或依赖当前目录的相对路径。
- `repoRoot` 必须准确指向 `git rev-parse --show-toplevel` 返回的主仓库根目录。
- `worktreesRoot` 不能等于 `repoRoot`，也不能位于 `repoRoot` 内部。
- 不要使用 `repo/.worktrees`、`repo/worktrees` 之类的目录。
- `htmlTaskRoot` 必须位于 `docsRoot` 内。
- `planRelativeDir`、`projectFacts` 和 `planTemplate` 是仓库内相对路径，不能包含 `..`。
- `worktreeNamePrefix` 只能使用字母、数字、点、下划线和连字符，建议使用 `MyGame` 这类短名称。
- 没有 Worktree 使用习惯时，不需要手工执行 Git 命令；把 `worktreesRoot` 视为控制台管理的隔离执行目录即可。
- 根目录建议使用 ASCII、小写且不包含空格，例如 `dev-conductor`、`my-game`；这不是强制要求，但能减少外部脚本和终端引用路径时的转义问题。
- 每个人都应重新生成自己的 Profile，不要直接复制包含其他人用户名和绝对路径的 Profile。

## 四、安装前检查

需要准备：

- Python 3.10 或更高版本
- Git，并支持 `git worktree`
- 已安装并能正常运行的 Codex CLI
- 一个非 detached HEAD 的本地 Git 项目

检查命令：

```bash
python3 --version
git --version
git worktree list
codex --version
```

Codex App 是可选项。没有安装 Codex App 时，仍可使用基于 `codex exec` 的标准流程。

### 可选：读取链接需求文档

链接需求可先保存正文、核对覆盖和附件策略，再手动开始讨论。默认情况下，飞书 / Lark 链接采用正文导入，普通公开链接由后台 Codex 在讨论中直接只读访问。

- **通用正文导入**：从有权限的浏览器、文档工具或其他渠道获取正文，再导入并核对覆盖；无需 Chrome、插件或 Codex 桌面。旧 `chrome_mcp` 任务继续支持导入。控制台没有实现后台自动 Chrome 读取。
- **官方 Lark CLI**：安装 `lark-cli` 并完成当前用户的飞书授权，可自动读取支持的飞书 / Lark 文档链接。可用性以可执行文件和 `user` 授权为准；`lark-shared`、`lark-wiki`、`lark-doc` Skills 缺失仅显示诊断提示。

Lark CLI 由服务进程直接调用，需能在启动控制台的用户及环境下访问本机凭据。可在同一启动终端检查 `lark-cli --version` 和 `lark-cli auth status --json`；若控制台找不到 CLI，可设置 `PROJECT_FLOW_LARK_CLI_BIN` 为可执行文件的绝对路径后重启服务。状态检查通过仍需实际文档权限，内嵌表格还可能需要表格只读权限。

读取成功后，服务端对 Lark CLI 返回的原文、章节和表格完整性元数据做确定性校验并保存，不依赖后台 Codex 二次复核。附件默认可选，未读附件和引用保留提示；任务选择附件必读时，必须补齐全部未读项才能继续。后台 Codex 连接用于后续讨论。讨论阶段空闲时可显式切换导入 / Lark CLI 或调整附件策略；切换读取方式须重新读取或保存，调整策略会重新判断已存材料是否就绪。Codex 连接与 Lark 凭据的区别见 [Codex 连接配置](codex-connections.md#文档读取的环境边界)。

项目可在 Profile 增加以下可选默认值，新任务仍可覆盖：

```json
{
  "sourceReading": {
    "defaultReader": "auto",
    "attachmentPolicy": "optional"
  }
}
```

`defaultReader` 支持 `auto`、`manual_import`、`lark_cli`、`codex_read_only`。`auto` 对 Lark 链接选择导入，对普通公开链接选择 Codex 直接只读；附件必读时选择导入。`lark_cli` 默认值遇其他链接会回退导入；`codex_read_only` 默认值遇 Lark 或附件必读也会回退导入。用户显式选择不适用的组合会报错。配置只包含这些固定选项，不允许自定义命令或路径。

这些默认值固化到新任务，旧任务不随 Profile 变更收紧；未保存附件策略的旧任务仍为 `optional`。已有独立材料步骤的任务不能改为直接只读来绕过门禁。完整配置与任务规则见 [链接文档读取](../README.md#链接文档读取)及 [Profile Schema](../skills/project-flow-setup/references/profile-schema.md#source-reading-defaults)。

## 五、下载控制台

建议将工具克隆到独立的 `tools` 目录，不要放进目标项目仓库：

```bash
mkdir -p ~/Developer/tools
cd ~/Developer/tools
git clone https://github.com/CandyAlla/project-flow-console.git dev-conductor
cd dev-conductor
```

服务端只使用 Python 标准库，不需要执行 `pip install`。

## 六、安装配置 Skill

`project-flow-setup` 是为不同电脑和项目生成安全 Profile 的统一入口。

macOS / Linux 推荐使用软链接：

```bash
mkdir -p ~/.codex/skills
ln -s "$PWD/skills/project-flow-setup" ~/.codex/skills/project-flow-setup
```

如果目标已经存在，先检查，不要直接覆盖：

```bash
ls -la ~/.codex/skills/project-flow-setup
```

如果它已经指向当前控制台目录，则不需要重复创建。更新控制台仓库后，软链接会自动使用最新版 Skill。

## 七、为本机项目生成 Profile

先获取项目的真实绝对路径：

```bash
cd /path/to/your-project
git rev-parse --show-toplevel
```

然后新建一个 Codex 任务并输入：

```text
使用 $project-flow-setup 配置 /absolute/path/to/your-project
```

Skill 会先执行只读 dry-run，展示：

- 主仓库和基准分支
- `workspaceRoot`、`docsRoot` 与 `worktreesRoot`
- Plan、HTML 和项目事实入口
- 各阶段使用的 Skills
- 日志与人工验证来源
- 路径冲突和缺失项
- 哪些目录复用了项目现有规范，哪些目录使用了本机托管 fallback

确认 dry-run 后才生成：

```text
dev-conductor/profiles/<project-id>.json
```

也可以直接运行脚本：

```bash
cd ~/Developer/tools/dev-conductor

python3 skills/project-flow-setup/scripts/configure_project.py \
  /absolute/path/to/your-project \
  --dry-run

python3 skills/project-flow-setup/scripts/configure_project.py \
  /absolute/path/to/your-project
```

没有现有目录规范时，脚本默认推荐：

```text
~/ProjectFlowData/<project-id>/docs
~/ProjectFlowData/<project-id>/worktrees
```

如果公司要求把托管数据统一放到其他磁盘，可以只覆盖 fallback 根目录：

```bash
python3 skills/project-flow-setup/scripts/configure_project.py \
  /absolute/path/to/your-project \
  --managed-root /Volumes/Development/ProjectFlowData \
  --dry-run
```

只有在 dry-run 自动识别的路径不符合预期时，才显式传入目录参数：

```bash
python3 skills/project-flow-setup/scripts/configure_project.py \
  /Users/alice/Developer/workspaces/my-game/repo \
  --name "My Game" \
  --id my-game \
  --workspace-root /Users/alice/Developer/workspaces/my-game \
  --docs-root /Users/alice/Developer/workspaces/my-game/docs \
  --worktrees-root /Users/alice/Developer/workspaces/my-game/worktrees \
  --html-task-root /Users/alice/Developer/workspaces/my-game/docs/tasks/active \
  --plan-dir Docs/plans/active \
  --dry-run
```

不要跳过 dry-run，也不要为了省事手工复制别人的 Profile。

## 八、启动本地控制台

macOS 推荐直接启动多项目 Hub：

```bash
cd ~/Developer/tools/dev-conductor
./start.command
```

也可以直接使用 Python：

```bash
python3 hub.py --port 4318
```

Hub 会自动发现 `profiles/*.json`。左侧项目轨道可切换项目；“所有项目”首页集中显示项目、任务和跨项目沉淀。点击“添加项目”可以先 dry-run 扫描本地 Git 项目，或接入已有 Project Profile。

没有任何 Profile 时 Hub 仍可启动，并直接显示添加项目入口，不需要先手工创建占位配置。

如果默认端口上已经运行旧的单项目服务，`start.command` 会保留并打开现有服务，不会中断其后台任务。完成任务并正常停止旧服务后，再次启动即可切换到 Hub。

每个项目使用独立 Worker 进程，切换页面不会替换其他项目的 Profile，也不会停止其后台任务。

同一项目运行目录带有单控制器锁；重复启动不会接管或覆盖现有任务状态，而会提示继续使用原服务或先正常停止它。

Linux 或没有使用 `start.command` 时，运行 `hub.py`，再手动打开启动日志中的地址。

默认地址：

```text
http://127.0.0.1:4318/
```

健康检查：

```bash
curl --fail http://127.0.0.1:4318/api/hub/projects
```

终端按 `Ctrl-C` 可以停止服务。

## 九、多个项目或端口冲突

默认使用一个 Hub 统一管理多个 Profile：

```text
Project Hub :4318
  ├── Project A Worker → Profile A → Repo A / .runtime/A
  ├── Project B Worker → Profile B → Repo B / .runtime/B
  └── Project C Worker → Profile C → Repo C / .runtime/C
```

Worker 使用 Hub 分配的本机内部端口，不需要为每个 Profile 手工维护端口。默认单项目最多并行 8 个后台任务，所有项目合计最多 16 个：

```bash
PROJECT_FLOW_PROJECT_CONCURRENCY=8 \
PROJECT_FLOW_GLOBAL_CONCURRENCY=16 \
python3 hub.py
```

如果只想运行旧的单项目界面，可以继续显式指定 Profile：

```bash
PROJECT_FLOW_PROFILE="$PWD/profiles/game-client.json" \
python3 server.py --port 4318
```

`id` 不同的 Profile 会把任务状态隔离到：

```text
.runtime/<project-id>/tasks/
```

## 十、更新与备份

更新公共工具：

```bash
cd ~/Developer/tools/dev-conductor
git pull --ff-only
```

更新代码后，等待后台任务结束，正常停止并重新启动 Hub 或单项目服务，再刷新页面。重复点击 `start.command` 会复用已运行服务，不会替它加载新代码；修改 `CODEX_HOME`、CLI 路径或其他启动环境变量，也需要从目标环境重新启动服务。Codex 独立连接的配置生效规则见 [Codex 连接配置](codex-connections.md)。

如果已保存的文档材料可继续讨论，页面却仍显示旧提示，先完整刷新页面（macOS 为 `⌘R`）核对当前状态。导入表单中尚未保存的草稿会随刷新丢失，应先保存。

本机 Profile、任务状态和上传截图默认不会进入 Git：

- `profiles/<project-id>.json`
- `.runtime/<project-id>/tasks/`
- `.runtime/<project-id>/tasks/<task-id>/feedback-images/`
- `.runtime/hub/projects.json`
- `.runtime/hub/logs/`
- `.runtime/hub/job-slots/`
- `.runtime/memory/memory.db`
- `.runtime/memory/api-key`

如需备份任务状态，可在停止服务后备份 `.runtime/<project-id>`。本机 Memory Hub 则备份 `.runtime/memory`。不要把其中的需求文档、日志、截图、记忆数据库、API Key 或绝对路径提交到公共 GitHub 仓库。

## 十一、分享给同事时应提供什么

给同事发送以下内容即可：

1. GitHub 仓库地址。
2. 这份本机部署指南。
3. 目标项目仓库的访问方式和推荐基准分支。
4. 项目必须安装的 Skills 清单。
5. 项目的日志、测试和人工验收约定。

不要发送：

- 自己的 `profiles/<project-id>.json`
- `.runtime/` 目录
- Codex session、App Thread 或认证信息
- 飞书 Token、App Secret 或浏览器登录数据
- 已包含本机用户名的启动脚本

每位同事完成 Git clone 后，都应在自己的电脑上重新运行 `$project-flow-setup`。

## 十二、常见路径错误

### Worktree 放在主仓库里

错误：

```text
/Users/alice/Projects/my-game/.worktrees
```

正确：

```text
/Users/alice/ProjectFlowData/my-game/worktrees
```

### Profile 使用其他人的路径

如果启动日志显示 `/Users/bob/...`，但当前使用者不是 `bob`，应重新运行 `$project-flow-setup`，不要逐项搜索替换 JSON。

### Profile 使用相对路径或环境变量

错误：

```json
"repoRoot": "$HOME/Projects/my-game"
```

正确：

```json
"repoRoot": "/Users/alice/Projects/my-game"
```

### 端口已经占用

临时选择另一个本地端口：

```bash
PROJECT_FLOW_PROFILE="$PWD/profiles/my-game.json" \
python3 server.py --port 4320
```

浏览器打开 `http://127.0.0.1:4320/`。

## 十三、安全边界

- 服务只监听 `127.0.0.1`，不要使用端口转发或反向代理把它公开到局域网或互联网。
- 修改类 API 需要当前本地服务生成的会话令牌。
- 控制台不会自动 Fetch、Pull、Push 或 Merge。
- Worktree、Commit、Bug 修复等写操作仍需要页面中的人工按钮授权。
- Profile 是声明式路径和 Skill 配置，不应包含 Shell 命令、Token 或账号信息。
- 使用前应核对 Profile 指向的仓库、文档根目录和 Worktree 根目录。
