# arXiv Daily Tracker

> 每日自动抓取 arXiv `quant-ph` 新论文，智谱 AI 提炼中英双语摘要，通过 Obsidian 同步或邮件推送至研究者。

---

## 核心功能

| 功能 | 说明 |
|------|------|
| **智谱 AI 提炼** | GLM-4-Flash 输出核心价值 + 高亮中英双语摘要，拒绝套话式总结 |
| **Obsidian 同步** | 自动推送 Markdown 到 `obsidian-cmrunner` 仓库，按年份归档 |
| **邮件推送** | 支持 Gmail、Outlook、Yahoo 及任意 SMTP 服务器，SSL/STARTTLS/无加密三种模式 |
| **智能归档** | 按年份分类存入 `arxiv/YYYY/`，标题即文件名 |
| **多模态通知** | 支持 `obsidian` / `email` / `both` 三种模式自由切换 |

---

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置凭据

```bash
cp .env.example .env
# 编辑 .env，填入你的 API 密钥和 SMTP 凭据
```

### 3. 运行

```bash
python main.py                      # 默认运行（抓取最新日期）
python main.py --date 2026-04-09    # 指定日期
python main.py --verbose            # 详细日志
python main.py --no-email           # 仅生成报告，不发邮件
```

---

## 配置详解

### 通知模式

通过环境变量 `NOTIFY_MODE` 控制：

| 模式 | 行为 |
|------|------|
| `obsidian`（默认） | 仅同步 Markdown 到 Obsidian 仓库，不发邮件 |
| `email` | 仅发送邮件（附件含 Markdown），不产生 Git 提交 |
| `both` | 同时发邮件和同步到 Obsidian 仓库 |

### SMTP 邮件配置（`config.yaml`）

```yaml
email:
  enabled: true
  smtp_host: smtp.gmail.com        # SMTP 服务器地址
  smtp_port: 465                   # 端口号
  smtp_security: ssl               # 安全模式：ssl | starttls | none
  recipients:
    - recipient@example.com        # 收件人列表，支持多个
```

#### 常见邮件服务商配置

| 服务商 | SMTP 地址 | 端口 | 安全模式 |
|--------|-----------|------|----------|
| **Gmail** | `smtp.gmail.com` | 465 | `ssl` |
| **Outlook / Microsoft 365** | `smtp.office365.com` | 587 | `starttls` |
| **Yahoo Mail** | `smtp.mail.yahoo.com` | 465 | `ssl` |
| **QQ 邮箱** | `smtp.qq.com` | 465 | `ssl` |
| **163 邮箱** | `smtp.163.com` | 465 | `ssl` |
| **自定义** | 你的 SMTP 地址 | 你的端口 | `ssl` / `starttls` / `none` |

> **Gmail 用户注意**：需开启两步验证，然后在 [Google 账号设置](https://myaccount.google.com/apppasswords) 中生成 App Password（应用专用密码）。
>
> **Outlook 用户注意**：需在 [Microsoft 安全设置](https://account.live.com/proofs/AppPasswords) 中生成应用密码，或确认已启用 SMTP AUTH。

### SMTP 凭据（`.env`）

```dotenv
ZHIPU_API_KEY=your_zhipu_api_key_here

# SMTP 邮箱凭据（支持任意邮件服务商）
SMTP_USERNAME=you@gmail.com
SMTP_PASSWORD=xxxx xxxx xxxx xxxx

# 通知模式：obsidian | email | both
NOTIFY_MODE=obsidian
```

> **向后兼容**：旧版 `GMAIL_ADDRESS` / `GMAIL_APP_PASSWORD` 环境变量仍然可用，但会输出弃用警告。建议尽快迁移到新变量名。

### arXiv 抓取配置（`config.yaml`）

```yaml
arxiv:
  categories: [quant-ph]       # arXiv 分类，支持多个
  max_results: null            # null = 全量抓取，不设上限

llm:
  model: glm-4-flash           # 智谱 AI 模型
  max_retries: 3               # API 调用失败重试次数

schedule:
  time: "08:00"                # 定时运行时间
  timezone: "Europe/Copenhagen"

output:
  directory: ./output          # 输出目录
  formats: [markdown]          # 输出格式（PDF 已停用）
```

---

## 输出结构

```
output/YYYY-MM-DD/
└── quant-ph-YYYY-MM-DD.md

# Obsidian 仓库同步路径
50_Sync_git/arxiv/YYYY/paper-title.md
```

---

## GitHub Actions 自动化

项目通过 GitHub Actions 实现每日自动运行：

- **触发时间**：每日 UTC 01:00（对应 Copenhagen 08:00 / 北京 09:00）
- **手动触发**：支持 `workflow_dispatch` 手动运行

### 必需的 Repository Secrets

| Secret 名称 | 说明 |
|-------------|------|
| `ZHIPU_API_KEY` | 智谱 AI API 密钥 |
| `SMTP_USERNAME` | SMTP 邮箱地址（发件人） |
| `SMTP_PASSWORD` | SMTP 密码或 App Password |
| `OBSIDIAN_SYNC_TOKEN` | 推送到 obsidian-cmrunner 仓库的 GitHub PAT |

### 可选的 Repository Variables

| Variable 名称 | 默认值 | 说明 |
|---------------|--------|------|
| `NOTIFY_MODE` | `obsidian` | 通知模式：`obsidian` / `email` / `both` |

> **迁移提示**：如果你之前使用的是 `GMAIL_ADDRESS` / `GMAIL_APP_PASSWORD`，请在 GitHub 仓库的 Settings > Secrets and variables > Actions 中将它们重命名为 `SMTP_USERNAME` / `SMTP_PASSWORD`。

---

## 当前状态

- ✅ Markdown 轻量链路（主路径）
- ✅ 多邮件服务商支持（Gmail / Outlook / Yahoo / 自定义 SMTP）
- ⛔ PDF 生成已停用（移除 pandoc/XeLaTeX 依赖）
- 🔄 GitHub Actions 每日自动触发

---

## 进阶文档

- [`CLAUDE.md`](CLAUDE.md) — 代码规范与开发指南
- [`SPEC.md`](SPEC.md) — 完整产品规格
- [`config.yaml`](config.yaml) — 用户配置文件

---

MIT License
