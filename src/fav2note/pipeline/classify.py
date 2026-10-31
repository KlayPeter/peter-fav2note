"""标题分类：判断一条收藏值不值得进知识库。

规则层先挡明显无营养的（命中直接丢），剩下的交给模型判断，
结果写回条目 extra["verdict"]（keep / drop），同名 key 不会重复花钱。
"""

from __future__ import annotations

import json
import re

from ..config import Config
from ..models import Item

BLOCK = re.compile(
    r"拉伸|康复|理疗|眼肌|护眼|斜方肌|肩胛|体态|骨盆|驼背|圆肩|颈椎|腰椎|"
    r"减脂|减肥|瘦身|掉秤|增肌|塑形|瑜伽|普拉提|跟练|卧推|深蹲|硬拉|"
    r"健身|肩颈|腰疼|穿搭|白衬衫|美妆|化妆|护肤|发型|美甲|香水|"
    r"菜谱|食谱|焖|好吃|饮品|奶茶|探店|外卖|零食|豆腐|炸鸡|火锅|"
    r"捏捏|手工|编织|折纸|杂货铺|私信我|代购|好物分享|"
    r"薅羊毛|优惠券|开箱|平替|蚂蚁|蟑螂|蚊|驱虫|"
    r"vlog|旅行|露营|萌宠|猫咪|狗狗|拍照姿势|"
    r"短剧|搞笑|段子|游戏|上分|阵容|明星|八卦|篮球|NBA|"
    r"情感|恋爱|脱单|相亲"
)

WHITE = re.compile(
    r"学习|习惯|效率|自律|时间管理|认知|思维|读书|书单|笔记|记忆|备考|考试|"
    r"方法论|复盘|决策|逻辑|职场|理财|副业|开源|教程|工作流|提示词|"
    r"AI|编程|产品|设计|算法|模型"
)

SYSTEM = """判断每条小红书/抖音收藏"看完能不能让人变强"——是否留下可复用的认知、方法、技能、习惯或优质资源。

算：技术教程、AI 工具、编程、产品分析、思维模型、心理学、哲学、学习方法与习惯、
时间管理、自律、职场商业与理财、科学历史人文科普、摄影剪辑设计教学、书单影单推荐。

不算：美食菜谱、健身动作体态减肥、化妆穿搭、恋爱情感、搞笑剧情游戏明星、
优惠带货、旅行日常、手工制作、私信引流、纯口号鸡汤。

输出 JSON 数组：[{"i":1,"keep":true}]"""


def rule_verdict(item: Item) -> str | None:
    """能用规则定的就别问模型。"""
    title = item.title or ""
    if BLOCK.search(title):
        return "drop"
    if WHITE.search(title):
        return "keep"
    return None


def classify(items: list[Item], config: Config, batch: int = 20, redo: bool = False) -> dict:
    """返回 {key: verdict}，只处理还没有结论的条目。"""
    pending = [i for i in items if redo or not i.extra.get("verdict")]
    results: dict[str, str] = {}

    remaining: list[Item] = []
    for item in pending:
        verdict = rule_verdict(item)
        if verdict:
            results[item.key] = verdict
        else:
            remaining.append(item)

    if not remaining:
        return results

    from openai import OpenAI

    client = OpenAI(api_key=config.require_api_key(), base_url=config.base_url, timeout=120)
    for start in range(0, len(remaining), batch):
        chunk = remaining[start : start + batch]
        lines = "\n".join(f'{i + 1}. {item.title[:70]}' for i, item in enumerate(chunk))
        try:
            response = client.chat.completions.create(
                model=config.model,
                messages=[
                    {"role": "system", "content": SYSTEM},
                    {"role": "user", "content": f"共 {len(chunk)} 条：\n{lines}\n\n输出：[{{\"i\":1,\"keep\":true}}]"},
                ],
                response_format={"type": "json_object"},
                temperature=0,
            )
            raw = response.choices[0].message.content or "[]"
            match = re.search(r"\[.*\]", raw, re.S)
            data = json.loads(match.group(0) if match else raw)
            got = {}
            for row in data:
                if isinstance(row, dict) and "i" in row:
                    got[int(row["i"])] = bool(row.get("keep"))
            for index, item in enumerate(chunk, start=1):
                results[item.key] = "keep" if got.get(index, True) else "drop"
        except Exception:  # noqa: BLE001 分类失败就放过，不影响主流程
            for item in chunk:
                results[item.key] = "keep"

    return results
