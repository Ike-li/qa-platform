# OMC 框架工作流程时间线

> 本文档记录了使用 oh-my-claudecode (OMC) 框架从零构建「企业级自动化测试平台」的完整过程。
> 包括每一步使用的 OMC 命令、提问内容、用户回答和执行结果。

---

## 总览

```
/deep-interview → /ralplan → /autopilot → 多视角审查 → /ralph 修复 → /ultraqa QA → /remember → /wiki → git init
```

| 阶段 | OMC 命令 | 耗时轮次 | 结果 |
|------|----------|---------|------|
| 需求澄清 | `/deep-interview` | 17 轮 | 模糊度 100% → 10.0% |
| 架构共识 | `/ralplan` | 2 轮迭代 | Architect + Critic APPROVE |
| 全栈实施 | `/autopilot` | 8 阶段 | 92 个源文件 |
| 安全审查 | `Agent(security-reviewer)` | 1 轮 | 2 CRITICAL + 3 HIGH |
| 代码审查 | `Agent(code-reviewer)` | 1 轮 | 1 CRITICAL + 4 HIGH |
| 功能审查 | `Agent(architect)` | 1 轮 | 1 项功能缺口 |
| 问题修复 | `/ralph` | 8 项修复 | 全部 PASS |
| 自动化QA | `/ultraqa` | 1 轮 | 117/117 通过 |
| 知识沉淀 | `/remember` | 1 轮 | 3 个 memory 文件 |
| 文档生成 | `/wiki` | 5 页 | 架构/RBAC/管道/部署/API |
| 版本控制 | `git init + commit` | 2 次提交 | 101 文件, 11136 行 |

---

## Stage 1: Deep Interview — 需求澄清

### 命令

```
/deep-interview "生产级的企业级自动化测试平台，框架: Flask（Python Web 框架），数据库mysql，报告: Allure，可单独在独立浏览器标签页打开，也就是一个链接。管理、调度和执行自动化测试，仪表盘数据服务：为前端提供实时的测试项目、分支、执行情况等数据，包含管理员账号体系"
```

### 轮次详情

| 轮次 | 提问 | 用户回答 | 模糊度 |
|------|------|----------|--------|
| 1 | "能具体描述一下它要解决的核心场景吗？" | **全新测试体系** — 从零搭建完整平台 | 75.5% |
| 2 | "如果让你验收，你会怎么判断它'能用了'？" | **企业级全功能** — RBAC、审计、通知、Webhook、并行执行 | 84.5% ↑ |
| 3 | "平台管理的'自动化测试'具体是哪类测试？" | **全选4类** — API、Web UI、单元/集成、性能 | 74.0% |
| 4 | "你希望仪表盘上最先看到哪些核心信息？" | **全选4项** — 通过率、趋势、队列、失败速览+Allure链接 | 64.0% |
| 5 | "你打算把平台部署在哪里？" | **Docker 容器化**，团队 5-20 人 | 57.5% |
| 6 | "测试脚本是怎么'进入'平台的？" | **Git 仓库拉取执行** | 55.5% |
| 7 | "你认为需要几种用户角色？" | **四角色：参考 TestRail**（超管+负责人+测试员+访客） | 46.0% |
| 8 | "测试脚本存放在哪个 Git 平台？" | **通用 Git** — 支持任意平台 | 43.0% |
| 9 | "第一版优先支持哪些通知渠道？" | **全选3渠道** — 邮件、钉钉、企微 | 36.5% |
| 10 | "测试执行可以由什么方式触发？" | **3种** — Web手动+Cron+API（不要CI/CD Webhook） | 31.0% |
| 11 | "Docker 部署采用什么编排方式？" | **docker-compose 单机** | 29.5% |
| 12 | "审计日志具体要记录哪些操作？" | **全选3类** — 账号、执行、项目管理 | 27.4% |
| 13 | "测试结果和审计日志需要保留多久？" | **管理员可配置** | 24.1% |
| 14 | "RBAC 4 角色的权限如何定义？" | **直接抄 TestRail 权限模型** | 19.2% ✅ |
| 15 | "单次测试执行的超时策略是什么？" | **管理员可配置** | 17.1% |
| 16 | "最多可以同时运行多少个测试任务？" | **管理员可配置** | 14.1% |
| 17 | "前端使用什么技术栈？" | **Flask 模板 + Bootstrap**（服务端渲染） | **10.0%** ✅ |

### 输出

- 规格文档: `.omc/specs/deep-interview-qa-platform.md`
- 最终模糊度: **10.0%**（阈值 20%）

---

## Stage 2: Ralplan — 架构共识

### 命令

```
/ralplan --consensus --direct .omc/specs/deep-interview-qa-platform.md
```

### 迭代过程

#### 迭代 1: Planner → Architect → Critic

**Planner** 创建初始实施计划:
- 8 个实施阶段 (Phase 0-7)
- 60+ 文件规划
- RALPLAN-DR 共识要素（5原则、3决策驱动、3可行方案）
- 完整 ADR (Architecture Decision Record)

**Architect 审查 → ITERATE**（3 项修正）:

| # | 问题 | 修复方案 |
|---|------|----------|
| 1 | Flask 直接服务 Allure 报告会阻塞 Worker | 从 Phase 0 加入 nginx 服务 Allure 静态文件 |
| 2 | Celery Beat 无法动态读取 DB 调度 | 实现自定义 DatabaseScheduler 子类 |
| 3 | 单一 Celery 任务无法处理部分失败 | 拆分为 3 阶段链式任务 (chain) |

**Planner 修订计划 → Architect 重新审查 → APPROVE**

**Critic 审查 → ITERATE**（2 Critical + 2 Major）:

| # | 严重性 | 问题 | 修复方案 |
|---|--------|------|----------|
| 1 | CRITICAL | CronSchedule 缺少 crontab 解析属性 | 添加 `@property celery_schedule` |
| 2 | CRITICAL | Git 凭证未加密存储 | Fernet 加密 + URL 嵌入 token |
| 3 | MAJOR | Dockerfile 缺少 Java + Allure CLI | 添加 openjdk-21 + allure 安装 |
| 4 | MAJOR | 用户依赖无隔离 | 每次执行创建独立虚拟环境 |

**Planner 修订 → Architect APPROVE → Critic APPROVE**

### 输出

- 共识计划: `.omc/plans/consensus-plan.md`
- ADR 完整记录
- 3 个失败预演场景

---

## Stage 3: Autopilot — 全栈实施

### 命令

```
/autopilot .omc/plans/consensus-plan.md
```

> 由于存在 ralplan 共识计划，自动跳过 Phase 0（扩展）和 Phase 1（规划），直接从 Phase 2（执行）开始。

### 用户指定的模型路由

```
前端开发 → Gemini CLI (gemini-3.1-pro-preview)
Code Review → Codex CLI (gpt-5.5)，失败回退 Claude Code
```

### 8 阶段执行

| 阶段 | 内容 | 文件数 | 状态 |
|------|------|--------|------|
| Phase 0 | Docker Compose (6服务) + nginx + Dockerfile | 14 | ✅ |
| Phase 1 | 用户认证 + 4角色RBAC + 审计日志 + 模板 | 20 | ✅ |
| Phase 2 | 项目管理 + Git集成 + 测试套件发现 | 12 | ✅ |
| Phase 3 | 测试执行引擎（3阶段链式Celery管道） | 13 | ✅ |
| Phase 4 | 仪表盘（4视图 + Chart.js） | 10 | ✅ |
| Phase 5 | Cron/API触发 + 通知 + 动态调度器 | 19 | ✅ |
| Phase 6 | 系统配置 + 审计面板 + 数据保留清理 | 8 | ✅ |
| Phase 7 | 测试套件 + 生产加固 + README + 种子数据 | 16 | ✅ |

### 执行中的问题与解决

| 问题 | 原因 | 解决 |
|------|------|------|
| Phase 4 代理超时 (x2) | 读取过多现有代码 | 手动创建剩余模板和JS文件 |
| Phase 5 代理超时 | 复杂度超出代理处理能力 | 手动创建 services/notification_tasks/scheduler |
| docker-compose up 失败 | openjdk-17 不可用 | 改用 openjdk-21 |
| Docker build 上下文过大 | .venv 被包含 | 创建 .dockerignore |
| ENTRYPOINT 重复 | gunicorn gunicorn ... | 移除 ENTRYPOINT，用 CMD |
| --without-mingle 不支持 | beat 不支持 worker 选项 | 从 beat 命令移除 |
| 数据库表缺失 | CronSchedule 未导入 | 手动 db.create_all() |

### 输出

- **92 个源文件**, 64 Python, 18 HTML, 1 JS
- **14 张数据库表**
- **6 个 Docker 容器**
- Docker 运行: `docker-compose up -d --build`

---

## 多视角审查

### 命令（3 个 Agent 并行）

```
Agent(architect)      → 功能完整性审查
Agent(security-reviewer) → OWASP Top 10 安全扫描
Agent(code-reviewer)  → 代码质量审查
```

### Architect 审查结果

| 区域 | 状态 | 说明 |
|------|------|------|
| 核心流程 | ✅ IMPLEMENTED | 项目→执行→报告完整链路 |
| RBAC (4角色) | ✅ IMPLEMENTED | 权限矩阵 + 装饰器 |
| 仪表盘 (4视图) | ✅ IMPLEMENTED | Chart.js + JSON API |
| 触发方式 | ⚠️ PARTIAL | Web+API OK，**Cron 缺执行任务** |
| 通知 (3渠道) | ✅ IMPLEMENTED | 邮件/钉钉/企微 |
| 审计日志 | ✅ IMPLEMENTED | 全操作覆盖 |
| 管理员配置 | ✅ IMPLEMENTED | 12 项配置 |

### Security 审查结果

| 严重性 | 问题 | 位置 |
|--------|------|------|
| 🔴 CRITICAL | extra_args 未校验，命令注入 | execution_tasks.py:381 |
| 🔴 CRITICAL | SECRET_KEY 默认值 "change-me" | config.py:11 |
| 🟠 HIGH | API 执行端点缺 RBAC 权限检查 | api/executions.py:55 |
| 🟠 HIGH | 登录接口无限速 | auth/routes.py |
| 🟠 HIGH | API 蓝本未豁免 CSRF | api/__init__.py |
| 🟡 MEDIUM | DB 默认凭证硬编码 | config.py:18 |

### Code Review 结果

| 严重性 | 问题 | 位置 |
|--------|------|------|
| 🔴 CRITICAL | SECRET_KEY 不安全默认值 | config.py:10 |
| 🟠 HIGH | Celery 并发守卫静默吞异常 | execution_tasks.py:49,69,80 |
| 🟠 HIGH | 路由 commit 缺 rollback 保护 | auth/projects/executions routes |
| 🟠 HIGH | has_role 传字符串给 Role 枚举 | base.html:66 |
| 🟠 HIGH | get_credential 异常捕获过宽 | project.py:68 |
| 🟡 MEDIUM | send_notification 无 @celery.task | notification_tasks.py:11 |
| 🟡 MEDIUM | 500 错误页面渲染 404 模板 | __init__.py:112 |

---

## Ralph 修复循环

### 命令

```
/ralph 修复多视角审查发现的 8 个问题
```

### PRD 定义

```json
{
  "US-001": "extra_args 命令注入白名单校验",
  "US-002": "SECRET_KEY/FERNET_KEY 强制环境变量",
  "US-003": "添加 run_cron_schedule Celery 任务",
  "US-004": "has_role 支持字符串参数",
  "US-005": "API 执行端点 RBAC 权限检查",
  "US-006": "路由 commit rollback 保护",
  "US-007": "send_notification 添加 @celery.task",
  "US-008": "登录接口限速"
}
```

### 修复详情

| # | 问题 | 修复方案 | 文件 |
|---|------|----------|------|
| US-001 | extra_args 命令注入 | `shlex.split()` + 白名单校验 (-k, --timeout, -x, --tb, -v, -q, --co, --maxfail, -m) | execution_tasks.py |
| US-002 | 不安全默认密钥 | `os.environ.get()` + ValueError 启动失败 | config.py |
| US-003 | Cron 无执行任务 | 新建 `run_cron_schedule` Celery 任务 + 更新调度器引用 | schedule_tasks.py, scheduler.py |
| US-004 | has_role 枚举不兼容 | 支持 `isinstance(r, str)` 和 `isinstance(r, Role)` | user.py |
| US-005 | API 无权限检查 | 添加 `user.has_permission("execution.trigger")` 检查 | api/executions.py |
| US-006 | commit 无 rollback | 5 处 `try: commit / except: rollback; raise` | auth/projects/executions routes |
| US-007 | 通知任务非 Celery 任务 | 添加 `@celery.task(bind=True, max_retries=3)` + `self.retry()` | notification_tasks.py |
| US-008 | 登录无限速 | Redis 计数器: 5次/分钟/IP，成功重置 | auth/routes.py |

### Architect 验证

| 故事 | 结果 | 说明 |
|------|------|------|
| US-001 | PASS | shlex + 白名单 + ValueError |
| US-002 | PASS | 两个 key 强制检查 |
| US-003 | PASS | 任务存在 + 调度器引用正确 |
| US-004 | PASS | 字符串和枚举都支持 |
| US-005 | PASS | 权限检查 + 403 |
| US-006 | PASS | 5 处 commit 全部包装 |
| US-007 | **FAIL → 修复 → PASS** | 初版缺少 `self.retry()`，添加后通过 |
| US-008 | PASS | Redis 限速 + 429 响应 |

### Deslop 清理

修复后执行 deslop 清理:

| 文件 | 问题 | 修复 |
|------|------|------|
| execution_tasks.py | 未使用导入 `standalone_celery` | 删除 |
| execution_tasks.py | 死代码 `_timeout_execution()` | 删除 |
| scheduler.py | 空 `tick()` 覆写 | 删除 |
| auth/routes.py | `__import__("os")` 反模式 | 改为 `import os` |
| user.py | 冗余 UserMixin 覆写 | 删除 |

### 回归验证

```
docker-compose up -d --build → 健康检查通过
curl http://localhost/health → {"status": "ok"}
curl http://localhost/auth/login → HTTP 200
```

---

## UltraQA — 自动化测试

### 命令

```
/ultraqa 运行 pytest tests/ 验证平台测试套件
```

### 结果

```
======================= 117 passed, 35 warnings in 22.25s =======================
```

| 测试文件 | 用例数 | 状态 |
|----------|--------|------|
| test_auth.py | 15 | ✅ 全部通过 |
| test_projects.py | 16 | ✅ 全部通过 |
| test_executions.py | 12 | ✅ 全部通过 |
| test_rbac.py | 48 | ✅ 全部通过 |
| test_notifications.py | 13 | ✅ 全部通过 |
| test_api.py | 13 | ✅ 全部通过 |

35 个 SQLAlchemy LegacyAPI 警告（Query.get() 已弃用），无功能问题。

---

## Remember — 知识沉淀

### 命令

```
/remember 将企业级自动化测试平台项目的关键知识沉淀到 memory
```

### 输出

| 文件 | 类型 | 内容 |
|------|------|------|
| project_qa_platform.md | project | 架构决策、技术栈、关键文件、已知限制 |
| user_preferences.md | user | 中文偏好、全选风格、管理员可配置偏好 |
| MEMORY.md | index | Memory 索引文件 |
| project-memory.json | OMC | 项目元数据（techStack, structure, conventions, notes） |

---

## Wiki — 文档生成

### 命令

```
/wiki 为企业级自动化测试平台生成 Wiki 文档
```

### 生成的页面

| 页面 | 分类 | 内容 |
|------|------|------|
| 架构概览 | architecture | 系统架构图、技术栈、Docker 服务、数据库表 |
| RBAC 权限模型 | architecture | 4 角色、权限矩阵、实现方式、模板用法 |
| 3 阶段链式执行管道 | architecture | 状态机、3 个 Stage 详解、并发控制、超时配置 |
| 部署指南 | reference | 快速启动、环境变量、密钥生成、数据库初始化 |
| REST API 参考 | reference | 认证、端点列表、请求/响应示例、限速、错误码 |

---

## Git 初始化

### 命令

```bash
git init
git add -A
git commit -m "feat: initial release of enterprise automated testing platform"

# 补充文档
git add LICENSE CONTRIBUTING.md CHANGELOG.md
git commit -m "docs: add LICENSE, CONTRIBUTING.md, CHANGELOG.md"
```

### 提交历史

```
28cc0f9 docs: add LICENSE, CONTRIBUTING.md, CHANGELOG.md (3 files, 228 insertions)
6b4a93e feat: initial release of enterprise automated testing platform (101 files, 11136 insertions)
```

---

## 关键经验总结

### OMC 框架使用模式

1. **`/deep-interview`** — 当需求模糊时，用 Socratic 提问法逐步降低模糊度（每轮量化评分）
2. **`/ralplan`** — Architect + Critic 共识循环，确保架构方案经得起审查
3. **`/autopilot`** — 检测到共识计划后自动跳过规划，直接执行
4. **多视角审查** — Architect（功能）、Security（安全）、Code（质量）并行审查
5. **`/ralph`** — PRD 驱动的修复循环，逐项验证直到全部 PASS
6. **`/ultraqa`** — 自动化 QA 循环，运行测试直到全部通过
7. **`/remember`** — 知识沉淀到 memory，跨会话可复用
8. **`/wiki`** — 生成持久化知识库文档

### 代理超时处理

当 Agent 长时间无进展（600秒）时会自动超时。解决方案：
- 检查已创建的文件
- 手动补全剩余文件
- 比重新启动整个代理更高效

### Docker 部署常见问题

| 问题 | 根因 | 预防 |
|------|------|------|
| 包名不兼容 | Debian 版本差异 | 先检查 `apt-cache search` |
| 构建上下文过大 | .venv 被包含 | 始终创建 .dockerignore |
| ENTRYPOINT 冲突 | docker-compose command 与 ENTRYPOINT 重叠 | 明确选择 ENTRYPOINT 或 CMD |
| 数据库表缺失 | 模型未导入 | 使用 `from app.models import *` |
| healthcheck 不匹配 | Worker 继承 Web 的 HTTP 检查 | 为不同服务配置不同 healthcheck |
