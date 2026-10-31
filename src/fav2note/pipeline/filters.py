"""采集时的排除规则：标签 + 自由提示词。

标签是预制规则，勾选哪些就排除哪些；提示词留给模型做补充判断。
配置存在 data/filters.json，采集时立即生效，分类时也会参考。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

# 标签 -> 标题命中规则（宁可多给，用户自己勾）
TAG_RULES: dict[str, str] = {
    "健身运动": r"健身|锻炼|腹肌|马甲线|瘦身|减脂|增肌|塑形|拉伸|体态|瑜伽|普拉提|跑步|跳绳|深蹲|卧推|俯卧撑|翘臀|瘦腿",
    "球类竞技": r"篮球|扣篮|跳投|足球|射门|网球|羽毛球|乒乓|比赛集锦|球星|NBA|CBA|世界杯",
    "美食菜谱": r"菜谱|食谱|做法|好吃|美食|探店|下饭|小吃|烘焙|早餐|夜宵|焖|炸|煎|炖|鸡腿|鲈鱼|豆腐|面条|火锅|烧烤",
    "饮品零食": r"奶茶|咖啡|果茶|饮料|零食|甜品|蛋糕|冰淇淋|雪糕",
    "穿搭美妆": r"穿搭|美妆|护肤|发型|口红|妆容|衣橱|白衬衫|香水|美甲|染发|眼妆|底妆",
    "医美养生": r"医美|整形|祛痘|痘印|抗老|美白|养生|艾灸|拔罐|刮痧|调理",
    "游戏娱乐": r"游戏|上分|阵容|皮肤|英雄|副本|通关|BOSS|手游|端游|开黑",
    "追剧影视": r"短剧|追剧|解说|剧集|综艺|电影推荐|豆瓣|片单|花絮|明星|八卦",
    "带货优惠": r"带货|优惠|券|开箱|平替|领取|免费领|下单|链接在|小黄车|抽奖|福利|秒杀|拼团|百亿补贴",
    "情感恋爱": r"恋爱|情感|脱单|相亲|前任|暧昧|分手|结婚|婚礼|彩礼",
    "母婴育儿": r"育儿|宝宝|辅食|孕期|产后|早教|幼儿园|亲子",
    "宠物萌宠": r"猫咪|狗狗|宠物|铲屎|养猫|养狗",
    "旅行攻略": r"旅行|旅游|攻略|自驾|露营|民宿|打卡|citywalk|周边游",
    "家居装修": r"装修|家居|收纳|清洁|改造|租房|软装|智能家居|好物",
    "手工DIY": r"手工|编织|折纸|粘土|捏捏|手账|DIY|改造旧物",
    "汽车数码": r"汽车|提车|试驾|轮胎|改装|手机评测|开箱|参数对比|购机",
    "玄学星座": r"星座|塔罗|占卜|风水|转运|八字|运势",
    "搞笑段子": r"搞笑|段子|沙雕|整活|抽象|笑死|离谱",
    "励志口号": r"一定要改变|逆袭|开挂|必看|不看后悔|震惊|泪目|破防",
    "直播预告": r"直播|预告|开播|连麦",
}

DEFAULT_TAGS = list(TAG_RULES)

DEFAULT_PROMPT = "排除纯口播鸡汤、没有具体信息量的内容；优先保留有步骤、参数、工具名或判断标准的干货。"


class Filters:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.data = {"tags": DEFAULT_TAGS, "prompt": DEFAULT_PROMPT}
        if path.is_file():
            try:
                self.data.update(json.loads(path.read_text(encoding="utf-8")))
            except ValueError:
                pass

    def save(self, tags: list[str], prompt: str) -> dict:
        self.data = {"tags": [t for t in tags if t in TAG_RULES], "prompt": prompt.strip()}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
        return self.data

    def excluded(self, title: str) -> str | None:
        """命中哪个标签就返回哪个，用于采集时直接标记。"""
        for tag in self.data.get("tags", []):
            rule = TAG_RULES.get(tag)
            if rule and re.search(rule, title or ""):
                return tag
        return None
