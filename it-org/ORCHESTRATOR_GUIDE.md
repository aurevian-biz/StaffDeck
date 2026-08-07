# StaffDeck 流水线编排器使用说明

> 对应文件：`it-org/staffdeck_orchestrator.py`
> 配套工作流：`it-org/sdlc_pipeline.yaml`

## 一、这是什么

把 **agency-orchestrator（AO）schema 的 YAML 工作流**翻译成对 StaffDeck 数字员工的派活指令：

- 解析 YAML → 构建 DAG → **分层并行执行**（`concurrency` 控制并发度）
- `{{变量}}` 在步骤间传递输出
- `condition` 不满足的步骤自动跳过
- `approval` / `human_input` 人工节点暂停等待输入
- 失败自动**指数退避重试**（`llm.retry` 次）
- 每步结果归档到 `ao-output/<工作流名>-<时间戳>/`

分工：**AO 管流程编排（DAG/并行/门禁/重试），StaffDeck 管员工执行（SOP 状态机/知识库/工具）**。

## 二、环境准备

```bash
# 依赖
pip install pyyaml requests

# 前置条件（缺一不可）：
# 1. StaffDeck 服务已启动（python scripts\dev.py up）
# 2. 已导入员工与资源配置（python it-org/import_staffdeck.py）
#    —— 编排器按员工"姓名"找员工，找不到会报"员工不存在，请先运行 import_staffdeck.py"
# 3. 员工已绑定对应 SOP（org_bindings.json 已配置好，导入即生效）
```

## 三、命令行用法

```bash
# 预览执行计划（不调用任何 API，验证 YAML 与 DAG）
python it-org/staffdeck_orchestrator.py it-org/sdlc_pipeline.yaml --dry-run

# 正式执行（交互式：审批门禁会暂停等你输入 y/n）
python it-org/staffdeck_orchestrator.py it-org/sdlc_pipeline.yaml

# 覆盖输入变量（可多次 --input）
python it-org/staffdeck_orchestrator.py it-org/sdlc_pipeline.yaml \
    --input project_name=客服系统 --input include_perf=true

# 无人值守（审批自动放行 y，人工输入用空串）
python it-org/staffdeck_orchestrator.py it-org/sdlc_pipeline.yaml --non-interactive

# 服务不在默认地址时
python it-org/staffdeck_orchestrator.py it-org/sdlc_pipeline.yaml \
    --base-url http://127.0.0.1:5174 --username admin --password 你的密码 --tenant-id tenant_demo
```

### 参数一览

| 参数 | 默认值 | 说明 |
|---|---|---|
| `workflow`（位置参数） | 必填 | YAML 工作流文件路径 |
| `--base-url` | `http://127.0.0.1:5173` | StaffDeck 服务地址 |
| `--username` / `--password` | `admin` / `admin` | 登录账号 |
| `--tenant-id` | `tenant_demo` | 租户 |
| `--input k=v` | 无 | 覆盖工作流 inputs 的默认值，可多次 |
| `--dry-run` | 关 | 只解析并打印分层执行计划 |
| `--non-interactive` | 关 | 审批自动放行、人工输入填空 |

## 四、工作流 YAML 编写指南

### 4.1 顶层结构

```yaml
name: sdlc-agent-pipeline        # 工作流名（归档目录名）
llm:
  provider: staffdeck            # 固定值（扩展字段，仅作标识）
  retry: 3                       # 失败重试次数（指数退避）
  timeout: 300000                # 单轮对话超时（毫秒）
concurrency: 2                   # 并行步骤数上限
inputs:                          # 输入变量（可用 --input 覆盖）
  - name: project_name
    default: 智能客服Agent系统
  - name: include_ai
    default: true
steps:                           # 步骤列表（核心）
  - id: product_prd              # 必填，唯一
    role: 产品经理               # 员工姓名（与 org_agents.json 一致）
    task: "请为「{{project_name}}」产出 PRD…"   # 支持 {{变量}}
    output: prd                  # 输出变量名（供下游步骤引用）
    depends_on: []               # 依赖的步骤 id 列表
    condition: "{{include_ai}} == true"   # 不满足则跳过
    max_turns: 6                 # 单步最多对话轮数（SOP 反问多时可调大）
    extract: reply               # reply（默认）| trace（存完整 Trace JSON）
```

### 4.2 步骤类型

| 类型 | 说明 | 关键字段 |
|---|---|---|
| `task`（默认） | 派给数字员工执行 | `role` + `task` + `output` |
| `approval` | 人工审批门禁，暂停等 y/n | `prompt`；拒绝则流水线中止 |
| `human_input` | 人工输入，值写入变量 | `prompt` + `output` |

### 4.3 依赖与并行

```yaml
- id: step_c
  depends_on: [step_a, step_b]      # 两个都完成才执行
- id: step_d
  depends_on: [step_a, step_b]
  depends_on_mode: any_completed    # 任一完成即可执行（默认 all）
```

同一层的步骤自动并行（受 `concurrency` 限制）。

### 4.4 条件表达式

```yaml
condition: "{{include_perf}} == true"
condition: "{{project_name}} contains 客服"
condition: "{{mode}} != demo and {{include_ai}} == true"
```

支持运算符：`contains` / `==` / `!=`，组合用 `and` / `or`（不支持括号）。

## 五、执行过程与交互

1. **登录** → 校验账号连通性
2. **DAG 分层**：按最长依赖路径分层（`--dry-run` 可预览：`L1 产品经理 → L2 四架构并行 → L3 审批 → …`）
3. **逐层执行**：
   - 并行步骤用线程池并发跑
   - `approval` / `human_input` 在主线程串行，交互模式打印提示等你输入
   - 每个 task 步骤：创建会话 → 发任务 → 若员工反问（SOP 采集信息，`session_state.awaiting_input`）自动续轮，直到完成或 `max_turns` 上限
4. **重试**：单步失败按 `retry` 次指数退避重试（2s→4s→8s…封顶 30s）；重试耗尽则**中止整个流水线**，其余步骤不再执行
5. **归档输出**并打印结果汇总

## 六、输出归档

每次执行生成目录 `ao-output/<工作流名>-<时间戳>/`（在工作目录下）：

```
ao-output/
└── sdlc-agent-pipeline-20260802-153000/
    ├── summary.md          # 执行报告：输入变量 + 每步状态（✅/⏭️/❌）
    ├── metadata.json       # 结构化元数据：变量快照、每步状态（done/skipped/failed）
    └── steps/
        ├── 1-product_prd.md      # 每步详情（含 StaffDeck 会话 id）
        ├── 2-solution_architect.md
        └── ...
```

`steps/N-<id>.md` 中的会话 id 可在 StaffDeck 界面（Trace）回看该员工的完整执行过程。

## 七、常见问题

| 现象 | 原因与处理 |
|---|---|
| `员工不存在: xxx。请先运行 import_staffdeck.py` | 员工未导入，或工作流 `role` 与导入的员工名不一致（注意全角/半角、空格） |
| 登录失败 401 | `--username`/`--password`/`--tenant-id` 不对，或服务未启动 |
| 步骤输出为空 "(员工无文字回复…)" | SOP 未触发（员工没匹配到意图）→ 检查该员工是否绑定对应 SOP，或在 `task` 中写明要走的流程 |
| 步骤反复被员工反问直到 max_turns | SOP 采集信息过多 → 调大该步骤 `max_turns`，或在 `task` 里直接附齐所需信息 |
| 审批被拒导致流水线中止 | `approval` 输入非 y/yes 即中止；`--non-interactive` 会自动放行 |
| 某些步骤没执行 | 查看是否 `condition` 不满足（输出显示 ⏭️ 跳过） |

## 八、注意事项

- **数字员工没有跨会话记忆**：每步 `task` 必须自带足上下文（把上游 `{{变量}}` 拼进去），不要把"请参考上一步"当指令。
- `extract: trace` 会把完整 Trace JSON 存入变量，数据量大，默认用 `reply` 即可。
- 工作流 `llm.provider` 固定写 `staffdeck`（本适配器扩展字段，AO 原生引擎不识别）。
- `loop` 循环节点（AO 原生功能）**本适配器未实现**，请用多个显式步骤替代。
