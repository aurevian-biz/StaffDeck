# 数字员工 SDLC + OpenCode 融合流水线（25 步骤版）

> 本文档说明 it-org/ 配置下 20 名数字员工如何接进 SDLC + OpenCode 融合流水线。
> 配套文件：org_agents.json / org_skills.json / org_bindings.json / org_config.json / import_staffdeck.py / sdlc_pipeline.yaml / staffdeck_orchestrator.py / gen_sdlc_pipeline.py

## 一、融合全景图

```
发现与对齐 ──→ 产品 PRD ──→ 方案与架构 ──→ 编码实现 ──→ 质量保障 ──→ 发布交付 ──→ 知识沉淀
 (Phase 0)     (Phase 1)     (Phase 2)     (Phase 3)     (Phase 4)     (Phase 5)     (Phase 6)
   ce-ideate    product_prd   4 architect    ce-work       ce-code-review  ce-commit     ce-compound
   ce-strategy   openspec     openspec_design  TDD              TDD          ce-push-pr    ce-refresh
   ce-brainstorm  proposal    ce-plan         work             work
```

## 二、阶段详解

### 阶段 0 · 发现与对齐（OpenCode Phase 0）

| 步骤 | 员工 | 技能 | 产出 |
|---|---|---|---|
| **discovery_ideate** | 产品经理 | ce-ideate | 改进想法清单 |
| **discovery_strategy** | 产品经理 | ce-strategy | STRATEGY.md 策略文档 |
| **discovery_brainstorm** | 产品经理 | ce-brainstorm | Requirements Doc |

**说明**：可使用 `skip_discovery=true` 跳过此阶段（需求已明确时）。

### 阶段 1 · 产品 PRD + OpenSpec 提案（Phase 1）

| 步骤 | 员工 | 技能 | 产出 |
|---|---|---|---|
| **product_prd** | 产品经理 | product_manage_sop | PRD 文档 |
| **openspec_proposal** | 产品经理 | openspec_propose_sop | proposal.md（WHEN/THEN 场景） |

### 阶段 2 · 方案与架构（Phase 2，并行 4 员工）

| 步骤 | 员工 | 技能 | 产出 |
|---|---|---|---|
| **solution_architect** | 方案架构师 | solution_design_sop | 总体技术方案 |
| **backend_architect** | 后端架构师 | backend_architect_sop | 后端架构文档 |
| **frontend_architect** | 前端开发工程师 | frontend_dev_sop | 前端方案 |
| **security_architect** | 安全架构师 | security_architect_sop | 安全设计评审意见 |
| **openspec_design** | 方案架构师 | openspec_design_sop + ce-doc-review | design.md + tasks.md |
| **architecture_approval** | — | 审批门禁 | 放行/中止 |
| **implementation_plan** | 方案架构师 | ce-plan | 实施计划（TDD 步骤） |

### 阶段 3 · 编码实现（Phase 3，TDD 强调）

| 步骤 | 员工 | 技能 | 产出 |
|---|---|---|---|
| **software_dev** | 软件工程师 | code_implementation_sop + TDD | 业务模块代码 |
| **ai_dev** | AI 应用工程师 | ai_app_engineer_sop + TDD | AI/智能体模块代码 |
| **devops_setup** | DevOps 自动化工程师 | devops_automation_sop | CI/CD 配置 |

**TDD 工作流**：RED → GREEN → REFACTOR，每个任务先写 FAILING 测试。

### 阶段 4 · 质量保障（Phase 4）

| 步骤 | 员工 | 技能 | 产出 |
|---|---|---|---|
| **code_review** | 代码审查专家 | ce-code-review | 审查报告（🔴🟡💭分级） |
| **api_test** | API 测试工程师 | api_testing_sop | 接口测试策略 |
| **acceptance_test** | 测试验收专员 | test_case_generation_sop + acceptance_check_sop | 测试用例 + 验收清单 |
| **performance_test** | 性能基准工程师 | performance_benchmark_sop | 性能报告（条件触发） |
| **pentest** | 渗透测试工程师 | penetration_test_sop | 渗透测试报告（条件触发） |
| **release_approval** | — | 审批门禁 | 放行/中止 |

### 阶段 5 · 发布交付（Phase 5）

| 步骤 | 员工 | 技能 | 产出 |
|---|---|---|---|
| **commit_push_pr** | 软件工程师 | ce-commit-push-pr | commit + PR |
| **delivery_summary** | 交付项目经理 | project_risk_inspection_sop + weekly_report_sop | 交付总结 |

### 阶段 6 · 知识沉淀（Phase 6，闭环）

| 步骤 | 员工 | 技能 | 产出 |
|---|---|---|---|
| **knowledge_compound** | 知识运营专员 | ce-compound | docs/solutions/ 知识沉淀 |
| **knowledge_sediment** | 知识运营专员 | ce-compound-refresh | 知识库/SOP 修订建议 |

## 三、DAG 分层（18 层）

```
L1:  discovery_ideate（顺序）
L2:  discovery_strategy（顺序）
L3:  discovery_brainstorm（顺序）
L4:  product_prd（顺序）
L5:  openspec_proposal（顺序）
L6:  solution_architect / backend_architect / frontend_architect / security_architect（4 路并行）
L7:  openspec_design（顺序）
L8:  architecture_approval（审批）
L9:  implementation_plan（顺序）
L10: software_dev / ai_dev / devops_setup（3 路并行）
L11: code_review（顺序）
L12: api_test / acceptance_test（并行）
L13: performance_test / pentest（并行，条件控制）
L14: release_approval（审批）
L15: commit_push_pr（顺序）
L16: delivery_summary（顺序）
L17: knowledge_compound（顺序）
L18: knowledge_sediment（顺序）
```

## 四、编排器使用

```bash
# 预览执行计划
python it-org/staffdeck_orchestrator.py it-org/sdlc_pipeline.yaml --dry-run

# 正式执行
python it-org/staffdeck_orchestrator.py it-org/sdlc_pipeline.yaml \
    --base-url http://127.0.0.1:5173 --username admin --password admin \
    --tenant-id tenant_demo --input project_name=客服系统

# 跳过发现阶段（需求已明确时）
python it-org/staffdeck_orchestrator.py it-org/sdlc_pipeline.yaml \
    --input skip_discovery=true

# 无人值守
python it-org/staffdeck_orchestrator.py it-org/sdlc_pipeline.yaml --non-interactive
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

### 新增输入变量

| 变量 | 默认值 | 说明 |
|---|---|---|
| `skip_discovery` | `false` | 是否跳过发现阶段（需求已明确时设为 `true`） |

## 五、与 OpenCode 工作流的对应关系

| OpenCode 阶段 | StaffDeck 阶段 | 新增步骤 | 技能映射 |
|---|---|---|---|
| Phase 0: Discovery | 阶段 0 | discovery_ideate, discovery_strategy, discovery_brainstorm | ce-ideate, ce-strategy, ce-brainstorm |
| Phase 1: Spec | 阶段 1 | openspec_proposal | openspec_propose_sop |
| Phase 2: Plan | 阶段 2 | openspec_design, implementation_plan | openspec_design_sop, ce-doc-review, ce-plan |
| Phase 3: Execute | 阶段 3 | （TDD 强调） | ce-work, TDD 工作流 |
| Phase 4: Quality | 阶段 4 | （ce-code-review 增强） | ce-code-review |
| Phase 5: Release | 阶段 5 | commit_push_pr | ce-commit-push-pr |
| Phase 6: Closure | 阶段 6 | knowledge_compound | ce-compound, ce-compound-refresh |

## 六、员工岗位总览（SD-000 ~ SD-019）

| 工号 | 员工 | 部门/组 | SOP 技能 | 通用技能 |
|---|---|---|---|---|
| SD-000 | 整体智能体 | 开放广场 | — | — |
| SD-001 | 售前咨询顾问 | 市场/售前 | customer_intake_sop, quote_review_sop | — |
| SD-002 | 方案架构师 | 交付/架构 | solution_design_sop, openspec_design_sop | ce-plan, ce-doc-review |
| SD-003 | 交付项目经理 | 交付/项目 | project_risk_inspection_sop, weekly_report_sop | — |
| SD-004 | 软件工程师 | 研发/后端 | code_implementation_sop, tech_support_sop | ce-debug, ce-simplify-code, ce-commit, ce-commit-push-pr |
| SD-005 | 测试验收专员 | 测试/功能 | test_case_generation_sop, acceptance_check_sop | reviewing-openspec-artifacts |
| SD-006 | 售后支持工程师 | 服务/售后 | ticket_triage_sop, fault_diagnosis_sop | ce-debug |
| SD-007 | 知识运营专员 | 运营/知识 | knowledge_sedimentation_sop | ce-compound, ce-compound-refresh |
| SD-008 | 内部行政助手 | 行政 | admin_service_sop | — |
| SD-009 | 代码审查专家 | 研发/质量 | code_review_expert_sop | ce-code-review |
| SD-010 | 后端架构师 | 研发/架构 | backend_architect_sop | — |
| SD-011 | API 测试工程师 | 测试/测试 | api_testing_sop | — |
| SD-012 | 性能基准工程师 | 测试/性能 | performance_benchmark_sop | — |
| SD-013 | DevOps 自动化工程师 | 研发/平台 | devops_automation_sop | ce-clean-gone-branches, ce-worktree |
| SD-014 | AI 应用工程师 | 研发/AI | ai_app_engineer_sop | ce-agent-native-architecture, ce-optimize |
| SD-015 | 安全架构师 | 研发/安全 | security_architect_sop | ce-agent-native-audit |
| SD-016 | 渗透测试工程师 | 测试/安全 | penetration_test_sop | — |
| SD-017 | 前端开发工程师 | 研发/前端 | frontend_dev_sop | — |
| SD-018 | 数据库优化工程师 | 研发/平台 | database_optimize_sop | — |
| SD-019 | 产品经理 | 产品 | product_manage_sop, openspec_propose_sop | ce-ideate, ce-strategy, ce-brainstorm, ce-plan, ce-doc-review |

## 七、生成器用法

```bash
# 默认生成
python it-org/gen_sdlc_pipeline.py --out it-org/sdlc_pipeline.yaml

# 自定义参数
python it-org/gen_sdlc_pipeline.py --project-name 订单系统 --requirements "处理订单" --no-include-ai

# 跳过发现阶段
python it-org/gen_sdlc_pipeline.py --skip-discovery
```

## 八、相关资源清单

- 8 知识库：产品与服务手册、成功案例库、技术知识库、交付流程制度库、测试规范与验收标准、售后故障处理手册、知识运营台账、公司制度库
- 16 工具：crm.lead.register、project.progress.query、report.weekly.push、code.review、api.example、ticket.handle、log.query、image.generate.gemini、proof.doc.review、product.pulse、search.web.last30、trend.analyze、slack.search、browser.automate、agent.browser.cli、ast.search
- 30+ 通用技能：ce-ideate, ce-strategy, ce-brainstorm, ce-plan, ce-doc-review, ce-code-review, ce-commit, ce-commit-push-pr, ce-compound, ce-compound-refresh 等
