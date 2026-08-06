# Project Flow Console 本机部署指南

这份指南用于把 Project Flow Console 分享给其他人，让每位使用者在自己的电脑上运行独立实例。

推荐模式是：共享同一个 GitHub 工具仓库，但每个人分别维护自己的 Project Profile、任务状态、项目仓库和 Worktree。不要把控制台部署成一台多人共用的远程服务。

## 一、部署模型

每位使用者的电脑上包含四类内容：

1. `project-flow-console`：可通过 Git 更新的公共工具代码。
2. 主项目仓库：实际开发项目的主 Git checkout。
3. `worktrees`：控制台为需求创建的隔离 Git Worktree。
4. `docs` 与 `.runtime`：需求文档、验收 HTML，以及只属于当前电脑的任务状态。

控制台只监听 `127.0.0.1`，其他电脑无法直接访问。页面中的 Codex、Worktree 和 Commit 操作都发生在当前使用者自己的电脑上。

## 二、推荐目录结构

### 新项目或可以整理目录时

推荐把公共工具与项目工作区分开：

```text
/Users/alice/Developer/
├── tools/
│   └── project-flow-console/          # 公共控制台代码
└── workspaces/
    └── my-game/                       # workspaceRoot
        ├── repo/                      # repoRoot，主 Git 仓库
        ├── docs/                      # docsRoot，仓库外的需求文档
        │   └── tasks/
        │       ├── active/            # htmlTaskRoot
        │       └── archive/
        └── worktrees/                 # worktreesRoot，必须在 repo 外
            ├── MyGame-add-login-a1b2/
            └── MyGame-fix-payment-c3d4/
```

示例中的 `repo` 可以换成真实仓库名；关键是它与 `docs`、`worktrees` 保持同级，而不是把 Worktree 目录放进 Git 仓库。

对应的 Profile 路径如下：

| Profile 字段 | 示例 |
|---|---|
| `workspaceRoot` | `/Users/alice/Developer/workspaces/my-game` |
| `repoRoot` | `/Users/alice/Developer/workspaces/my-game/repo` |
| `docsRoot` | `/Users/alice/Developer/workspaces/my-game/docs` |
| `htmlTaskRoot` | `/Users/alice/Developer/workspaces/my-game/docs/tasks/active` |
| `worktreesRoot` | `/Users/alice/Developer/workspaces/my-game/worktrees` |

项目内的执行 Plan 仍使用仓库相对路径，例如：

```json
"planRelativeDir": "Docs/plans/active"
```

创建 Worktree 后，正式 Plan 会放到该 Worktree 的 `Docs/plans/active` 中；逻辑验收 HTML 和控制台文档仍保存在外部 `docsRoot`。

### 已有项目不方便搬家时

不需要为了使用控制台移动现有仓库。可以保留原位置，只把控制台数据和 Worktree 放到独立目录：

```text
/Users/alice/Projects/
└── my-game/                            # repoRoot，保持原位置

/Users/alice/ProjectFlowData/
└── my-game/
    ├── docs/                           # docsRoot
    │   └── tasks/active/               # htmlTaskRoot
    └── worktrees/                      # worktreesRoot

/Users/alice/Developer/tools/
└── project-flow-console/               # 控制台代码
```

这时 `workspaceRoot` 可以设为 `/Users/alice/Projects`，已有需求文档也可以从单独配置的 `docsRoot` 接入。

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
- 根目录建议使用 ASCII、小写且不包含空格，例如 `project-flow-console`、`my-game`；这不是强制要求，但能减少外部脚本和终端引用路径时的转义问题。
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

## 五、下载控制台

建议将工具克隆到独立的 `tools` 目录，不要放进目标项目仓库：

```bash
mkdir -p ~/Developer/tools
cd ~/Developer/tools
git clone https://github.com/CandyAlla/project-flow-console.git
cd project-flow-console
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

确认 dry-run 后才生成：

```text
project-flow-console/profiles/<project-id>.json
```

也可以直接运行脚本：

```bash
cd ~/Developer/tools/project-flow-console

python3 skills/project-flow-setup/scripts/configure_project.py \
  /absolute/path/to/your-project \
  --dry-run

python3 skills/project-flow-setup/scripts/configure_project.py \
  /absolute/path/to/your-project
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

macOS 推荐显式指定 Profile：

```bash
cd ~/Developer/tools/project-flow-console

PROJECT_FLOW_PROFILE="$PWD/profiles/my-game.json" \
./start.command
```

也可以直接使用 Python：

```bash
PROJECT_FLOW_PROFILE="$PWD/profiles/my-game.json" \
python3 server.py
```

Linux 或 Windows 没有使用 `start.command` 时，运行 `server.py`，再手动打开启动日志中的地址。

默认地址：

```text
http://127.0.0.1:4318/
```

健康检查：

```bash
curl --fail http://127.0.0.1:4318/api/health
```

终端按 `Ctrl-C` 可以停止服务。

## 九、多个项目或端口冲突

同一份控制台可以维护多个 Profile，但每个服务进程一次加载一个 Profile。

如果只运行一个项目，建议始终显式指定 Profile。多个项目同时运行时，为每个进程使用不同端口：

```bash
PROJECT_FLOW_PROFILE="$PWD/profiles/game-client.json" \
python3 server.py --port 4318

PROJECT_FLOW_PROFILE="$PWD/profiles/backend-api.json" \
python3 server.py --port 4319
```

`id` 不同的 Profile 会把任务状态隔离到：

```text
.runtime/<project-id>/tasks/
```

## 十、更新与备份

更新公共工具：

```bash
cd ~/Developer/tools/project-flow-console
git pull --ff-only
```

本机 Profile、任务状态和上传截图默认不会进入 Git：

- `profiles/<project-id>.json`
- `.runtime/<project-id>/tasks/`
- `.runtime/<project-id>/tasks/<task-id>/feedback-images/`

如需备份任务状态，可在停止服务后备份 `.runtime/<project-id>`。不要把其中的需求文档、日志、截图或绝对路径提交到公共 GitHub 仓库。

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
