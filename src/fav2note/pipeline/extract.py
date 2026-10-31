"""AI 提炼：逐字稿 -> 结构化草稿。"""

from __future__ import annotations

import json
import re

from ..config import Config
from ..models import Item, NoteDraft, Transcript

SYSTEM = """你在帮用户把一条视频整理成能反复看的知识笔记。用户说过"不要水"，注意：

【内容】
1. 按内容自然分节，3-6 段，每段给准确时间码（取逐字稿行首）。
2. 每段第一条是这段的主题（直接说事，别用"这段介绍…"开头），其余 2-4 条是细节：
   数字、参数、命令、工具名、判断标准、先后顺序、正误对比。
3. 禁止"要注意方法""很重要""因人而异"这类没有信息量的话。
4. steps 只在有明确操作流程时给；pitfalls 只写作者真正提醒过的坑。
5. summary 结论先行：解决什么问题、答案是什么、谁适合看，150-250 字。

【写法】
6. 短句，一句一件事。不用"首先/其次/最后/综上"这类模板词。
7. 不复述标题，不写"本期视频介绍了…"。
8. 中英文之间留空格。
9. 逐字稿有识别错误。人名/产品名拿不准就保留原词加〔?〕，禁止猜。
10. 内容必须来自逐字稿，不要补充你自己的知识。
11. 严格输出 JSON。"""

SCHEMA = """只输出 JSON：
{
  "one_liner": "一句话结论，30字内",
  "category": "技术AI|学习方法|思维认知|职场商业|科普知识|技能教程|习惯自律|书影推荐",
  "summary": "150-250字",
  "sections": [{"time": "01:23", "title": "6-12字", "points": ["具体要点"]}],
  "steps": ["可照做的步骤"],
  "tools": ["工具/软件/网站，带用途"],
  "pitfalls": ["作者提到的坑"],
  "quotes": ["信息量最高的一句，≤20字"],
  "takeaways": ["3-5条可迁移的原则，不复述分节"],
  "closing": "80-150字：为什么成立、边界在哪、最值得记住的一点",
  "tags": ["3-6个标签"],
  "density": 1到5
}"""

CATEGORIES = {
    "技术AI", "学习方法", "思维认知", "职场商业",
    "科普知识", "技能教程", "习惯自律", "书影推荐",
}


class Extractor:
    def __init__(self, config: Config) -> None:
        self.config = config
        self._client = None

    @property
    def client(self):
        if self._client is None:
            from openai import OpenAI

            self._client = OpenAI(
                api_key=self.config.require_api_key(),
                base_url=self.config.base_url,
                timeout=180,
            )
        return self._client

    def run(self, item: Item, transcript: Transcript) -> NoteDraft:
        prompt = (
            f"标题：{item.title}\n作者：{item.author}\n平台：{item.platform}\n"
            f"类型：{item.kind}\n点赞：{item.liked}\n\n"
            f"带时间码的逐字稿：\n{transcript.text}\n\n{SCHEMA}"
        )
        return self._request(prompt, item)

    def run_from_text(self, item: Item, text: str, note_kind: str = "图文") -> NoteDraft:
        """没有语音时走这条：用 OCR 出来的文字，实在没有就只靠标题。"""
        body = (
            f"标题：{item.title}\n作者：{item.author}\n平台：{item.platform}\n"
            f"类型：{note_kind}\n点赞：{item.liked}\n\n"
        )
        if text.strip():
            body += (
                "这条没有语音，下面是从图片里 OCR 出来的文字，可能断行错乱，"
                "请按上下文理解后提炼：\n\n" + text.strip()
            )
        else:
            body += (
                "这条没有语音，也没有识别到可读文字。只根据标题给出一份克制的笔记："
                "summary 说明它大概在讲什么、适合谁；sections 给空数组；"
                "how_to 与 takeaways 尽量为空，不要编造具体步骤。"
            )
        return self._request(body + "\n\n" + SCHEMA, item)

    def _request(self, prompt: str, item: Item) -> NoteDraft:
        response = self.client.chat.completions.create(
            model=self.config.model,
            messages=[{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0.3,
        )
        raw = response.choices[0].message.content or "{}"
        return self._parse(raw, item)

    def _parse(self, raw: str, item: Item) -> NoteDraft:
        try:
            data = json.loads(raw)
        except ValueError:
            match = re.search(r"\{.*\}", raw, re.S)
            data = json.loads(match.group(0)) if match else {}

        def as_list(value, limit=10) -> list[str]:
            if isinstance(value, str):
                value = [value]
            if not isinstance(value, list):
                return []
            return [" ".join(str(v).split()) for v in value if str(v).strip()][:limit]

        category = str(data.get("category", "")).strip()
        if category not in CATEGORIES:
            category = "未分类"

        sections = []
        for section in data.get("sections") or []:
            if isinstance(section, dict):
                sections.append({
                    "time": str(section.get("time", "")).strip(),
                    "title": str(section.get("title", "")).strip(),
                    "points": as_list(section.get("points"), 8),
                })

        try:
            density = max(1, min(5, int(data.get("density", 3))))
        except (TypeError, ValueError):
            density = 3

        return NoteDraft(
            one_liner=str(data.get("one_liner", "")).strip(),
            summary=str(data.get("summary", "")).strip(),
            category=category,
            sections=sections,
            steps=as_list(data.get("steps")),
            tools=as_list(data.get("tools")),
            pitfalls=as_list(data.get("pitfalls")),
            quotes=as_list(data.get("quotes"), 5),
            takeaways=as_list(data.get("takeaways"), 6),
            closing=str(data.get("closing", "")).strip(),
            tags=as_list(data.get("tags"), 6),
            density=density,
        )
