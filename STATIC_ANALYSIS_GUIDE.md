# 多语言静态分析工具配置指南

本项目支持对多种编程语言进行代码审查和静态分析。

## 📦 已安装的工具

### Python 工具（通过 pip）
```bash
# 安装命令（已完成）
pip install ruff bandit semgrep mypy

# 或使用 requirements.txt
pip install -r requirements.txt
```

### JavaScript/TypeScript 工具（通过 npm）
```bash
# 安装命令
npm install

# 或全局安装 ESLint
npm install -g eslint
```

## 🔧 使用方法

### Python 代码扫描

#### 1. Ruff - 快速 Linter（推荐首选）
```powershell
# 检查所有问题
.\venv\Scripts\ruff.exe check agent_core

# 自动修复
.\venv\Scripts\ruff.exe check agent_core --fix

# 格式化代码
.\venv\Scripts\ruff.exe format agent_core
```

#### 2. Bandit - 安全扫描
```powershell
# 扫描安全漏洞
.\venv\Scripts\bandit.exe -r agent_core

# 生成详细报告
.\venv\Scripts\bandit.exe -r agent_core -f json -o security_report.json
```

#### 3. Mypy - 类型检查
```powershell
# 类型检查
.\venv\Scripts\mypy.exe agent_core

# 严格模式
.\venv\Scripts\mypy.exe agent_core --strict
```

#### 4. Semgrep - 代码模式匹配（支持多语言）
```powershell
# 自动检测规则
.\venv\Scripts\semgrep.exe --config=auto agent_core

# 使用特定规则集
.\venv\Scripts\semgrep.exe --config=p/python agent_core

# 扫描安全问题
.\venv\Scripts\semgrep.exe --config=p/security-audit agent_core

# 扫描所有支持的语言（包括 JS/TS/Java/Go 等）
.\venv\Scripts\semgrep.exe --config=auto .
```

### JavaScript/TypeScript 代码扫描

#### 1. ESLint - JS/TS Linter
```bash
# 检查 JS/TS 文件
npm run lint:js

# 自动修复
npm run lint:js:fix

# 或直接使用命令
npx eslint . --ext .js,.jsx,.ts,.tsx
```

#### 2. Prettier - 代码格式化
```bash
# 检查格式
npm run format:check

# 自动格式化
npm run format
```

#### 3. StyleLint - CSS/SCSS Linter
```bash
# 检查样式文件
npm run lint:style

# 自动修复
npm run lint:style:fix
```

### 其他语言支持（通过 Semgrep）

Semgrep 原生支持 30+ 种语言：

```powershell
# Java
.\venv\Scripts\semgrep.exe --config=p/java .

# Go
.\venv\Scripts\semgrep.exe --config=p/golang .

# C/C++
.\venv\Scripts\semgrep.exe --config=p/c .

# Ruby
.\venv\Scripts\semgrep.exe --config=p/ruby .

# PHP
.\venv\Scripts\semgrep.exe --config=p/php .

# Rust
.\venv\Scripts\semgrep.exe --config=p/rust .
```

## 🎯 集成到 AI Agent

### 工具注册示例

在 `agent_core/tools/executor.py` 中添加静态分析工具：

```python
def scan_with_ruff(args: Dict[str, Any]) -> str:
    """使用 Ruff 扫描 Python 代码"""
    import subprocess
    path = args.get("path", "agent_core")
    result = subprocess.run(
        ["ruff", "check", path, "--output-format=json"],
        capture_output=True,
        text=True
    )
    return result.stdout

def scan_with_semgrep(args: Dict[str, Any]) -> str:
    """使用 Semgrep 扫描多语言代码"""
    import subprocess
    path = args.get("path", ".")
    language = args.get("language", "auto")
    result = subprocess.run(
        ["semgrep", f"--config=p/{language}", path, "--json"],
        capture_output=True,
        text=True
    )
    return result.stdout

# 注册工具
SCANNER_TOOLS = {
    "scan_python_ruff": scan_with_ruff,
    "scan_security_bandit": scan_with_bandit,
    "scan_multi_language": scan_with_semgrep,
}
```

## 📊 配置文件说明

### Python
- `ruff.toml` - Ruff 配置（代码质量、格式化）
- `.bandit` - Bandit 安全扫描配置
- `pyproject.toml` - Mypy 类型检查配置

### JavaScript/TypeScript
- `eslint.config.mjs` - ESLint 配置（ES2024 格式）
- `.prettierrc` - Prettier 格式化配置
- `.stylelintrc` - StyleLint CSS 检查配置
- `package.json` - npm 依赖管理

### 通用
- `.gitignore` - Git 忽略规则（已包含工具产生的临时文件）

## 🔥 推荐的扫描流程

### 1. 快速扫描（用于 CI 或快速反馈）
```powershell
# Python
.\venv\Scripts\ruff.exe check agent_core --select F,E

# JavaScript（如果有）
npm run lint:js
```

### 2. 完整扫描（用于深度审查）
```powershell
# Python - 所有检查
.\venv\Scripts\ruff.exe check agent_core
.\venv\Scripts\bandit.exe -r agent_core
.\venv\Scripts\mypy.exe agent_core

# 多语言 - Semgrep
.\venv\Scripts\semgrep.exe --config=auto .

# JavaScript（如果有）
npm run lint:all
```

### 3. 安全扫描（定期执行）
```powershell
# Python 安全
.\venv\Scripts\bandit.exe -r agent_core -f screen

# 多语言安全
.\venv\Scripts\semgrep.exe --config=p/security-audit .
```

## 💡 与大模型结合的最佳实践

1. **先用静态分析工具定位问题** → 获得准确的错误位置和类型
2. **将扫描结果传给大模型** → 让模型解释问题、提供修复建议
3. **模型生成修复代码** → 再次扫描验证是否解决

示例工作流：
```
用户请求 → Ruff 扫描 → 发现 10 个问题
         → 将问题列表+代码传给 LLM
         → LLM 分析并生成修复
         → 应用修复 → Ruff 再次扫描 → 确认已解决
```

## 📈 性能对比

| 工具 | 语言 | 速度 | 准确率 | 适用场景 |
|------|------|------|--------|----------|
| Ruff | Python | ⚡⚡⚡⚡⚡ | ⭐⭐⭐⭐ | 日常开发、CI |
| Bandit | Python | ⚡⚡⚡⚡ | ⭐⭐⭐⭐⭐ | 安全审计 |
| Mypy | Python | ⚡⚡⚡ | ⭐⭐⭐⭐ | 类型安全 |
| Semgrep | 多语言 | ⚡⚡⚡ | ⭐⭐⭐⭐⭐ | 深度分析 |
| ESLint | JS/TS | ⚡⚡⚡⚡ | ⭐⭐⭐⭐ | 前端代码 |
| LLM | 所有 | ⚡ | ⭐⭐⭐⭐⭐ | 复杂问题理解 |

**建议策略**：静态分析工具处理 80% 的常见问题，LLM 处理 20% 的复杂逻辑和设计问题。
