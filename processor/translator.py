"""
translator.py — 调用 Zhipu AI (glm-4-flash) 对论文进行深度价值提炼。

专注于论文价值的深度提炼，不提供通识性科普。

每篇论文发起两次 LLM 请求：
  1. 标题翻译：将英文标题译为中文。
  2. 摘要分析：单次调用，结构化输出四段内容——
       - Core Value（1-2句核心贡献提炼）
       - Keywords（CoT 强制思考步骤：先提取 2-3 个双语核心术语）
       - Abstract (EN, 核心术语用 **加粗** 高亮，LaTeX 公式原样保留)
       - 中文摘要（对应中文术语用 **加粗** 高亮，LaTeX 公式原样保留）

失败时进行指数退避重试（最多 3 次），全部失败后抛出异常由调用方处理。
"""

import logging
import os
import re
import time

from openai import OpenAI

from fetcher.arxiv_fetcher import Paper

logger = logging.getLogger(__name__)

ZHIPU_BASE_URL = "https://open.bigmodel.cn/api/paas/v4/"
REQUEST_TIMEOUT = 45  # 秒；适当延长，减少高负载下的误超时

# System Prompt：以系统角色注入铁律约束，权重高于 user 消息。
# 分隔符必须与 _parse_analysis_output() 中的 TAGS 保持一致。
ANALYSIS_SYSTEM_PROMPT = (
    "你是一名专业量子物理学术助理。你的任务是对论文摘要进行深度价值提炼，"
    "输出面向领域内研究者的精准信息，绝非科普。\n\n"
    "【铁律，违反即为错误输出】\n"
    "1. ===CORE_VALUE=== 段落【必须】全程使用中文，严禁出现任何英文单词或句子。\n"
    "2. ===KEYWORDS=== 段落【必须】在翻译之前先提取 2-3 个核心专业术语或关键指标，"
    "格式为每行一个「EN term / 中文术语」。这是强制思考步骤，不得省略。\n"
    "3. ===ABSTRACT_EN=== 段落【必须】将 ===KEYWORDS=== 中提取的术语/指标"
    "用 **...** 加粗语法高亮，至少高亮 2 处，严禁一处都不高亮。\n"
    "4. ===ABSTRACT_ZH=== 段落【必须】将对应的中文术语/数值"
    "用 **...** 加粗语法高亮，至少高亮 2 处，严禁一处都不高亮。\n"
    "5. 【铁律】绝对禁止使用任何 HTML 标签（如 <font>、<span>、<s>、<mark> 等），"
    "唯一合法的高亮方式是 ** 加粗语法。\n"
    "6. 【铁律】** 加粗内的 LaTeX 公式 $ 符号【严禁】丢失，"
    "必须完整保留（例如 **$\\hat{\\rho}$** 合法，$ 弄丢即为错误）。\n"
    "7. 【严格排版要求/铁律】所有数学公式、变量、希腊字母及 LaTeX 数学命令"
    "（如 \\eta、\\mathcal、\\symcal 等）必须严格包含在 LaTeX 数学模式分隔符内："
    "行内公式用 $...$ 包裹（如 $\\eta$），行间公式用 $$...$$ 包裹。"
    "绝对禁止在普通文本中直接暴露任何孤立的 LaTeX 命令——"
    "裸露的 \\命令 不在 $ 内即为错误输出。\n"
    "8. 【严禁】在四个分隔符段落之外输出任何额外文字。"
)

# 摘要分析 User Prompt：强约束指令 + few-shot 示例，与 ANALYSIS_SYSTEM_PROMPT 配合使用。
ANALYSIS_PROMPT_TEMPLATE = (
    "请严格按照以下顺序输出四个段落，使用分隔符划定各段，分隔符外不得有任何额外内容。\n\n"
    "===CORE_VALUE===\n"
    "【必须用中文】1-2句，直接陈述核心贡献或发现。"
    "严禁以「本文」/「作者」开头；严禁输出英文。\n\n"
    "===KEYWORDS===\n"
    "【翻译前的强制思考步骤】提取 2-3 个核心专业术语或关键指标，"
    "格式为每行一个「EN term / 中文术语」，不得省略此步骤。\n\n"
    "===ABSTRACT_EN===\n"
    "原文摘要逐字保留。【必须】将上方 KEYWORDS 中提取的术语/指标"
    "用 **...** 加粗语法高亮（至少 2 处）。"
    "LaTeX公式内字符原样保留；所有数学符号/希腊字母/LaTeX命令必须在 $...$ 内；严禁使用任何 HTML 标签。\n\n"
    "===ABSTRACT_ZH===\n"
    "准确的中文翻译。【必须】将对应的中文术语/数值"
    "用 **...** 加粗语法高亮（至少 2 处）。"
    "LaTeX公式原样保留；所有数学符号/希腊字母/LaTeX命令必须在 $...$ 内；严禁使用任何 HTML 标签。\n\n"
    "---\n"
    "【正确输出示例】（仅作格式参考，内容与论文无关）\n\n"
    "===CORE_VALUE===\n"
    "提出了一种基于变分量子电路的错误缓解框架，在噪声量子处理器上将逻辑错误率降低了47%，"
    "无需额外物理量子比特开销。\n\n"
    "===KEYWORDS===\n"
    "variational quantum error mitigation / 变分量子错误缓解\n"
    "47% logical error rate reduction / 47%逻辑错误率降低\n"
    "zero-noise extrapolation / 零噪声外推\n\n"
    "===ABSTRACT_EN===\n"
    "We present a **variational quantum error mitigation** framework that reduces logical error rates "
    "by **47%** on near-term noisy processors without additional physical qubit overhead. "
    "The method leverages **zero-noise extrapolation** combined with a learned noise model $\\hat{{\\rho}}$.\n\n"
    "===ABSTRACT_ZH===\n"
    "我们提出了一种**变分量子错误缓解**框架，在近期噪声量子处理器上将逻辑错误率降低了**47%**，"
    "且无需额外的物理量子比特开销。该方法结合了**零噪声外推**技术与学习型噪声模型 $\\hat{{\\rho}}$。\n\n"
    "---\n"
    "以下是待处理的论文摘要原文：\n\n{text}"
)


def build_client(model: str, max_retries: int) -> tuple[OpenAI, str, int]:
    """
    构建 Zhipu AI 客户端。

    Args:
        model:       模型名称，如 'glm-4-flash'。
        max_retries: 最大重试次数。

    Returns:
        (client, model, max_retries) 三元组。
    """
    api_key = os.environ["ZHIPU_API_KEY"]
    client = OpenAI(
        api_key=api_key,
        base_url=ZHIPU_BASE_URL,
        timeout=REQUEST_TIMEOUT,  # SDK 级 socket 超时，防止连接层无限挂起
        max_retries=0,            # 禁用 SDK 内置重试，避免与手动指数退避叠加导致无限循环
    )
    return client, model, max_retries


def _parse_keywords(keywords_raw: str) -> list[tuple[str, str]]:
    """
    解析 ===KEYWORDS=== 段落，返回 (EN术语, 中文术语) 对列表。

    期望格式（每行一对，以 " / " 分隔）：
        variational quantum circuit / 变分量子线路
        47% error reduction / 47%的错误率降低

    若某行格式不符则跳过，不抛异常。

    Args:
        keywords_raw: LLM 输出的 KEYWORDS 段原始文本。

    Returns:
        [(en_term, zh_term), ...] 列表，去除首尾空白。
    """
    pairs: list[tuple[str, str]] = []
    for line in keywords_raw.splitlines():
        line = line.strip()
        if " / " in line:
            parts = line.split(" / ", 1)
            en_term = parts[0].strip()
            zh_term = parts[1].strip()
            if en_term and zh_term:
                pairs.append((en_term, zh_term))
    return pairs


def _apply_marks(text: str, terms: list[str], *, case_insensitive: bool = False) -> str:
    """
    将 terms 中的每个术语在 text 中用 **...** 加粗（每术语首次出现）。

    LaTeX 公式保护：跳过位于 $...$ 内部的匹配，避免破坏公式结构。
    已被 ** 包裹的内容不会被重复处理。

    Args:
        text:             原始摘要文本。
        terms:            待高亮的术语列表。
        case_insensitive: 是否大小写不敏感（英文摘要用 True，中文用 False）。

    Returns:
        高亮后的文本。
    """
    for term in terms:
        if not term or term in ("", " "):
            continue
        # 跳过已经存在的 ** 内容（防止重复包裹）
        if f"**{term}**" in text:
            continue
        flags = re.IGNORECASE if case_insensitive else 0
        pattern = re.escape(term)
        # 找第一个不在 LaTeX 公式 $...$ 内的匹配位置
        for m in re.finditer(pattern, text, flags=flags):
            start, end = m.start(), m.end()
            # 检查此匹配是否在 LaTeX 公式内：计算 match 之前的 $ 数量
            # 奇数个 $ 表示在公式内，跳过
            dollar_count = text[:start].count("$")
            if dollar_count % 2 == 1:
                continue  # 在公式内，跳过
            matched_text = text[start:end]
            text = text[:start] + f"**{matched_text}**" + text[end:]
            break  # 每个术语只高亮首次出现
    return text


def _strip_html(text: str) -> str:
    """
    移除文本中所有 HTML 标签及大模型可能产生的无意义碎片。

    处理对象：
    - 合法标签：<mark>、<s>、<font color="...">、<span>、<br> 等
    - 模型幻觉碎片：<read ...>、<0x...> 等不完整/未知标签
    - 仅移除标签本身，保留标签内的文本内容
    """
    # 匹配 <...> 形式的任意标签（含属性、自闭合），不贪婪以避免跨标签吞噬内容
    return re.sub(r"<[^>]+>", "", text)


def _parse_analysis_output(raw: str, fallback_abstract: str) -> tuple[str, str, str]:
    """
    从 LLM 结构化输出中提取 core_value、abstract_en_highlighted、abstract_zh 三段内容。

    分隔符顺序：CORE_VALUE → KEYWORDS → ABSTRACT_EN → ABSTRACT_ZH

    混合高亮策略：
    - 优先使用 LLM 在 ABSTRACT_EN/ABSTRACT_ZH 中直接生成的 ** 加粗；
    - 若 LLM 未生成（glm-4-flash 指令跟随限制），则用 Python 根据 KEYWORDS 段
      提取的术语进行兜底高亮，保证输出中始终有 ** 加粗标记。

    Args:
        raw:              LLM 返回的原始字符串。
        fallback_abstract: 任一段缺失时的回退值（英文原摘要）。

    Returns:
        (core_value, abstract_en_highlighted, abstract_zh) 三元组。
        解析失败时不抛异常，对应字段返回 fallback_abstract（core_value 返回空串）。
    """
    TAGS = ["===CORE_VALUE===", "===KEYWORDS===", "===ABSTRACT_EN===", "===ABSTRACT_ZH==="]

    def _extract(text: str, start_tag: str, end_tag: str | None) -> str:
        start_idx = text.find(start_tag)
        if start_idx == -1:
            return ""
        content_start = start_idx + len(start_tag)
        if end_tag is not None:
            end_idx = text.find(end_tag, content_start)
            segment = text[content_start:end_idx] if end_idx != -1 else text[content_start:]
        else:
            segment = text[content_start:]
        return segment.strip()

    core_value  = _extract(raw, TAGS[0], TAGS[1])
    keywords_raw = _extract(raw, TAGS[1], TAGS[2])
    abstract_en = _extract(raw, TAGS[2], TAGS[3])
    abstract_zh = _extract(raw, TAGS[3], None)

    # 回退：任一正文段缺失则使用英文原摘要；core_value 缺失则保持空串（渲染层会跳过）
    if not abstract_en:
        abstract_en = fallback_abstract
    if not abstract_zh:
        abstract_zh = fallback_abstract

    # 混合高亮兜底：若 LLM 未在摘要中加 **，则由 Python 根据 KEYWORDS 补充高亮
    if "**" not in abstract_en or "**" not in abstract_zh:
        keyword_pairs = _parse_keywords(keywords_raw)
        if keyword_pairs:
            en_terms = [en for en, _ in keyword_pairs]
            zh_terms = [zh for _, zh in keyword_pairs]
            if "**" not in abstract_en:
                abstract_en = _apply_marks(abstract_en, en_terms, case_insensitive=True)
            if "**" not in abstract_zh:
                abstract_zh = _apply_marks(abstract_zh, zh_terms, case_insensitive=False)

    # 最终清洗：移除模型可能残留的任何 HTML 标签碎片
    core_value  = _strip_html(core_value)
    abstract_en = _strip_html(abstract_en)
    abstract_zh = _strip_html(abstract_zh)

    return core_value, abstract_en, abstract_zh


def translate_paper(paper: Paper, client: OpenAI, model: str, max_retries: int) -> Paper:
    """
    对单篇论文执行深度价值提炼，结果写入：
      paper.title_zh              — 中文标题
      paper.core_value            — 1-2句核心贡献提炼
      paper.abstract_en_highlighted — 原文摘要（核心术语 **加粗** 高亮）
      paper.abstract_zh           — 中文摘要（核心术语 **加粗** 高亮）
    任一步骤失败时回退到英文原文，不中断整体流程。

    Args:
        paper:       待翻译的 Paper 对象（原地修改）。
        client:      已初始化的 OpenAI 客户端。
        model:       模型名称。
        max_retries: 单次翻译的最大重试次数。

    Returns:
        翻译后的 Paper 对象（同一对象）。
    """
    try:
        paper.title_zh = _translate_text(
            paper.title,
            prompt_template="将以下英文学术论文标题翻译为中文，只输出译文，不加任何解释：\n{text}",
            client=client,
            model=model,
            max_retries=max_retries,
        )
    except Exception as e:
        logger.warning(f"标题翻译失败 [{paper.arxiv_id}]：{e}。使用英文原标题。")
        paper.title_zh = paper.title

    # 摘要分析：单次调用，结构化输出 Core Value + 双语摘要（关键词加粗）
    try:
        raw = _translate_text(
            paper.abstract,
            prompt_template=ANALYSIS_PROMPT_TEMPLATE,
            client=client,
            model=model,
            max_retries=max_retries,
            system_prompt=ANALYSIS_SYSTEM_PROMPT,
        )
        paper.core_value, paper.abstract_en_highlighted, paper.abstract_zh = (
            _parse_analysis_output(raw, fallback_abstract=paper.abstract)
        )
    except Exception as e:
        logger.warning(f"摘要分析失败 [{paper.arxiv_id}]：{e}。使用英文原摘要。")
        paper.abstract_zh = paper.abstract
        paper.abstract_en_highlighted = paper.abstract
        paper.core_value = ""

    return paper


def _translate_text(
    text: str,
    prompt_template: str,
    client: OpenAI,
    model: str,
    max_retries: int,
    system_prompt: str = "",
) -> str:
    """
    调用 LLM 翻译单段文本，失败时指数退避重试。

    Args:
        text:            待翻译的原文。
        prompt_template: 包含 {text} 占位符的提示模板。
        client:          OpenAI 客户端。
        model:           模型名称。
        max_retries:     最大重试次数。
        system_prompt:   可选的 system 角色消息；非空时作为首条消息注入，
                         权重高于 user 消息，用于传递强约束指令。

    Returns:
        翻译结果字符串。

    Raises:
        最后一次重试仍失败时，重新抛出异常。
    """
    prompt = prompt_template.format(text=text)
    # 若提供了 system_prompt，将其作为最高优先级的系统指令注入
    messages: list[dict[str, str]] = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    for attempt in range(max_retries):
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=messages,
                timeout=REQUEST_TIMEOUT,
            )
            content = resp.choices[0].message.content.strip()
            # openai SDK 的 DEBUG 层只打印请求体，不打印响应体。
            # 诊断解析器问题时必须能看到 LLM 的真实返回，故在此显式落盘。
            logger.debug(f"[RAW_LLM_OUTPUT] model={model} len={len(content)}\n{content}")
            return content
        except Exception as e:
            if attempt == max_retries - 1:
                raise
            wait = 2 ** attempt  # 指数退避：1s, 2s, 4s...
            logger.debug(f"翻译请求失败（第 {attempt + 1} 次），{wait}s 后重试：{e}")
            time.sleep(wait)

    # 理论上不会到达此处
    raise RuntimeError("翻译重试耗尽")
