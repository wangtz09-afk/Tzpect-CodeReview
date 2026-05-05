# Tzpect-CodeReview

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![Code Review](https://img.shields.io/badge/code-review-green.svg)](https://github.com/wangtz09-afk/Tzpect-CodeReview)
[![AI Powered](https://img.shields.io/badge/AI-powered-ff69b4.svg)](https://github.com/wangtz09-afk/Tzpect-CodeReview)

> 基于多 Agent 协作的自动化代码审查工具。支持**任意 OpenAI 兼容 API**（DeepSeek、通义千问、OpenAI、Groq、Ollama、LM Studio 等），审查代码变更、生成修复、运行测试、最终验证 — 全部附带详细推理。

## 特性

- **4-Agent 流水线**: 审查 → 修复 → 测试 → 验证，支持迭代修复循环（最多 2 轮）
- **项目感知**: 自动检测框架（Spring Boot、Django、React 等 12 种）和语言，注入上下文减少误报
- **自定义规则**: 通过 `.codereview.yml` 配置忽略模式、检查白名单、严重度覆盖、团队特定规则
- **跨文件分析**: 构建项目知识图谱，检测接口不匹配、继承问题等跨文件问题
- **修复质量评估**: 多维度验证生成修复（语法、结构、语义相似度、测试通过）
- **反馈学习**: SQLite 数据库追踪审查准确率，从误报中学习，持续改进审查质量
- **语言支持**: Java、Python、JavaScript/TypeScript、Go、Rust、PHP、Ruby、Swift、Kotlin、C#、Vue、CSS、HTML、SQL 等
- **修复验证**: 自动分析生成的修复代码，检测回归问题、危险模式和结构异常
- **并行处理**: 并发审查多个文件，可配置工作线程数
- **断点续审**: 保存审查进度，中断后可恢复
- **成本追踪**: 实时记录 Token 使用量和费用估算
- **速率限制**: 内置令牌桶算法，防止触发 API 速率限制
- **多种输出格式**: 终端（Rich）、JSON、Markdown（适合 PR 评论）、SARIF、HTML
- **增量审查**: 只审查变更的行，节省 60-80% Token
- **实时进度面板**: 动态显示审查进度、Token 使用和预计剩余时间
- **响应缓存**: 相同 Prompt 自动缓存，减少重复 API 调用
- **GitHub Actions 集成**: 自动为 PR 添加审查评论
- **应用修复**: 自动将 AI 生成的修复应用到源文件
- **全面测试**: 212+ 单元测试覆盖所有模块

## 安装

```bash
git clone <repo-url>
cd code-review-agent

# 安装依赖
pip install -r requirements.txt
pip install pytest  # 运行测试

# 配置 API 密钥
cp .env.example .env
# 编辑 .env 填入你的 API Key
```

## 配置

编辑 `.env`：

```bash
# ── API Key（必填：设置至少一个）───
# 通用密钥（任何提供商）
API_KEY=sk-your-api-key-here

# 或使用提供商特定的名称：
# DASHSCOPE_API_KEY=...    # 通义千问/千问
# DEEPSEEK_API_KEY=...     # DeepSeek
# OPENAI_API_KEY=...       # OpenAI GPT
# GROQ_API_KEY=...         # Groq (Llama, Mistral)
# TOGETHER_API_KEY=...     # Together AI
# ANTHROPIC_API_KEY=...    # Anthropic (通过 OpenAI 兼容代理)

# ── 自定义 API 端点（可选，推荐使用）───
# 设置此项可使用任何自定义/OpenAI 兼容端点
# 示例：
#   API_URL=https://api.openai.com/v1/chat/completions
#   API_URL=https://api.groq.com/openai/v1/chat/completions
#   API_URL=http://localhost:11434/v1/chat/completions    # Ollama
#   API_URL=http://localhost:1234/v1/chat/completions     # LM Studio
# API_URL=https://your-custom-endpoint/v1/chat/completions

# ── 模型选择（必填）───
# 设置你的 API 提供商提供的模型名称
# 示例：
#   DeepSeek: deepseek-chat, deepseek-coder
#   Qwen/通义：qwen-max, qwen-plus, qwen-turbo
#   OpenAI: gpt-4o, gpt-4-turbo, gpt-3.5-turbo
#   Groq: llama-3.1-70b-versatile, mixtral-8x7b-32768
#   Together: meta-llama/Llama-3-70b-chat-hf
#   Ollama: llama3.1, codellama, deepseek-coder
REVIEWER_MODEL=your-model-name
FIXER_MODEL=your-model-name
TESTER_MODEL=your-model-name
VERIFIER_MODEL=your-model-name

# ── LLM 参数（可选）───
# MAX_TOKENS=4096
# TEMPERATURE=0.3

# ── 审查参数（可选）───
# MAX_FILES_PER_RUN=20

# ── API 超时和重试（可选）───
# API_TIMEOUT=180
# MAX_RETRIES=3
```

## 使用

### 基础审查

```bash
# 审查当前目录的 Git 变更
py -3 main.py review .

# 审查指定仓库
py -3 main.py review /path/to/repo

# 只审查暂存的变更
py -3 main.py review . --staged

# 审查最近 3 次提交的变更
py -3 main.py review . --since HEAD~3
```

### 高级选项

```bash
# 只审查 Java 文件
py -3 main.py review . --language java

# 只审查 Java 和 Python 文件
py -3 main.py review . --language java,python

# 只显示严重及以上的问题
py -3 main.py review . --severity high

# 输出为 JSON（CI/CD 集成）
py -3 main.py review . --json

# 输出为 Markdown（PR 评论）
py -3 main.py review . --markdown

# 输出为 SARIF（GitHub Code Scanning）
py -3 main.py review . --sarif

# 输出为 HTML 报告
py -3 main.py review . --html

# 保存结果到目录
py -3 main.py review . --output-dir ./results

# 并行处理（3 个工作线程）
py -3 main.py review . --parallel --workers 3

# 断点续审
py -3 main.py review . --checkpoint-dir ./checkpoints --resume

# 设置预算上限（超过后自动停止）
py -3 main.py review . --budget 5.0

# 速率限制
py -3 main.py review . --rate-limit 1.0

# 详细日志
py -3 main.py review . --verbose
```

### 扫描非 Git 项目

```bash
# 直接扫描模式（无需 Git）
py -3 main.py scan /path/to/project

# 扫描并过滤
py -3 main.py scan /path/to/project --language python --max-files 50
```

### 修复与应用

```bash
# 审查并生成修复建议
py -3 main.py fix .

# 预览修复（试运行）
py -3 main.py apply-fixes . --dry-run

# 应用修复（需确认）
py -3 main.py apply-fixes .

# 强制应用修复
py -3 main.py apply-fixes . --force
```

### 项目上下文感知（减少误报）

审查时自动检测项目的框架和语言，将上下文注入 LLM 提示：

```bash
# 自动检测（默认启用）
py -3 main.py review .

# 禁用上下文感知
py -3 main.py review . --no-context
```

支持检测 12 种框架：Spring Boot、Django、Flask、FastAPI、React、Vue、Angular、Next.js、Express.js、Gin、Rails、Laravel。

### 自定义规则（团队规范）

在项目根目录创建 `.codereview.yml`：

```yaml
# 忽略测试和生成文件
ignore_patterns:
  - "tests/*"
  - "**/generated/**"

# 不报告样式问题
disabled_checks:
  - style

# 覆盖严重度
severity_overrides:
  "SQL Injection": critical

# 团队特定指令
custom_instructions: |
  Be strict about null handling in method parameters.
```

```bash
# 启用自定义规则（默认）
py -3 main.py review .

# 禁用自定义规则
py -3 main.py review . --no-custom-rules
```

### 反馈学习

记录审查反馈，持续改进准确率：

```bash
# 标记为有效问题
py -3 main.py feedback test.py "SQL Injection" accepted

# 标记为误报
py -3 main.py feedback test.py "Magic Number" dismissed

# 查看统计
py -3 main.py feedback-stats
```

### 架构

```bash
# 验证配置是否正确
py -3 main.py validate-config

# 验证配置并测试 API 连接
py -3 main.py validate-config --test-connection
```

## 架构

```
code-review-agent/
├── .env                              # 配置文件
├── .github/workflows/                # GitHub Actions
├── agents/
│   ├── base.py                       # Agent 基类（含 Prompt 截断）
│   ├── reviewer.py                   # 代码审查 Agent（30+ 检查项）
│   ├── fixer.py                      # 代码修复生成
│   ├── tester.py                     # 测试生成与执行
│   └── verifier.py                   # 最终验证（3 级决策）
├── core/
│   ├── git_ops.py                    # Git 操作与文件扫描
│   └── pipeline.py                   # 多 Agent 编排（含错误恢复）
├── utils/
│   ├── llm.py                        # LLM 客户端（多后端 + 响应缓存）
│   ├── logger.py                     # 结构化日志（自动轮转）
│   ├── rate_limiter.py               # 令牌桶速率限制
│   ├── checkpoint.py                 # 断点续审
│   ├── cost_tracker.py               # Token 和费用追踪
│   ├── fix_verifier.py               # 修复正确性验证（10+ 语言）
│   ├── parallel.py                   # 并行文件处理（动态负载均衡）
│   ├── incremental.py                # 增量审查（只审查变更行）
│   ├── progress_dashboard.py         # 实时进度面板
│   ├── output_formatter.py           # 多格式输出（SARIF/HTML/JSON）
│   ├── config_validator.py           # 配置验证
│   ├── project_context.py            # 项目上下文感知（框架/语言检测）
│   ├── custom_rules.py               # 自定义规则引擎（YAML 配置）
│   ├── cross_file_analyzer.py        # 跨文件分析（知识图谱）
│   ├── fix_quality.py                # 修复质量评估
│   └── feedback_db.py                # 反馈学习（SQLite 追踪）
├── .codereview.yml                   # 自定义规则配置示例
├── config.py                         # 配置管理
├── main.py                           # CLI 入口
├── requirements.txt                  # 依赖
└── tests/                            # 212+ 单元测试
```

## 审查检查项

### 安全性
- SQL 注入、XSS、硬编码密钥、路径遍历、CSRF、不安全反序列化

### 缺陷与正确性
- 空值处理、差一错误、竞态条件、资源泄漏、错误处理、类型转换

### 性能
- N+1 查询、低效字符串操作、不必要对象创建、缺少分页

### 代码质量
- 魔术数字、死代码、命名问题、过度复杂

### 语言特定
- **Java**: Spring 注解、JDBC 模式、集合、并发
- **Python**: eval/exec/pickle、可变默认参数、资源管理
- **JavaScript/TypeScript**: innerHTML、eval、document.write、异步模式
- **Go**: goroutine 泄漏、错误处理、defer 模式
- **Rust**: unwrap、unsafe、类型转换
- **PHP**: exec、反序列化、SQL 注入

## 修复验证

FixVerifier 模块分析生成的修复代码：

- **危险模式**: eval()、exec()、os.system()、原始 SQL、innerHTML
- **回归问题**: 删除的导入、删除的函数/方法、不平衡的大括号
- **过度变更**: 标记删除 >50% 原始文件的修复
- **回归风险**: 根据问题严重性分类为低/中/高

## 输出格式

### 终端（默认）
富控制台输出，带颜色标识的严重级别、详细问题描述和修复预览。

### JSON
完整结构化数据，适合 CI/CD 管道和后续处理。

### Markdown
GitHub 风格 Markdown，含问题表格、修复建议和测试结果 — 适合 PR 评论。

### SARIF
静态分析结果交换格式，兼容 GitHub Code Scanning 和 Azure DevOps。

### HTML
自包含的 HTML 报告，含摘要仪表盘、问题表格和可展开的代码预览。

## GitHub Actions

内置工作流自动审查 PR 并评论：

```yaml
# .github/workflows/code-review.yml
# 在仓库 Secrets 中添加 DASHSCOPE_API_KEY
```

## 测试

```bash
# 运行所有测试
py -3 -m pytest tests/ -v

# 运行覆盖率
py -3 -m pytest tests/ -v --cov=agents --cov=core --cov=utils

# 运行特定测试模块
py -3 -m pytest tests/test_git_ops.py -v
```

## CLI 参考

### review
审查仓库中的代码变更。

| 选项 | 描述 |
|------|------|
| `--staged` | 只审查暂存的变更 |
| `--since <commit>` | 审查指定提交以来的变更 |
| `--json` | 输出为 JSON |
| `--markdown` | 输出为 Markdown |
| `--sarif` | 输出为 SARIF |
| `--html` | 输出为 HTML 报告 |
| `--max-files <n>` | 最大审查文件数（默认 20） |
| `--severity <level>` | 最低显示严重级别 |
| `--language <lang>` | 按语言过滤（逗号分隔） |
| `--output-dir <path>` | 保存结果到目录 |
| `--parallel` | 启用并行处理 |
| `--workers <n>` | 并行线程数（默认 3） |
| `--checkpoint-dir <path>` | 断点续审目录 |
| `--resume` | 从上次断点恢复 |
| `--budget <usd>` | 最大预算（美元） |
| `--rate-limit <n>` | API 速率限制（次/秒） |
| `--verbose` | 显示详细调试日志 |

### scan
扫描非 Git 项目中的源文件。

### fix
审查并生成修复建议。

### apply-fixes
将 AI 生成的修复应用到源文件。

| 选项 | 描述 |
|------|------|
| `--dry-run` | 仅预览，不修改文件 |
| `--force` | 跳过确认 |

### validate-config
验证配置和 API 访问。

## 许可证

MIT
