# Spug 轻量化运维版 使用说明

> 面向 Windows 单机便携部署：内置私有 Python runtime，不写注册表、不改 PATH；
> 被管 Linux 主机不需要安装 Python。

## 1. 启动与登录

1. 将整个 `Spug` 目录放到可写路径（如 `D:\Spug`，不要放 `Program Files`）。
2. 双击 `Spug.exe`：首次自动建库并创建管理员 `admin / admin`，启动服务并打开浏览器，
   随后驻留系统托盘（托盘菜单：打开界面 / 退出）。
3. 修改监听地址/端口：编辑同目录 `spug.ini`：

```ini
[server]
host = 0.0.0.0
port = 9000
```

4. 数据（SQLite/日志/仓库）都在 `data\`；备份整个 `data\` 即可。

## 2. 添加主机

「主机管理 → 新建主机」：

- 认证方式二选一：
  - **密码**：填写 SSH 登录密码（保存在本机 SQLite，接口不返回原文）；
  - **密钥**：上传独立私钥，或使用系统设置里的全局密钥。
- 选择分组后保存，Spug 会立即验证连通性。
- 主机列表「系统」列显示 Facts 采集结果；「卡片」按钮可看卡片视图；
  「Facts」可查看/刷新缓存。

## 3. 批量执行状态模块

「批量执行 → 执行任务」：

1. 选择目标主机；
2. 任务类型选「状态模块」；
3. 选择模块（软件包/文件/目录/服务/用户）并填表单；
4. 可打开 **Dry-run 预览**（只计算将要下发的命令，不修改主机）；
5. 开始执行，右侧控制台实时输出，结果含 changed/failed/diff。

文件模块的「使用模板」可选择配置模板，按每台主机的 Facts/变量渲染后推送。

## 4. 流水线

「流水线 → 编辑」：

- 节点支持：执行命令、构建、数据传输/上传、参数化、状态模块、Facts 刷新、通知。
- 状态模块节点执行完会输出 `changed/failed`，下游条件可选：
  `上游有变更时 / 上游无变更时 / 上游成功 / 上游失败 / 总是执行`。
- 列表页「执行」正常收敛；「Dry-run」只巡检不改机器。
- 编辑器顶部「存为基线」可把当前流水线的状态模块节点保存为基线。

## 4.1 制品拉取节点（raw / rpm / deb）

流水线新增节点「制品拉取」，用于从外部制品库消费制品（不做上传/浏览）：

- **raw**：HTTP 静态文件/NORA raw。Dry-run 只做 HEAD 探测；真实执行用 `curl` 下载，
  按文件大小与「覆盖」开关判断是否需要重新下载，已是最新输出 unchanged。
- **rpm**：把仓库地址写成 `/etc/yum.repos.d/spug-artifact-<节点>.repo`，
  再用包管理器安装（复用 pkg 模块的幂等/dry-run）。Basic 用 `username/password`，
  Bearer 用 `http_headers`。
- **deb**：把仓库地址写成 `/etc/apt/sources.list.d/spug-artifact-<节点>.list`，
  再用包管理器安装（带 10 分钟 update 缓存以保证幂等）。Basic 用 URL 内嵌凭据；
  **deb 不支持 Bearer**（apt 限制）。
- 表单：源类型、源地址（填到仓库根，如 `https://host/rpm`）、仓库名、包名、版本号；
  deb 额外需要 `suite`（如 noble）与 `component`（如 main）。
- 若远端主机**系统里已经配置了同一个仓库**，节点会跳过写源配置，避免 apt/yum 的
  Trusted 选项冲突。
- 非 root 主机写 `/etc` 需要 sudo：请在该主机保存登录密码，节点会通过 SSH 加密通道
  传给 `sudo -S`，不会出现在命令行或日志里。
- 日志只显示「已配置 Bearer/Basic 认证」，不会输出 token/账号密码。
- 凭据复用「系统管理 → 凭据管理」，与 Spug 原生一致以明文存本机 SQLite（接口不回显）。

## 4.2 状态模块清单

| 模块 | 用途 |
|---|---|
| 软件包 pkg | 安装/卸载/升级，自动识别 Debian/RedHat/Alpine，RedHat 系自动区分 yum（CentOS 7）与 dnf（8+） |
| 文件 file | 存在性/内容/权限，内容可用 Jinja2 模板 |
| 目录 directory | 目录创建/删除/权限/递归 |
| 服务 service | 启停/开机自启/重启，自动选择 systemd/sysvinit |
| 用户 user | 系统用户创建/删除/属性/密钥 |
| 用户组 group | 系统组创建/删除 |
| 原生命令 command | 执行 shell 命令（幂等由命令自身保证） |
| 配置行 line | 管理文件中某一行（增/删/替换） |
| 配置块 block | 用标记管理文件中的一段内容 |
| 内核参数 sysctl | sysctl 设置与持久化 |
| 定时任务 crontab | 远端 crontab 条目（按名称幂等） |
| 远端下载 download | 目标主机上用 curl/wget 下载 URL |

## 5. 定时任务

「任务计划 → 新建」：

- 任务内容三选一：脚本 / 状态模块 / Facts 刷新；
- 状态模块可勾选「Dry-run 巡检」；
- 通知：无变更静默；有变更/巡检漂移/失败时汇总一条（钉钉/飞书/企微/Webhook）。

## 6. 运维增强

- **变更日志**：所有 changed/failed 时间线，可按来源/主机/结果筛选，查看命令与输出。
- **配置模板**：Jinja2 模板库，支持历史版本与逐行对比；可引用 Facts/主机变量/分组变量。
- **基线管理**：多个状态模块节点组合，一键收敛 / 一键巡检。
- **变量管理**：主机变量、分组变量（优先级：主机 > 分组 > Facts > 流水线）。
- **动态分组**：基于 Facts 规则自动维护成员（如 `os_family = Debian`）。

## 6.1 变量上下文预览面板

流水线编辑页右侧箭头展开「可用变量」面板：

- 顶部下拉选择预览主机（仅当前流水线绑定的主机）；不选主机时只看变量清单；
- 选中主机后展示每个变量的真实值 + 来源标签（全局/环境/流水线/host_var/fact）；
- 点击任意变量行，会把 `{{ 变量名 }}` 插入到当前焦点所在的输入框；
- 合并优先级：全局 < 环境/分组 < 流水线参数 < 主机变量 < Facts；
- Facts 为只读快照，且只展示已注册字段，不能被用户变量覆盖；
- 提示：预览基于最近缓存的 Facts，需要最新信息请先执行「刷新Facts」节点。

## 6.2 文件分发（零依赖）

「批量执行 → 文件分发」现在使用 **纯 SFTP** 实现，不依赖 sshfs / rsync：

- **源为主机**：从源主机 SFTP 递归拉取目录到本地临时目录，再分发；
- **源为上传文件**：直接上传本地文件到各目标主机；
- 两侧都只需要 SSH（密码或密钥），目标机不需要安装任何额外软件；
- Windows 单机也能用（无需 msys / rsync / sshfs）。

> 注：Windows 上「应用发布」的构建步骤需要系统安装 git（GitPython 调用它），
> 打包与解包已改为 Python 内置 tarfile，不再依赖 bash / tar。

## 6.3 自定义发布（数据传输）注意事项

「应用发布 → 发布配置 → 自定义发布」里添加**数据传输**动作时：

- **目标路径必须写具体落地路径**，例如 `/tmp/mypkg.zip`、`/data/app`、`/opt/myapp`。
  不要写 `/tmp`、`/data` 这类目录本身或系统目录 —— Spug 会先 `rm -rf 目标路径`
  再放入新内容，写 `/tmp` 会把整个 `/tmp` 删掉（本版本已加拦截并给出提示）。
- **数据来源为「本地路径」** 时，路径是 **Spug 服务端**上的路径（Windows 本机也可以，
  支持中文目录）；部署时会自动打成 tar.gz 再上传，只需传输一个文件。
- 后续「解压」动作要求目标机已安装 `unzip`（CentOS 最小化安装默认没有，
  可先加一个执行动作 `yum install -y unzip`，或用 `python3 -m zipfile -e 包.zip 目标目录`）。
- 解压后如果还要覆盖文件，建议显式写 `unzip -o`（覆盖已存在文件）。

## 6.4 升级与更新

- **完整替换**：把新的 `dist\Spug` 整个覆盖到安装目录（会动 `runtime`，约 5200 个文件，较慢）。
- **快速更新（推荐）**：只替换 `app` 与 `web` 时，用包内自带的 `更新程序.ps1`：
  ```powershell
  powershell -ExecutionPolicy Bypass -File .\更新程序.ps1 -Zip .\spug-win-x64.zip
  ```
  脚本会先停掉正在运行的 Spug，只同步 `app` / `web`，**保留 `data`（数据库）与 `runtime`**，
  通常 1～2 秒完成。
- 首次启动时 Python 会重新生成 `.pyc` 缓存（约 2 秒），之后启动更快。

### 关于托盘图标

便携包**不再内置 Pillow**（省约 14MB），托盘图标改由 `Spug.exe` 启动器用 Windows
原生 `NotifyIcon` 提供：

- 双击 `Spug.exe` → 右下角出现 Spug 图标，右键菜单「打开 Spug 界面 / 退出」；
- 双击托盘图标也能打开界面；
- **退出请用托盘右键 → 退出**（会同时结束后台 Python 进程）；
- 如果托盘因环境限制初始化失败，程序会提示并退化为后台运行，Web 界面照常可用。

## 7. Web 终端

- 主机变量 `spug_tmux=1` 时，连接终端会自动执行 `tmux new -A -s spug`；
  未安装 tmux 自动降级为普通 shell。
- 终端右上角「常用命令」可收藏当前输入命令并一键回填。

## 8. 外部自愈（UptimeKuma 等）

```bash
curl -X POST "http://127.0.0.1:9000/api/apis/pipeline/12/" \
  -H "X-Api-Key: <系统设置-开放服务里的 api_key>" \
  -H "Content-Type: application/json" \
  -d '{"params": {}, "dry_run": false}'
```

返回 `202` 与 token；用 `GET /api/apis/pipeline/result/<token>/` 查询结果。

## 9. 备份与升级

- 备份：停止服务 → 复制整个 `data\` 目录。
- 升级：替换 `Spug.exe`、`runtime\`、`app\`、`web\`，保留 `data\` 与 `spug.ini`；
  启动时会自动执行新迁移。
- 端口冲突：修改 `spug.ini` 或设置环境变量 `SPUG_PORT`。

## 10. 注意事项

- 默认管理员 `admin/admin` 仅用于首次登录，请立即修改密码。
- `admin/admin` + 默认 `0.0.0.0` 监听意味着局域网可访问；仅本机使用可设 `host = 127.0.0.1`。
- 密码/私钥与原生 Spug 一样保存在本机 SQLite，请保护好 `data\spug.db`。
- 发布/构建/流水线的本地脚本步骤依赖 `bash`（Windows 需 Git for Windows）。
- 状态模块的 pkg/service 会真实修改主机，执行前建议先用 Dry-run 预览。
