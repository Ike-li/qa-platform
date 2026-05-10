# QA Platform 外部测试仓库规范

## 1. 概述

本文档定义 QA Platform 期望的外部测试仓库结构和规范。遵循本规范的测试仓库可以被平台自动发现、分类、执行并生成报告。

平台支持通过 Git 仓库 URL 注册外部测试项目，注册后平台会自动：

- 克隆仓库到本地工作区
- 识别并解析测试文件
- 根据目录结构自动分类测试类型
- 构建隔离的 Python 虚拟环境并安装依赖
- 执行测试并收集结果
- 生成 Allure 报告和 JUnit XML 报告

## 2. 目录结构

以下是一个符合规范的测试仓库完整目录结构示例：

```
my-test-repo/
├── README.md                    # 仓库说明文档（可选）
├── requirements.txt             # [必须] Python 依赖清单
├── conftest.py                  # [推荐] 全局 pytest fixture
├── pytest.ini                   # [可选] pytest 配置（平台不显式读取，pytest 自动发现）
├── api/                         # API 测试目录
│   ├── test_user_api.py         #   用户相关 API 测试
│   ├── test_order_api.py        #   订单相关 API 测试
│   └── test_auth.py             #   认证相关 API 测试
├── ui/                          # UI 测试目录
│   ├── test_login_page.py       #   登录页面测试
│   └── test_dashboard.py        #   仪表盘页面测试
├── performance/                 # 性能测试目录
│   ├── test_api_load.py         #   API 负载测试
│   └── test_search_perf.py      #   搜索性能测试
├── unit/                        # 单元测试目录
│   ├── test_utils.py            #   工具函数单元测试
│   └── test_models.py           #   模型单元测试
└── fixtures/                    # 测试数据目录（可选）
    ├── users.json
    └── responses.json
```

**关键原则：**

- 测试文件必须命名为 `test_*.py` 格式
- 测试类型由所在目录名自动分类
- 不需要 `__init__.py` 文件
- 隐藏目录（`.git`、`.venv`、`.github` 等）会被自动跳过

## 3. 文件命名规范

| 规则 | 说明 |
|------|------|
| 测试文件 | 必须匹配 `test_*.py`（大小写不敏感） |
| 隐藏目录 | `.git`、`.venv`、`.github` 等会被自动跳过 |
| `__init__.py` | 不需要，平台不依赖包导入机制 |
| `conftest.py` | 推荐放在仓库根目录 |
| `requirements.txt` | 必须放在仓库根目录 |

平台使用 `pathlib.rglob("test_*.py")` 递归扫描所有测试文件，因此只要文件名以 `test_` 开头、以 `.py` 结尾，放在仓库任意子目录下都会被发现。

## 4. 测试类型自动分类

平台根据测试文件所在目录的名称自动分类测试类型。分类逻辑基于目录名的词边界匹配（代码来源：`app/projects/services.py:58-63`）。

| 目录名包含 | 分类结果 | 匹配方式 |
|-----------|---------|---------|
| `api` | **API** | 词边界匹配（如 `api/`、`my_api/`、`api_tests/`） |
| `ui` | **UI** | 词边界匹配（如 `ui/`、`web_ui/`、`ui_tests/`） |
| `perf` | **PERFORMANCE** | 前缀匹配（如 `perf/`、`performance/`、`perf_tests/`） |
| `unit` | **UNIT** | 词边界匹配（如 `unit/`、`unit_tests/`） |
| 其他 | **UNIT** | 默认兜底 |

**词边界匹配**意味着目录名中包含完整单词 `api`、`ui` 或 `unit` 时才会匹配（前后以路径分隔符 `/`、`_`、`-` 等为边界）。例如：

- `tests/api/` → 匹配 `api` → 分类为 API
- `my_api_tests/` → 匹配 `api`（`_` 为边界）→ 分类为 API
- `apiary/` → 不匹配 `api`（`api` 不是独立词）→ 分类为 UNIT

**前缀匹配**仅用于 `perf`，即目录名以 `perf` 开头就会匹配：

- `performance/` → 匹配 → 分类为 PERFORMANCE
- `perf_tests/` → 匹配 → 分类为 PERFORMANCE

## 5. 测试函数发现机制

平台使用两步机制发现测试函数：

### 第一步：文件扫描

使用 `pathlib.Path.rglob("test_*.py")` 递归扫描仓库目录树，收集所有匹配的测试文件路径。

### 第二步：AST 解析

对每个测试文件使用 `ast.parse()` 解析 Python 源码，提取所有以 `test_` 开头的函数名。

- 直接定义在模块级别的 `def test_*` 函数会被发现
- 定义在类中的 `def test_*` 方法也会被发现（`ast.walk` 遍历所有节点）

这意味着以下两种写法都支持：

```python
# 方式一：模块级函数
def test_login():
    assert True

# 方式二：类中的方法
class TestLogin:
    def test_valid_user(self):
        assert True
    
    def test_invalid_password(self):
        assert True
```

## 6. requirements.txt

`requirements.txt` 文件必须放在仓库根目录，包含测试执行所需的 Python 依赖。

### 必须包含

```
pytest
```

`pytest` 是平台执行测试的必要依赖，如果缺少此包，测试执行将失败。

### 建议包含

```
allure-pytest
```

包含 `allure-pytest` 后，平台会自动附加 `--alluredir` 参数以生成 Allure 测试报告数据。

### 完整示例

```
pytest>=7.0
allure-pytest>=2.13
requests>=2.28
pytest-html>=3.2
```

### 注意事项

- 平台会在仓库克隆后根据此文件创建虚拟环境并安装依赖
- 网络访问默认在 Sandbox 模式下受限，安装过程在容器内完成
- 如果依赖安装失败，整个测试执行流程将中止

## 7. pytest 执行命令

平台在执行测试时构建如下命令格式：

```bash
<venv>/bin/pytest <test_path> --alluredir=<results> --junitxml=<junit.xml> -v --tb=short
```

其中：

| 占位符 | 说明 |
|-------|------|
| `<venv>` | 平台为项目创建的虚拟环境路径 |
| `<test_path>` | 被选中执行的测试文件或目录路径 |
| `<results>` | Allure 原始结果输出目录 |
| `<junit.xml>` | JUnit XML 报告输出文件路径 |

### 白名单参数

平台允许用户通过 UI 传入以下 pytest 参数（不在白名单中的参数将被拒绝）：

| 参数 | 说明 | 示例 |
|------|------|------|
| `-k` | 按表达式筛选测试 | `-k "test_login"` |
| `--timeout` | 测试超时时间 | `--timeout=30` |
| `-x` | 首次失败后停止 | `-x` |
| `--tb` | 回溯信息格式 | `--tb=long` |
| `-v` | 详细输出 | `-v` |
| `-q` | 简洁输出 | `-q` |
| `--co` | 仅收集不执行 | `--co` |
| `--maxfail` | 最大失败次数后停止 | `--maxfail=3` |
| `-m` | 按标记筛选测试 | `-m "smoke"` |
| `-s` | 不捕获 stdout | `-s` |

## 8. conftest.py 最佳实践

### 位置

将 `conftest.py` 放在仓库根目录，这样所有子目录中的测试文件都会自动继承其中定义的 fixture，无需额外配置。

```
my-test-repo/
├── conftest.py          # 全局 fixture，所有测试可用
├── requirements.txt
├── api/
│   └── test_api.py      # 自动继承根目录 conftest.py 的 fixture
└── unit/
    └── test_unit.py     # 同样自动继承
```

### Fixture Scope 建议

| Fixture 类型 | 建议 Scope | 原因 |
|-------------|-----------|------|
| 测试数据（fixtures） | `function` | 每个测试用例使用独立数据，避免测试间干扰 |
| HTTP 客户端 | `session` | 连接可复用，减少开销 |
| 数据库连接 | `session` | 连接池复用，测试结束后统一清理 |
| 临时文件/目录 | `function` | 每个测试独立清理 |

### 示例

```python
import pytest
import requests

@pytest.fixture(scope="session")
def api_client():
    """整个测试会话共享的 HTTP 客户端"""
    session = requests.Session()
    session.headers.update({"Content-Type": "application/json"})
    yield session
    session.close()

@pytest.fixture(scope="function")
def test_user():
    """每个测试函数独立的用户数据"""
    return {
        "username": "test_user",
        "email": "test@example.com",
        "role": "viewer"
    }
```

### 子目录 conftest.py

可以在子目录中额外放置 `conftest.py`，提供该目录专属的 fixture。子目录的 fixture 对同级及下级目录的测试可见，与根目录的 fixture 互不冲突。

## 9. 输出解析

平台执行测试后会收集两类输出用于生成报告。

### JUnit XML

pytest 通过 `--junitxml` 参数生成 JUnit XML 报告。平台解析其中的关键元素：

- `<testcase>` 元素的 `name` 属性：测试函数名称
- `<testcase>` 元素的 `classname` 属性：测试类名（模块级函数则为文件路径）
- `<testcase>` 元素的 `file` 属性：测试文件路径
- `<testcase>` 元素的 `time` 属性：测试执行耗时（秒）
- `<testsuite>` 元素的 `tests`、`failures`、`errors` 属性：汇总统计

### Allure 报告

如果项目安装了 `allure-pytest`，平台会：

1. 在 pytest 执行时自动附加 `--alluredir=<results>` 参数
2. 收集 Allure 原始结果文件
3. 通过 `allure generate` 命令生成 HTML 报告
4. 在平台 UI 中提供报告查看链接

Allure 报告包含丰富的可视化信息：测试分层结构、失败详情、附件、执行时间趋势等。

## 10. Sandbox 模式

当平台配置了 `ENABLE_SANDBOX=true` 时，测试将在 Docker 容器内隔离执行，以保障平台安全性。

### 运行环境

| 配置项 | 默认值 | 说明 |
|-------|-------|------|
| 仓库挂载 | 只读 (`/workspace`) | 测试代码不可修改，防止测试污染源码 |
| 网络访问 | 默认禁用 | 容器内无网络，防止测试访问外部资源 |
| 网络开关 | 按项目可配 | 管理员可为特定项目开启网络访问 |

### Sandbox 模式下的注意事项

- 测试不能修改仓库中的文件
- 测试不能访问外部 API 或服务（除非管理员为该项目开启了网络）
- 测试不能写入宿主机文件系统
- 如果测试需要外部依赖（如数据库、API 服务），需在平台配置中设置相应的服务依赖

### 典型的容器化执行流程

1. 平台拉取测试仓库代码到临时目录
2. 启动 Docker 容器，将代码目录以只读方式挂载到 `/workspace`
3. 在容器内创建虚拟环境并安装 `requirements.txt` 中的依赖
4. 在容器内执行 pytest 命令
5. 将测试结果（JUnit XML + Allure 原始数据）从容器内复制出来
6. 销毁容器

## 11. 常见问题

### 不需要 `__init__.py`

平台使用 `pathlib` 进行文件扫描，不依赖 Python 包导入机制。因此不需要在测试目录中放置 `__init__.py` 文件。即使放置了也不会影响功能，但属于多余文件。

### conftest.py 继承无需额外配置

`conftest.py` 放在仓库根目录后，其 fixture 会自动对所有子目录中的测试可用。这是 pytest 的原生行为，不需要在任何配置文件中额外声明。

### pytest.ini / pyproject.toml 不被平台显式读取

平台不会主动读取 `pytest.ini`、`pyproject.toml`、`setup.cfg` 等 pytest 配置文件中的设置。但是，pytest 在执行时会自动发现并使用这些文件中的配置（如自定义标记、默认参数等）。

因此，你可以在这些文件中配置 pytest 行为，但以下平台控制的参数会被覆盖：

- `--alluredir`（由平台自动设置）
- `--junitxml`（由平台自动设置）
- `-v` 和 `--tb=short`（由平台默认附加）

### 测试发现失败的常见原因

| 原因 | 解决方法 |
|------|---------|
| 文件名不匹配 `test_*.py` | 确保测试文件以 `test_` 开头 |
| 文件中没有 `def test_*` 函数 | 确保测试函数以 `test_` 开头 |
| `requirements.txt` 缺少 `pytest` | 在 `requirements.txt` 中添加 `pytest` |
| 语法错误导致 `ast.parse` 失败 | 检查 Python 语法是否正确 |

## 12. 快速开始

### 步骤一：准备测试仓库

创建一个包含以下内容的 Git 仓库：

```
my-test-repo/
├── requirements.txt    # 至少包含 pytest
├── conftest.py         # 可选：全局 fixture
├── api/
│   └── test_example.py # 你的 API 测试
└── unit/
    └── test_example.py # 你的单元测试
```

最简 `requirements.txt`：

```
pytest>=7.0
allure-pytest>=2.13
```

### 步骤二：注册到平台

1. 登录 QA Platform
2. 进入「项目管理」页面
3. 点击「新建项目」
4. 填写 Git 仓库 URL 和其他配置信息
5. 提交注册

### 步骤三：运行测试

1. 进入项目详情页
2. 选择要执行的测试（可按类型、目录、文件筛选）
3. 配置执行参数（可选）
4. 点击「执行」按钮
5. 等待执行完成，查看测试报告

## 13. Git 托管

测试模板仓库应推送到独立的 Git 仓库供用户 clone。推荐的仓库组织方式：

### 仓库结构

```
test-repo-template/
├── docs/
│   └── TEST_REPO_GUIDE.md    # 本文档
├── requirements.txt
├── conftest.py
├── README.md
├── api/
│   └── test_example.py
├── ui/
│   └── test_example.py
├── performance/
│   └── test_example.py
└── unit/
    └── test_example.py
```

### 使用方式

用户可以通过以下方式使用模板：

1. **Clone 并修改**：`git clone <template-repo-url>` 然后根据需要修改测试内容
2. **Fork**：在 Git 平台上 fork 仓库后修改
3. **作为参考**：参照模板的目录结构和规范创建自己的仓库

### 仓库维护建议

- README.md 中应包含简要说明和指向本文档的链接
- 示例测试文件应保持简单，展示正确的写法
- 定期检查模板是否与平台最新版本兼容
