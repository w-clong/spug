# Spug 轻量化运维 Fork 改造说明（进行中）

> 目标：Windows 单机便携版，内置官方 Python embeddable runtime，同进程 import pyinfra
> 提供状态模块、Facts 缓存、变量、Jinja2 模板、基线、变更日志等能力，
> 平替 Ansible 日常 90% 场景。**不引入工单/审批/RBAC/CMDB/监控存储/K8s。**

## 1. 硬性架构与落地方式

| 规范 | 实现位置 | 状态 |
|---|---|---|
| 私有 embeddable Python runtime，不写注册表/PATH | `build-portable.ps1` + `runtime/`；`Spug.exe` 注入运行根 | 已验证 |
| 同进程 import pyinfra，禁止 CLI/subprocess | `apps/ops/kernel/runner.py` | 已实现 |
| 复用 Spug 原生 paramiko 依赖 | `apps/ops/kernel/inventory.py`（私钥解析走 `libs.ssh.SSH.load_pkey`） | 已实现 |
| 凭证不落地/不进命令行/不写临时文件 | 私钥走 `State.private_keys` 注入 PKey 对象；密码走 `ssh_password`（内存传给 paramiko） | 已实现 |
| 密码 + 密钥双认证 | `Host.password`（SQLite 存储，接口不返回原文）/ `Host.pkey` | 已实现 |
| Facts：pyinfra 实时采集 + 数据库缓存 | `apps/ops/kernel/facts.py` + `host_facts` 表 | 已实现内核 |
| 统一 changed/failed/diff/msg | `apps/ops/kernel/result.py` | 已实现 |
| 独立线程池隔离、异常不拖垮主进程 | 调用方使用线程池；`StateRunner.run()` 全量 try/except 并落失败结果 | 已实现内核 |
| 事件回调 → Spug WebSocket 日志 | `_EventCallback` + `on_event(host_id, kind, msg)` | 已实现内核 |

## 2. 已完成（第一阶段）

### 2.1 数据库模型与迁移（新增 app `apps.ops`）

| 表 | 说明 |
|---|---|
| `host_facts` | Facts 缓存：`host_id / fact_key / fact_value(JSON) / updated_at`，唯一键 `(host_id, fact_key)` |
| `host_variables` | 主机变量（host_vars） |
| `group_variables` | 分组变量（group_vars） |
| `dynamic_groups` | 基于 Facts 的动态分组规则（JSON 规则数组） |
| `config_templates` / `config_template_versions` | Jinja2 模板库 + 历史版本 |
| `baselines` | 基线模板（状态模块节点组合） |
| `state_tasks` / `state_task_hosts` | 批量执行页「状态模块」任务及逐主机结果 |
| `change_records` | 全局变更日志（changed/failed/diff/来源/操作人） |

`host_groups` 增加 `is_dynamic` 字段（`apps.host` 迁移 `0002_group_is_dynamic`）。
所有 app 的初始迁移已生成并通过 `manage.py migrate` 验证（SQLite）。

> 注：`spug_api/.gitignore` 原本忽略 `migrations/`，导致仓库内没有迁移文件；
> 本次已移除该忽略规则并在工作区生成全部迁移（共 19 个文件），保证升级可重复。

### 2.2 内核（`apps/ops/kernel/`）

```
inventory.py   Host -> pyinfra Inventory；私钥内存注入
modules.py     模块注册表（UI 字段描述）+ 表单参数归一化 + 按发行版分发 operation
runner.py      StateRunner：连接 -> 采集分发 Facts -> add_op -> (dry-run | run_ops) -> 结果收敛
facts.py       静态 Facts 采集/缓存/读取/_SPUG_FACT_* 环境变量
variables.py   变量池（pipeline < facts < group < host）
templates.py   Jinja2 渲染（含 to_json 过滤器）
result.py      HostResult / RunSummary
selftest.py    不连主机的自检脚本
```

模块与 pyinfra operation 映射：

- `pkg` → `apt.packages` / `dnf.packages` / `apk.packages`
- `file` → `files.file`；带 content 时 `files.put(StringIO(...))`
- `directory` → `files.directory`
- `service` → `systemd.service` / `sysvinit.service`
- `user` → `server.user`

Dry-run 语义：连接到主机后执行到 pyinfra `Prepare` 阶段，计算将要下发的命令并输出，
**不进入 `run_ops`**，因此不会修改主机；`changed` 由 `OperationMeta.will_change` 推导。

### 2.3 批量执行 / 流水线 / API（本轮）

- 批量执行：`ExecHistory` 新增 `kind/module/dry_run`；POST `/api/exec/do/` 支持
  `kind=state`；PATCH 会把任务投递到 `spug:state:worker`。新增 worker
  `apps/ops/executor.py`，输出沿用原生 WS 协议（`{key, data, status}`），前端现有
  控制台可直接复用。
- 流水线：新增 `state` 与 `facts` 节点；`state` 节点结束输出 `changed`/`failed`，
  下游条件新增 `changed`/`unchanged`（Ansible Handler 语义）；全局 `dry_run=true`
  时非状态节点只跳过、不执行。
- Facts 注入：批量执行与流水线脚本节点执行前自动注入 `_SPUG_FACT_*` / `_SPUG_VAR_*`。
- 新增 API（`/api/ops/...`）：`modules/`、`facts/`（查询/刷新）、`variables/`
  （host/group）、`dynamic-groups/`、`templates/`（含版本）、`baselines/`、`changes/`。
- 前端：批量执行新增「状态模块」表单 + Dry-run 开关；流水线新增状态模块/Facts 节点、
  `changed`/`unchanged` 条件、列表页 Dry-run 入口；定时任务新增 脚本/状态模块/Facts 刷新
  三选一与 Dry-run 巡检；`web/build` 已重新构建。
- 定时任务：`Task` 新增 `kind/module/dry_run`；`state` 任务结果写入原生执行历史，
  无变更静默、有变更/失败时汇总一条通知（复用 rst_notify 渠道）。
- 前端「运维增强」菜单：变更日志（筛选/详情）、配置模板（新建/编辑/历史版本逐行对比）、
  基线管理（一键收敛 / 一键巡检）、变量管理（主机/分组）、动态分组（Facts 规则）；
  主机列表新增 Facts 抽屉。
- 制品拉取节点（方案 A，只消费）：流水线新增 `artifact` 节点，支持
  **raw / rpm / deb**（OCI 保留分支待迭代）；无认证 / Bearer / Basic（复用现有 Credential）、
  Jinja 渲染、HEAD Dry-run、按大小/覆盖策略幂等下载；rpm/deb 写远端源配置后用 pyinfra pkg
  模块安装（含 apt cache_time 保证幂等），系统已有同源时自动跳过写入避免 Trusted 冲突。
- 状态模块扩充：在 pkg/file/directory/service/user 基础上新增
  **group / command / line / block / sysctl / crontab / download** 共 12 个高频模块。
- 变量上下文预览：新增 `get_merged_context(pipeline_id, host_id)` 统一合并函数
  （全局 < 环境/分组 < 流水线参数 < 主机变量 < Facts），Facts 只读且仅展示
  `FACTS_META` 注册字段；流水线编辑器右侧新增可折叠面板，支持按主机预览真实值与来源，
  点击变量插入当前输入框；Jinja 渲染统一走 `render_jinja` 友好报错。
- 基线管理：可视化节点编辑（模块下拉 + 表单，可增删排序），支持一键收敛/巡检；
  流水线编辑器新增「存为基线」，可把当前流水线中的状态模块节点一键保存为基线；
  主机列表新增「卡片」视图（系统、内存、采集时间、快捷详情/Facts/编辑）。
- 主机增强：列表新增「系统」列（os_family/os_version/内存/采集时间）；新增
  `GET /api/host/export/json/` 与 `POST /api/host/import/json/` JSON 备份（不含凭证）。
- 通知分级：失败 / 巡检漂移 / 存在变更三种汇总标题，正常完成静默；无变更不打扰。
- Web 终端：主机变量 `spug_tmux=1` 时自动附着同名 tmux 会话（未安装 tmux 自动降级），
  常用命令可收藏（localStorage）并一键回填执行。
- 基线执行：`apps/ops/baseline_runner.py` 顺序执行基线节点，结果汇总为 StateTask，
  并写入全局变更日志。
- File 状态模块支持 `template_id`：按每台主机的 Facts + 主机/分组变量渲染 Jinja2，
  内容相同的主机合并为一个 operation；前端模板字段改为下拉选择。
- 密码认证：`Host` 新增 `password`（与 pkey 二选一），pyinfra Inventory 使用
  `ssh_password`；主机表单新增「认证方式」开关。密码仅存本机 SQLite，接口不返回原文。
- 便携打包：`build-portable.ps1` + `packaging/launcher.cs`（`Spug.exe`）+ embeddable
  runtime + `spug.ini`，结构与验证见下。

## 3. 版本耦合风险（重要）

1. **pyinfra 3.10.0 内部 API 非稳定契约**
   - 依赖 `pyinfra.api.state.StateStage`、`OperationMeta.changed/did_change`、
     `op_data.command_generator()`、`State.private_keys` 等；升级 pyinfra 需回归测试。
2. **pyinfra ↔ paramiko 版本**
   - pyinfra 3.10 声明 `paramiko>=2.11,<5`，Spug 固定 `paramiko==3.4.0`；
     已验证可导入并可构建连接器，但真实握手/密钥类型需在目标 Linux 主机上回归。
3. **gevent**
   - pyinfra 依赖 gevent 做并发连接与执行；本方案在独立线程内调用，
     Django 主线程不使用 gevent monkey patch。若后续 pyinfra 改变并发模型需复核。
4. **Python 3.12 embeddable**
   - 依赖 wheel 必须为 `cp312-win_amd64`；gevent/pydantic-core 等二进制包需随 runtime 固定版本。
5. **Django 4.2 + 无 migrations 仓库**
   - 运行期 `makemigrations` 生成的迁移与仓库内文件如不一致，会影响升级；
     本次已生成并纳入工作区，后续需固定。
6. **pyinfra 结果字段**
   - `diff` 由「准备阶段命令 + 执行输出」拼接，pyinfra 3.10 未提供统一的 diff 字符串；
     文件内容 diff 后续在模板/文件模块内自行计算（计划中）。

## 4. 待实施路线（按交付顺序）

1. **后端业务**：批量执行「状态模块」任务（API + worker + WS 日志）、流水线状态模块节点
   （changed/failed 分支）、Facts 定时采集、模板/基线/变更日志 API、变量注入 Shell/Python。
2. **前端**：复刻 Spug 原生风格的页面（状态模块表单、Facts 卡片、变量、模板库、基线、
   变更日志时间线、Dry-run 开关、通知策略）。
3. **打包**：`runtime/`（python-3.12.10-embed-amd64）+ 依赖 + `Spug.exe` 启动器；
   `spug.ini` 配置；数据目录 portable。
4. **文档与依赖锁定**：requirements 固定、构建/升级说明、风险清单。

## 5. 当前验证情况

- `manage.py migrate`：全部迁移通过（临时 SQLite）。
- `apps/ops/kernel/selftest.py`：Inventory 构建、私钥内存注入、5 个模块的 operation 分发通过。
- **官方 embeddable runtime 已验证**：`python-3.12.10-embed-amd64` + 依赖装入
  `Lib\site-packages`，成功导入 Django 4.2.30 / pyinfra 3.10.0 / gevent 26.9.0 /
  paramiko 3.4.0，并运行 `manage.py check`（0 issues）与内核自检。
- **批量执行/API 自检**：`apps/ops/selftest_api.py`（任务创建、非法模块拒绝、队列投递、
  模块/变量/模板/基线/变更日志/定时任务接口）。
- **Worker 自检**：`apps/ops/selftest_worker.py`（队列 → 落库 → changed 统计，幂等）。
- **定时任务自检**：`apps/ops/selftest_schedule.py`（状态模块任务 → 原生执行历史）。
- **便携包实测**：`dist\Spug` 用私有 runtime 启动 → 首页/静态资源 200 → `admin/admin`
  登录 → `/api/ops/modules/`、`/api/schedule/`、`/api/ops/changes/` 均正常。
- **真实 Linux E2E（已通过）**：Rocky Linux 9.7（root）+ Ubuntu 24.04（普通用户），
  密码认证；Facts 推导 `os_family=RedHat/Debian`、`os_version=9.7/24.04`；
  directory/file 首次 `changed=True`、二次执行幂等 `changed=False`；service 模块正确
  检出 Ubuntu `ssh` 未开机自启的漂移；pkg 按发行版分别生成 dnf/apt 安装命令（dry-run）；
  Jinja2 模板按主机渲染（Rocky 默认 port=80，Ubuntu 主机变量 port=8080，内容各自正确）。
- **打包版端到端（已通过）**：`dist\Spug` 私有 runtime 启动 → API 创建密码主机
  （真实 SSH 验证）→ `/api/ops/facts/` 采集到 `Debian/24.04` → 状态模块真实执行
  创建目录 → `/api/ops/changes/` 出现 changed 记录 → dry-run 幂等任务 → 清理成功。
- **回归自检（全部通过）**：`kernel/selftest.py`、`selftest_worker.py`、`selftest_api.py`、
  `selftest_schedule.py`、`selftest_baseline.py`、`selftest_password.py`、
  `selftest_dynamic.py`、`selftest_context.py`（优先级/Facts 只读/无主机/渲染报错）、
  `selftest_artifact.py`（raw dry-run HEAD / 下载 changed / 幂等 unchanged / 认证头生成）；
  `manage.py check` 0 issues。
- **未验证**：真实主机上的破坏性变更（如实际安装软件包/重启服务）尚未执行；
  pyinfra 3.10 内部 API 在升级后需回归。

## 6. 开发环境

```powershell
# 依赖（pyinfra 3.10 + Spug 单机依赖）
.\.venv-win\Scripts\python.exe -m pip install -r spug_api\requirements-standalone.txt pyinfra==3.10.0

# 内核自检
.\.venv-win\Scripts\python.exe spug_api\apps\ops\kernel\selftest.py

# 迁移
cd spug_api
$env:SPUG_DATA_DIR="C:\path\to\data"
..\.venv-win\Scripts\python.exe manage.py makemigrations <app...>
..\.venv-win\Scripts\python.exe manage.py migrate
```

## 8. 本次新增功能的已知边界

- **制品凭据**：按你的选择复用现有 `Credential`（与 Spug 原生一致，明文存 SQLite、
  接口不回显），未新增 Fernet 加密表；如需加密存储需后续迁移。
- **制品源**：raw / rpm / deb 已实现并经真实主机验证；OCI 镜像源待迭代。
  deb 不支持 Bearer（apt 限制，已给明确报错）；rpm Bearer 依赖 dnf `http_headers`。
- **deb 幂等**：`apt-get update` 使用 cache_time=600，否则每次执行都会判定 changed。
- **非 root 主机**：写 `/etc` 源配置与 `crontab -u other` 通过 SSH stdin 传递 sudo 密码
  （需 Host 保存登录密码），不会出现在命令行参数中。
- **统一上下文范围**：`get_merged_context` 已用于制品节点渲染与变量预览；
  原有状态模块/脚本节点仍沿用各自渲染逻辑，避免破坏既有行为（与“全部节点统一”有差距）。
- **前端框架**：按确认使用现有 React + antd4 实现，未引入 Vue。
- **布局**：已修复内容区无法滚动（外层 100vh + 隐藏滚动条导致高倍缩放时内容被裁），
  变量面板从 fixed 遮罩改为 flex 侧栏（不再遮挡节点配置抽屉）。

## 9. 外部自愈联动（UptimeKuma 等）

复用 Spug 原生开放 API：`POST /api/apis/pipeline/<pipeline_id>/`，请求头
`X-Api-Key` 取自「系统设置 → 开放服务」里的 api_key。

```bash
# 正常执行（收敛/重启）
curl -X POST "http://127.0.0.1:9000/api/apis/pipeline/12/" \
  -H "X-Api-Key: <your-api-key>" \
  -H "Content-Type: application/json" \
  -d '{"params": {"service": "nginx"}}'

# 只巡检，不修改主机
curl -X POST "http://127.0.0.1:9000/api/apis/pipeline/12/" \
  -H "X-Api-Key: <your-api-key>" \
  -H "Content-Type: application/json" \
  -d '{"params": {}, "dry_run": true}'
```

推荐流水线结构（自愈）：

1. `Facts刷新` 节点（可选）
2. `状态模块` 节点：`service`（name=nginx, running=true, enabled=true）
3. 下游 `changed` 条件 → `执行命令` 节点（如重载配置）或推送节点

UptimeKuma 的 Webhook 通知直接把上述 URL 作为 Webhook URL，并在请求头加
`X-Api-Key` 即可；返回 `202` 与 `token`，可用
`GET /api/apis/pipeline/result/<token>/` 查询执行结果。

> 说明：开放 API 不支持 `data_upload` 节点的流水线；`dry_run` 为本次新增参数。
