# Codex 连接配置

普通安装不需要连接配置文件。DevConductor 沿用启动服务时的 Codex 环境，在桌面提供“默认 Codex 环境”这一项；不会要求同时配置 API 和账号登录，也不会显示无法执行的登录切换选项。

默认环境指服务进程继承的 `CODEX_HOME`、环境变量和 Codex 配置；未设置 `CODEX_HOME` 时使用 Codex 的默认目录。外部应用后来切换登录或目录，不会改变已经启动的服务进程。应从与桌面 Codex 一致的环境启动控制台，或显式配置对应连接。

## 可选的独立连接

需要单独指定后台执行环境，或使用多个桌面入口时，在工具目录创建 `.runtime/codex-connections.json`：

```json
{
  "version": 2,
  "backgroundConnection": "default",
  "defaultDesktopConnection": "personal",
  "connections": {
    "personal": {
      "label": "个人账号",
      "home": "/absolute/path/to/codex-home",
      "desktop": {
        "type": "current"
      }
    }
  }
}
```

这个例子只配置一条命名连接；界面也会保留默认环境入口。`current` 要求 `home` 与服务继承的 Codex 目录一致，桌面也应使用同一个目录。若服务设置了 `CODEX_SQLITE_HOME`，请使用默认环境或能明确选择对应环境的 `command` 入口。没有额外桌面入口的普通安装，直接省略整个配置文件更简单。

| 字段 | 含义 |
| --- | --- |
| `version` | 新配置使用 `2` |
| `backgroundConnection` | 后台讨论、Plan、Ask、执行和 Review 使用的连接 ID；省略为 `default` |
| `defaultDesktopConnection` | 新聊天默认选择的连接 ID；省略为 `default` |
| `connections` | 可为空，也可以只有一条或多条；ID 自定义，`default` 保留给默认环境 |
| `label` | 界面显示的连接名称 |
| `home` | 该连接的 Codex 配置与聊天目录，必须是已有绝对路径 |
| `config` | 可选的 Codex 扁平配置覆盖，只支持字符串、布尔值和有限数字 |
| `envKey` | 可选的凭据环境变量名，可使用启动服务时已有的值 |
| `credentialFile` | 可选的本地 JSON 凭据文件；使用时必须指定 `envKey` |
| `credentialKey` | 凭据文件中的字段，省略为 `OPENAI_API_KEY` |
| `desktop` | 可选的桌面打开方式；省略则该连接只用于后台，不出现在聊天选择列表 |

后台连接与桌面选择相互独立。例如将 `backgroundConnection` 设为 `automation`，并配置一个没有 `desktop` 的 `automation` 连接，后台就会使用它，桌面聊天仍可以使用默认环境。

文档读取页面会显示后续讨论使用的后台连接名称；桌面聊天的连接选择不会改变它。这个名称来自当前配置，不代表该连接已经通过认证或完成读取。

每个 App Server 进程使用启动时读取的连接配置快照。修改连接配置会影响后续启动的进程，正在执行的轮次继续使用原来的目录、凭据和模型覆盖值。`config` 不允许覆盖 `sqlite_home` 或选择其他 `profile`，目录由 `home` 明确指定。

独立连接会清理继承的 API 凭据和 SQLite 目录覆盖，再注入该连接明确指定的凭据。没有凭据覆盖时，Codex 可使用其 `home` 中已有的登录配置。凭据文件无法读取或字段无效会报错，不会改用别的连接。服务不复制认证文件或聊天记录。

## 文档读取的环境边界

- 官方 Lark CLI 由控制台服务直接调用，以 `user` 身份读取正文和内嵌表格，使用服务继承的环境及本机飞书凭据。`backgroundConnection` 中的 Codex 目录和凭据覆盖不会应用到 Lark CLI。
- Lark CLI 可用性检查要求可执行文件和 `user` 授权有效；`lark-shared`、`lark-wiki`、`lark-doc` Skills 缺失仅作诊断提示。读取后，服务端对 CLI 返回的原文、章节和表格完整性元数据做确定性校验并保存，不调用后台 Codex 二次复核。后台 Codex 连接只用于后续讨论。
- 通用正文导入（`manual_import`）接受用户从有权限的渠道取得的文档内容，覆盖情况由用户核对，无需 Chrome 或 Codex 桌面。旧 `chrome_mcp` 任务兼容该流程；控制台没有新增后台自动 Chrome 读取。保存后，材料满足当前策略即可开始或恢复讨论。
- 普通公开链接可使用 `codex_read_only`，由后台 Codex 在讨论中只读访问；飞书 / Lark 链接和附件必读任务须先通过导入或 Lark CLI 准备材料。

Profile 的 `sourceReading` 只定义新任务的默认读取方式与附件策略；任务保存自己的选择，不受之后的 Profile 默认值变更影响。它不选择 Codex 连接，也不配置命令或凭据路径。默认解析、附件必读及旧任务兼容规则见 [链接文档读取](../README.md#链接文档读取)。

遇到 `lark_credentials_unavailable`，检查启动服务的用户及本机凭据存储访问环境（macOS 包括钥匙串）。后台 Codex 连接错误只影响开始或恢复讨论，不影响已完成的 Lark CLI 读取。按页面错误处理对应环节后再重试，文档读取重试会保留已保存材料和原讨论会话。讨论阶段空闲时也可显式切换正文导入 / Lark CLI；切换后须重新读取或保存材料，再继续讨论。

## 独立桌面入口

如果某条连接使用不同的 Codex 目录，需要提供能打开该目录下聊天的入口：

```json
{
  "type": "command",
  "command": ["/absolute/path/to/open-my-codex", "{url}"]
}
```

把它作为该连接的 `desktop` 字段。第一个参数必须是可执行文件的绝对路径；`{url}` 必须作为独立参数出现且只出现一次。入口负责选择正确的 Codex 环境并打开收到的聊天链接。控制台直接传递参数，不执行 shell 命令字符串。

默认入口按操作系统打开 Codex 链接；自定义入口文件缺失、没有执行权限、目录不匹配等情况会在界面标记为不可用，并说明原因。只有可用连接才允许创建或打开聊天。

## 现有双入口配置

旧版包含 `switcherStatePath`、`baseHome`、`desktopApp`、`connections.api` 和 `connections.account` 的配置继续支持。服务在内存中通过兼容适配器读取它，不改写原配置，不迁移历史聊天。

旧切换器的 `homes_ready`、`active` 状态和桌面启动器只属于这个适配器；普通配置无需提供这些字段。旧配置继续保持后台固定使用原 API 连接，并支持其原有的初始化前目录规则。

## 聊天绑定与更新

- 新聊天保存具体连接 ID；再次打开沿用该 ID，不受新聊天选择影响。
- 没有连接记录的旧绑定会在可用连接中检查；找到后补存连接，保留原聊天。
- 已绑定的连接被移除或不可用时，界面会提示恢复配置或新建聊天，不会自动切换到另一个账号。
- 手动选择的连接失效时需要重新选择；普通切页不会把自动默认值保存为手动选择。
- 更新服务代码后，等待后台任务结束，再重启控制台并刷新页面。重复点击 `start.command` 会复用已运行的服务。

`.runtime` 属于本机配置，不应提交到 Git。只在其中保存必要的路径与连接设置，凭据保持在本地凭据文件或进程环境中。
