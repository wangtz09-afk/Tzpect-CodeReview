# Tzpect-CodeReview

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![Code Review](https://img.shields.io/badge/code-review-green.svg)](https://github.com/wangtz09-afk/Tzpect-CodeReview)
[![AI Powered](https://img.shields.io/badge/AI-powered-ff69b4.svg)](https://github.com/wangtz09-afk/Tzpect-CodeReview)

> AI Code Review & Intelligent Fix Agent

Multi-agent collaborative automated code review tool. Built on LLM APIs (DeepSeek, DashScope, or any OpenAI-compatible endpoint), it reviews code changes, generates fixes, runs tests, and provides final verification — all with detailed reasoning.

## Features

- **4-Agent Pipeline**: Review -> Fix -> Test -> Verify, with iterative fix-review loops (up to 2 rounds)
- **Project Context Awareness**: Auto-detect frameworks (Spring Boot, Django, React, etc.) and inject context to reduce false positives
- **Custom Rules**: `.codereview.yml` for ignore patterns, check whitelists, severity overrides, team-specific rules
- **Cross-file Analysis**: Build project knowledge graph to detect interface mismatches and inheritance issues
- **Fix Quality Assessment**: Multi-dimensional validation of generated fixes (syntax, structure, semantic similarity, tests)
- **Feedback Learning**: SQLite database tracks review accuracy, learns from false positives to improve future reviews
- **Language Support**: Java, Python, JavaScript/TypeScript, Go, Rust, PHP, Ruby, Swift, Kotlin, C#, Vue, CSS, HTML, SQL, and more
- **Fix Verification**: Automatic analysis of generated fixes to detect regressions, dangerous patterns, and structural issues
- **Parallel Processing**: Review multiple files concurrently with configurable worker count
- **Checkpoint & Resume**: Save progress and resume interrupted reviews
- **Cost Tracking**: Real-time token usage and cost estimation per file and per stage
- **Rate Limiting**: Built-in token bucket algorithm prevents API rate limit errors
- **Multiple Output Formats**: Terminal (Rich), JSON, Markdown (suitable for PR comments), SARIF, HTML
- **File Output**: Save review results as JSON and Markdown files
- **GitHub Actions Integration**: Automated PR comments with review results
- **Apply Fixes**: Automatically apply AI-generated fixes to source files
- **Comprehensive Testing**: 284 unit tests covering all modules

## Installation

```bash
git clone <repo-url>
cd code-review-agent

# Install dependencies
pip install -r requirements.txt
pip install pytest  # For running tests

# Configure API key
cp .env.example .env
# Edit .env with your API key
```

## Configuration

Edit `.env`:

```bash
# Required: DeepSeek or DashScope API key
DASHSCOPE_API_KEY=your-api-key-here

# Optional: Custom API URL (for any OpenAI-compatible endpoint)
# API_URL=https://your-custom-endpoint/v1/chat/completions

# Model selection
REVIEWER_MODEL=deepseek-v4-flash
FIXER_MODEL=deepseek-v4-flash
TESTER_MODEL=deepseek-v4-flash
VERIFIER_MODEL=deepseek-v4-flash

# LLM parameters
# MAX_TOKENS=4096
# TEMPERATURE=0.3

# Review parameters
# MAX_FILES_PER_RUN=20

# API timeout and retry
# API_TIMEOUT=180
# MAX_RETRIES=3
```

## Usage

### Interactive Mode (Recommended)

Start without arguments for a guided terminal menu:

```bash
py -3 main.py
```

Or explicitly:

```bash
py -3 main.py interactive
```

You'll be guided through:
1. **Select action** — Review / Scan / Fix / HTML Report
2. **Enter path** — paste your project path (e.g. `D:\code\myproject`)
3. **Output format** — Terminal / JSON / Markdown / HTML / HTML+Save
4. **Language filter** — optional (Python / Java / Go / etc.)
5. **Severity filter** — optional (Critical / High / Medium / All)

Quick commands: type `review`, `scan`, `fix`, or `html` to skip straight to that action.

### Basic Review

```bash
# Review git changes in current directory
py -3 main.py review .

# Review specific repository
py -3 main.py review /path/to/repo

# Review staged changes only
py -3 main.py review . --staged

# Review changes since a specific commit
py -3 main.py review . --since HEAD~3
```

### Advanced Options

```bash
# Only review Java files
py -3 main.py review . --language java

# Only review Java and Python files
py -3 main.py review . --language java,python

# Only show high and critical severity issues
py -3 main.py review . --severity high

# Output as JSON (for CI/CD integration)
py -3 main.py review . --json

# Output as Markdown (for PR comments)
py -3 main.py review . --markdown

# Save results to directory
py -3 main.py review . --output-dir ./results

# Parallel processing (3 workers)
py -3 main.py review . --parallel --workers 3

# Checkpoint and resume
py -3 main.py review . --checkpoint-dir ./checkpoints --resume

# Set budget limit (stops when exceeded)
py -3 main.py review . --budget 5.0

# Verbose logging
py -3 main.py review . --verbose
```

### Scan Non-Git Projects

```bash
# Direct scan mode (no Git required)
py -3 main.py scan /path/to/project

# Scan with filters
py -3 main.py scan /path/to/project --language python --max-files 50
```

### Fix and Apply

```bash
# Review and generate fixes
py -3 main.py fix .

# Preview fixes (dry run)
py -3 main.py apply-fixes . --dry-run

# Apply fixes with confirmation
py -3 main.py apply-fixes .

# Apply fixes without confirmation
py -3 main.py apply-fixes . --force
```

## Architecture

```
code-review-agent/
├── .env                              # Configuration
├── .github/workflows/                # GitHub Actions
├── agents/
│   ├── base.py                       # Agent base class with prompt truncation
│   ├── reviewer.py                   # Code review agent (30+ checks)
│   ├── fixer.py                      # Code fix generation
│   ├── tester.py                     # Test generation and execution
│   └── verifier.py                   # Final verification (3-level decision)
├── core/
│   ├── git_ops.py                    # Git operations and file scanning
│   └── pipeline.py                   # Multi-agent orchestration
├── utils/                        # Utility modules
│   ├── llm.py                    # LLM client with caching and retry
│   ├── logger.py                 # Structured logging with rotation
│   ├── rate_limiter.py           # Token bucket rate limiting
│   ├── checkpoint.py             # Checkpoint and resume
│   ├── cost_tracker.py           # Token and cost tracking
│   ├── fix_verifier.py           # Fix correctness verification
│   ├── fix_quality.py            # Fix quality assessment
│   ├── feedback_db.py            # Feedback learning (SQLite)
│   ├── parallel.py               # Parallel file processing
│   ├── config_validator.py       # Config validation
│   ├── incremental.py            # Incremental review mode
│   ├── output_formatter.py       # SARIF, HTML, JSON output
│   ├── project_context.py        # Project context detection
│   ├── custom_rules.py           # Custom rules engine
│   ├── cross_file_analyzer.py    # Cross-file analysis
│   └── progress_dashboard.py     # Real-time progress dashboard
├── config.py                     # Configuration management
├── main.py                       # CLI entry point
├── interactive.py                # Interactive terminal menu mode
├── pyproject.toml                # Project metadata
├── requirements.txt              # Dependencies
└── tests/                        # 284 unit tests
```

## Review Checks

The Reviewer Agent checks for:

### Security
- SQL Injection, XSS, hardcoded secrets, path traversal, CSRF, insecure deserialization

### Bugs and Correctness
- Null/empty handling, off-by-one errors, race conditions, resource leaks, error handling, type conversion

### Performance
- N+1 queries, inefficient string operations, unnecessary object creation, missing pagination

### Code Quality
- Magic numbers, dead code, naming issues, excessive complexity

### Language-Specific
- **Java**: Spring annotations, JDBC patterns, collections, concurrency
- **Python**: eval/exec/pickle, mutable defaults, resource management
- **JavaScript/TypeScript**: innerHTML, eval, document.write, async patterns
- **Go**: goroutine leaks, error handling, defer patterns

## Fix Verification

The FixVerifier module analyzes generated fixes for:

- **Dangerous patterns**: eval(), exec(), os.system(), raw SQL statements, innerHTML
- **Regressions**: Removed imports, removed functions/methods, unbalanced braces
- **Excessive changes**: Flags fixes that remove >50% of the original file
- **Regression risk**: Classifies as low/medium/high based on issue severity

## Output Formats

### Terminal (default)
Rich console output with colored severity indicators, detailed issue descriptions, and fix previews.

### JSON
Structured output with full review data, suitable for CI/CD pipelines and further processing.

### Markdown
GitHub-flavored markdown with issue tables, fix suggestions, and test results - ideal for PR comments.

## GitHub Actions

The included workflow automatically reviews PRs and comments results:

```yaml
# .github/workflows/code-review.yml
# Add DASHSCOPE_API_KEY to repository secrets
```

## Testing

```bash
# Run all tests
py -3 -m pytest tests/ -v

# Run with coverage
py -3 -m pytest tests/ -v --cov=agents --cov=core --cov=utils

# Run specific test module
py -3 -m pytest tests/test_git_ops.py -v
```

## CLI Reference

### interactive
Start the interactive terminal menu (or run `py -3 main.py` with no arguments).

### review
Review code changes in a repository.

| Option | Description |
|--------|-------------|
| `--staged` | Only review staged changes |
| `--since <commit>` | Review changes since commit |
| `--json` | Output as JSON |
| `--markdown` | Output as Markdown |
| `--sarif` | Output as SARIF (GitHub Code Scanning) |
| `--html` | Output as HTML report |
| `--max-files <n>` | Maximum files to review (default: 20) |
| `--severity <level>` | Minimum severity to display |
| `--language <lang>` | Filter by language (comma-separated) |
| `--output-dir <path>` | Save results to directory |
| `--parallel` | Enable parallel processing |
| `--workers <n>` | Parallel worker threads (default: 3) |
| `--checkpoint-dir <path>` | Checkpoint directory for resume |
| `--resume` | Resume from last checkpoint |
| `--budget <usd>` | Max budget in USD |
| `--rate-limit <n>` | API rate limit (calls/sec, default: 1.0) |
| `--verbose` | Show detailed debug logs |
| `--no-context` | Disable project context detection |
| `--no-custom-rules` | Disable custom rules (.codereview.yml) |
| `--no-cross-file` | Disable cross-file analysis |
| `--no-fix-quality` | Disable fix quality assessment |
| `--no-feedback` | Disable feedback learning |
| `--collect-feedback` | Collect feedback on review results |

### scan
Scan and review source files in non-Git projects.

### fix
Review and generate fix suggestions.

### apply-fixes
Apply AI-generated fixes to source files.

| Option | Description |
|--------|-------------|
| `--dry-run` | Preview only, don't modify files |
| `--force` | Skip confirmation |

### feedback
Record feedback on a review issue (accepted/dismissed/modified).

### feedback-stats
Show feedback statistics and acceptance rates.

### validate-config
Validate configuration and test API connectivity.

| Option | Description |
|--------|-------------|
| `--test-connection` | Also test API connectivity |

## License

MIT
