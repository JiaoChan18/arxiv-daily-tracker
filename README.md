# ArXiv 量子物理每日速递 (arXiv Daily Tracker)

> 每天早晨 08:00 (Copenhagen)，自动抓取 arXiv `quant-ph` 分类下的所有新论文，用 LLM 进行**价值提炼**而非通识科普，渲染成带高亮的中英双语 PDF，直接投递到你的邮箱。

专为量子信息方向科研人员打造的"早报机器人"——打开邮件，本日全部新论文的**研究贡献**已被压缩成 1–2 句直述，摘要关键部分被荧光笔式加粗，中英对照。

---

## 核心黑科技

- **双引擎路由** — 根据日期自动选择 arXiv RSS 接口（当日速递）或 Search API（历史日期回溯），见 `main.py` 中 `get_arxiv_latest_date()`。周末 / 节假日自动回退最多 7 天。
- **LLM 深度提炼** — 调用智谱 GLM-4-Flash，使用结构化分隔符（`===CORE_VALUE===` / `===ABSTRACT_EN===` / `===ABSTRACT_ZH===`）输出"核心价值 + 高亮英文摘要 + 高亮中文摘要"，拒绝 "本文研究了…" 的套话式总结。见 `processor/translator.py`。
- **HTML 荧光笔高亮** — LLM 在中英摘要中对**研究方法、关键指标、结论**打上对齐的 `**加粗**`，渲染为可视化高亮块，LaTeX 公式原样保留。见 `renderer/markdown_writer.py`。
- **PDF 自动渲染** — pandoc + XeLaTeX 生成带中文字体和数学公式的专业 PDF；渲染失败时自动降级为 Markdown 附件，不中断投递。见 `renderer/pdf_exporter.py`。
- **邮件自动投递** — Gmail SMTP + App Password 加密发送；单篇论文分析失败不影响整批管线（graceful degradation）。见 `notifier/email_sender.py`。

---

## 快速开始

### 1. 安装 Python 依赖

```bash
pip install -r requirements.txt
```

### 2. 安装系统依赖（PDF 渲染用）

```bash
sudo apt install pandoc texlive-xetex texlive-lang-chinese texlive-science fonts-noto-cjk
```

### 3. 配置凭据

```bash
cp .env.example .env
```

编辑 `.env`，填入：

```dotenv
ZHIPU_API_KEY=your_zhipu_api_key_here
GMAIL_ADDRESS=you@gmail.com
GMAIL_APP_PASSWORD=xxxx xxxx xxxx xxxx   # Gmail App Password，非账号密码
```

Gmail App Password 在 Google 账户 → 安全 → 两步验证 → 应用专用密码 处生成。

### 4. 调整 `config.yaml`（可选）

收件人、定时时间、模型名等都在 `config.yaml`，默认值开箱即用。

---

## 运行示例

```bash
# 每日常规运行：自动选最新一批 → 翻译 → 渲染 PDF → 发邮件
python main.py

# 指定历史日期 + 调试日志
python main.py --date 2026-04-09 --verbose

# 干跑：本地生成报告，不发邮件
python main.py --no-email

# 定时模式：按 config.yaml 里的时间每日执行 main()
python scheduler.py
```

---

## 输出目录结构

```
output/
└── YYYY-MM-DD/
    ├── quant-ph-YYYY-MM-DD.md
    └── quant-ph-YYYY-MM-DD.pdf
```

`YYYY-MM-DD` 是 arXiv 侧的目标日期（不是运行脚本的时钟日期）。

---

## 进阶文档

- [`USAGE.md`](USAGE.md) — CLI 参数与日期路由矩阵
- [`SPEC.md`](SPEC.md) — 完整产品规格
- [`CLAUDE.md`](CLAUDE.md) — 代码规范与协作约定
- [`config.yaml`](config.yaml) — 用户配置

---

## License

MIT
