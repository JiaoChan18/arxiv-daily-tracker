# 📡 arXiv Daily Tracker

> 每日自动抓取 arXiv `quant-ph` 新论文，智谱 AI 提炼中英双语摘要，同步至 Obsidian 知识库。

---

## ✨ 核心功能

| 功能 | 说明 |
|------|------|
| 🤖 **智谱 AI 提炼** | GLM-4-Flash 输出核心价值 + 高亮中英双语摘要，拒绝套话式总结 |
| 📚 **Obsidian 同步** | 自动推送 Markdown 到 `obsidian-cmrunner` 仓库 |
| 🗂️ **智能归档** | 按年份分类存入 `arxiv/YYYY/`，标题即文件名 |
| 📬 **多模态通知** | 支持 `obsidian` / `email` / `both` 三种模式自由切换 |

---

## ⚙️ 配置

### 必填 Secrets（GitHub Actions）

| Secret | 说明 |
|--------|------|
| `ZHIPUAI_API_KEY` | 智谱 AI API 密钥 |
| `OBSIDIAN_SYNC_TOKEN` | 推送到 obsidian-cmrunner 仓库的 PAT |

### 关键配置项（`config.yaml`）

```yaml
notify_mode: obsidian      # obsidian | email | both
arxiv:
  category: quant-ph
  max_results: null        # null = 全量抓取
```

### 本地 `.env`（邮件模式需填）

```dotenv
ZHIPUAI_API_KEY=your_key
GMAIL_ADDRESS=you@gmail.com
GMAIL_APP_PASSWORD=xxxx xxxx xxxx xxxx
```

---

## 🚀 快速开始

```bash
pip install -r requirements.txt
cp .env.example .env      # 填入密钥

python main.py            # 运行（自动选最新日期）
python main.py --date 2026-04-09 --verbose
python main.py --no-email # 本地生成，不发邮件
```

---

## 📁 输出结构

```
output/YYYY-MM-DD/
└── quant-ph-YYYY-MM-DD.md

# Obsidian 仓库同步路径
arxiv/YYYY/paper-title.md
```

---

## 📌 当前状态

- ✅ Markdown 轻量链路（主路径）
- ⛔ PDF 生成已停用（移除 pandoc/XeLaTeX 依赖）
- 🔄 GitHub Actions 每日 08:00 Copenhagen 自动触发

---

## 📖 进阶文档

- [`CLAUDE.md`](CLAUDE.md) — 代码规范
- [`SPEC.md`](SPEC.md) — 完整产品规格
- [`config.yaml`](config.yaml) — 用户配置

---

MIT License
