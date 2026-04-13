"""
pdf_exporter.py — 将 Markdown 文件转换为 PDF，使用 pandoc + xelatex 引擎。

选用 pandoc 而非 weasyprint，原因：xelatex 对中文字符支持更成熟，
不依赖系统字体配置细节，生成的 PDF 在各平台一致性更好。

arXiv 摘要中有时含有论文自定义宏（如 \\Flb），这些宏在论文 preamble 中定义但
在我们的编译环境中不存在。export() 会自动从第一次失败的错误输出中提取这些未定义命令，
为每个命令注入 \\providecommand{\\cmd}{} 空定义后重试一次。

系统依赖（需提前安装）：
    sudo apt install pandoc texlive-xetex texlive-lang-chinese texlive-science fonts-noto-cjk
"""

import logging
import re
import subprocess
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

# pandoc 基础参数：使用 xelatex 并设置中文字体
# header-includes 注入常用 LaTeX 宏包，覆盖大多数 arXiv 物理论文的标准命令：
#   - amsmath/amssymb：数学公式环境与符号
#   - siunitx：\SI{value}{unit} 带单位数值
#   - physics：\ket, \bra, \norm 等量子力学常用命令
#   - bbm：\mathbbm{1} 单位矩阵符号
#   - xcolor + 自定义 \hl：pandoc 对 .mark 类 Span 会生成 \hl{...}，
#     我们用 \colorbox 替代 soul.sty 的 \hl，避开 soul 在 xelatex+CJK 下
#     的 token 化问题；代价是 mark 内容不折行（关键词短语场景可接受）。
_BASE_HEADER = (
    r"\usepackage{amsmath}"
    r"\usepackage{amssymb}"
    r"\usepackage{siunitx}"
    r"\usepackage{physics}"
    r"\usepackage{bbm}"
    r"\usepackage{xcolor}"
    # physics 等宏包会抢先定义 \hl（短横线/水平线辅助命令），直接 \newcommand
    # 会报 "Command \hl already defined"。先 providecommand 兜底，再 renewcommand
    # 覆盖为我们的高亮样式 —— 两种情况都能走通。
    r"\providecommand{\hl}[1]{}"
    r"\renewcommand{\hl}[1]{{\setlength{\fboxsep}{1pt}\colorbox{yellow!40}{#1}}}"
)

PANDOC_BASE_ARGS = [
    "--pdf-engine=xelatex",
    "--pdf-engine-opt=-interaction=nonstopmode",
    "-V", "CJKmainfont=Noto Sans CJK SC",  # 中文主字体
    "-V", "geometry:margin=2cm",             # 页边距
    "-V", "fontsize=11pt",
]

# 匹配行内数学 $...$，内容首尾可能有多余空格（arXiv 原稿常见写法）。
# 使用负向前/后瞻排除 $$（display math），避免误处理。
# pandoc 要求 $ 与内容之间不能有空格，否则视为普通文本。
_INLINE_MATH_RE = re.compile(r'(?<!\$)\$(?!\$)([^$\n]+?)(?<!\$)\$(?!\$)')

# 匹配 <mark>...</mark>；LLM/解析器产出的高亮标签，pandoc LaTeX writer 默认会
# 直接丢弃原始 HTML 标签，于是 PDF 里看不到高亮。预处理阶段转成 pandoc 原生的
# bracketed span（[text]{.mark}），pandoc 会为其生成 \hl{text}。
_MARK_RE = re.compile(r'<mark>(.*?)</mark>', re.DOTALL)


def _normalize_math_delimiters(text: str) -> str:
    """
    去除行内数学公式 $...$ 首尾的多余空格。

    arXiv 摘要中常见 `$ a + b $`、`$ a + b$`、`$a + b $` 写法，
    pandoc 不将首尾带空格的 $...$ 识别为数学模式，
    会导致 xelatex 报"命令只能在数学模式中使用"的错误。
    此函数统一规范化为 `$a + b$`。

    Args:
        text: 原始 Markdown 文本。

    Returns:
        规范化后的 Markdown 文本。
    """
    def _strip(m: re.Match) -> str:
        content = m.group(1).strip()
        return f'${content}$'

    return _INLINE_MATH_RE.sub(_strip, text)


def _convert_mark_to_pandoc_span(text: str) -> str:
    """
    将 <mark>X</mark> 转成 pandoc bracketed span `[X]{.mark}`。

    pandoc 的 LaTeX writer 会把 .mark 类 Span 输出为 \\hl{X}，配合 _BASE_HEADER
    中自定义的 \\hl 宏即可在 PDF 里看到黄色高亮。直接透传 HTML 标签行不通 ——
    pandoc 在 markdown→latex 方向默认丢弃未识别的 raw HTML。

    跳过两种情况，保留原文但去掉 <mark> 外壳：
      - 含 `$` 的公式内容：`\\hl` 与数学模式冲突，强行高亮会导致编译错误。
      - 含 `[` 或 `]` 的内容：会破坏 bracketed span 语法。

    Args:
        text: 预处理后的 Markdown 文本。

    Returns:
        已把 <mark> 替换为 .mark span 的文本。
    """
    def _sub(m: re.Match) -> str:
        content = m.group(1)
        if "$" in content or "[" in content or "]" in content:
            return content
        return f"[{content}]{{.mark}}"

    return _MARK_RE.sub(_sub, text)


def _extract_undefined_commands(stderr: str) -> list[str]:
    """
    从 xelatex 错误输出中提取未定义命令名列表。

    xelatex 错误格式：
        ! Undefined control sequence.
        l.339 lower bound \\(F \\ge \\Flb

    取紧跟 "Undefined control sequence" 之后那行的最后一个 \\command。

    Args:
        stderr: pandoc/xelatex 的 stderr 文本。

    Returns:
        去重后的未定义命令名列表（不含前置反斜杠）。
    """
    cmds: set[str] = set()
    lines = stderr.splitlines()
    for i, line in enumerate(lines):
        if "Undefined control sequence" in line and i + 1 < len(lines):
            context = lines[i + 1]
            # 取该行最后一个 \word 模式作为未定义命令
            found = re.findall(r'\\([A-Za-z]+)', context)
            if found:
                cmds.add(found[-1])
    return list(cmds)


def _build_pandoc_args(extra_header: str = "") -> list[str]:
    """
    构建 pandoc 命令行参数列表，可附加额外 LaTeX header 内容。

    Args:
        extra_header: 额外注入 header-includes 的 LaTeX 命令字符串。

    Returns:
        完整参数列表。
    """
    header = _BASE_HEADER + extra_header
    return PANDOC_BASE_ARGS + ["-V", f"header-includes={header}"]


def _run_pandoc(
    md_text: str,
    pdf_path: Path,
    extra_header: str = "",
) -> subprocess.CompletedProcess:
    """
    将 Markdown 文本写入临时文件并执行 pandoc 转换。

    Args:
        md_text:      预处理后的 Markdown 内容。
        pdf_path:     输出 PDF 路径。
        extra_header: 追加到 header-includes 的 LaTeX 命令（用于补充未定义宏）。

    Returns:
        subprocess.CompletedProcess（调用方检查 returncode）。
    """
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", suffix=".md", delete=False
    ) as tmp:
        tmp.write(md_text)
        tmp_path = Path(tmp.name)

    try:
        cmd = ["pandoc", str(tmp_path), "-o", str(pdf_path)] + _build_pandoc_args(extra_header)
        logger.debug(f"执行命令：{' '.join(cmd)}")
        return subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    finally:
        tmp_path.unlink(missing_ok=True)


def export(md_path: Path) -> Path | None:
    """
    将指定 Markdown 文件转换为同目录下的 PDF 文件。

    转换策略：
      1. 首次尝试使用标准宏包集合编译。
      2. 若失败，从 xelatex 错误输出中提取未定义命令名，
         为每个命令注入 \\providecommand{\\cmd}{} 空定义后重试一次。
      3. 两次均失败则返回 None，调用方降级为发送 Markdown 文件。

    Args:
        md_path: 源 Markdown 文件路径。

    Returns:
        生成的 PDF 文件路径；转换失败时返回 None。
    """
    pdf_path = md_path.with_suffix(".pdf")

    # 读取并预处理 Markdown：
    #   1. 修正 pandoc 无法识别的数学边界空格
    #   2. 把 <mark> HTML 标签转成 pandoc .mark span，使其在 LaTeX 输出中变成 \hl
    raw_text = md_path.read_text(encoding="utf-8")
    cleaned_text = _normalize_math_delimiters(raw_text)
    cleaned_text = _convert_mark_to_pandoc_span(cleaned_text)

    logger.info(f"开始生成 PDF：{pdf_path.name}")

    try:
        # ── 第一次尝试 ──────────────────────────────────────────
        result = _run_pandoc(cleaned_text, pdf_path)

        if result.returncode == 0:
            logger.info(f"PDF 生成成功：{pdf_path}")
            return pdf_path

        # ── 解析错误，注入缺失宏后重试 ──────────────────────────
        undefined_cmds = _extract_undefined_commands(result.stderr)
        if undefined_cmds:
            # \providecommand{\Flb}{} — 将未定义命令定义为空操作
            # 若原文中该命令已由宏包定义则 \providecommand 不覆盖
            fallback_defs = "".join(
                rf"\providecommand{{\{cmd}}}{{}}" for cmd in undefined_cmds
            )
            logger.warning(
                f"首次编译失败，发现未定义命令：{undefined_cmds}。"
                f"注入空定义后重试..."
            )
            result = _run_pandoc(cleaned_text, pdf_path, extra_header=fallback_defs)

            if result.returncode == 0:
                logger.info(f"PDF 重试成功（补充了 {len(undefined_cmds)} 个缺失宏）：{pdf_path}")
                return pdf_path

        logger.error(f"pandoc 转换失败（returncode={result.returncode}）：{result.stderr}")
        return None

    except FileNotFoundError:
        logger.error("未找到 pandoc 命令。请先安装：sudo apt install pandoc texlive-xetex")
        return None
    except subprocess.TimeoutExpired:
        logger.error("pandoc 转换超时（>120s），跳过 PDF 生成")
        return None
    except Exception as e:
        logger.error(f"PDF 生成时发生意外错误：{e}")
        return None
