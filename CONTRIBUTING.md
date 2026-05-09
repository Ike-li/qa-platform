# Contributing to QA Platform

感谢你对 QA Platform 的贡献兴趣！

## 开发环境搭建

```bash
# 1. 克隆仓库
git clone <repo-url> qa-platform && cd qa-platform

# 2. 创建虚拟环境
python -m venv .venv && source .venv/bin/activate

# 3. 安装依赖
pip install -r requirements.txt

# 4. 复制环境变量
cp .env.example .env
# 编辑 .env 设置 SECRET_KEY 和 FERNET_KEY

# 5. 启动服务
docker compose up -d mysql redis

# 6. 初始化数据库
flask db init && flask db upgrade
python scripts/seed_data.py

# 7. 启动开发服务器
flask run --debug
```

## 项目结构

```
app/
├── models/          # SQLAlchemy 数据模型
├── auth/            # 认证 + RBAC
│   ├── routes.py    # 登录/登出/个人资料
│   ├── forms.py     # 表单
│   └── decorators.py # 权限装饰器
├── projects/        # 项目管理 + Git 集成
├── executions/      # 测试执行引擎
├── dashboard/       # 仪表盘 + 指标
├── api/             # REST API
├── notifications/   # 通知渠道
├── admin/           # 系统管理
├── tasks/           # Celery 任务
├── templates/       # Jinja2 模板
└── utils/           # 工具函数
```

## 开发规范

### 代码风格
- Python: PEP 8，使用 type hints
- 模板: Jinja2 + Bootstrap 5
- 提交: Conventional Commits (`feat:`, `fix:`, `docs:` 等)

### 分支策略
- `main` — 生产分支
- `develop` — 开发分支
- `feature/*` — 功能分支
- `fix/*` — 修复分支

### 测试
```bash
# 运行所有测试
.venv/bin/python -m pytest tests/ -v

# 运行特定测试
.venv/bin/python -m pytest tests/test_rbac.py -v

# 查看覆盖率
.venv/bin/python -m pytest tests/ --cov=app
```

### 数据库迁移
```bash
docker compose exec web flask db migrate -m "描述"
docker compose exec web flask db upgrade
```

### 添加新功能
1. 创建模型 → `app/models/`
2. 创建蓝图 → `app/<feature>/`
3. 注册蓝图 → `app/__init__.py`
4. 创建模板 → `app/templates/<feature>/`
5. 添加测试 → `tests/test_<feature>.py`
6. 更新审计日志调用

### RBAC 权限
新功能必须在 `app/models/user.py` 的 `ROLE_PERMISSIONS` 中定义权限，并在路由中使用装饰器：
```python
from app.auth.decorators import permission_required

@bp.route("/new-feature")
@permission_required("feature.view")
def view_feature():
    ...
```

### Celery 任务
新异步任务使用 `@celery.task` 装饰器，任务名使用完整模块路径：
```python
@celery.task(name="app.tasks.my_module.my_task", bind=True, max_retries=3)
def my_task(self, arg):
    ...
```

## 提交前检查清单
- [ ] 测试通过 (`pytest tests/`)
- [ ] 审计日志已添加
- [ ] RBAC 权限已配置
- [ ] 模板继承 `base.html`
- [ ] CSRF token 已包含在表单中
EOF
echo "CONTRIBUTING.md created"