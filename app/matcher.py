"""规则匹配层：关键词（日/中/英 + 同义词映射）、价格区间、指定卖家、品牌。

匹配策略：
- 关键词：命中即算「命中」；关键词内含空格表示 AND（如「ポケモン カード」需同时出现）。
- 中文关键词自动映射为日文同义词（可扩展 SYNONYMS 表）。
"""
from __future__ import annotations

import re
from typing import Iterable, List

from .models import Keyword, Rule

# 常见中文 → 日文同义词映射（按需扩展；关键词抓取时统一做日文归一，保留原词）
SYNONYMS: dict[str, list[str]] = {
    "海贼王": ["ワンピース", "ワンピ", "onepiece", "one piece"],
    "龙珠": ["ドラゴンボール", "dragon ball", "DB"],
    "宝可梦": ["ポケモン", "ポケカ", "pokemon", "pokémon"],
    "口袋妖怪": ["ポケモン", "ポケカ", "pokemon", "pokémon"],
    "高达": ["ガンダム", "gundam"],
    "任天堂": ["ニンテンドー", "nintendo"],
    "游戏王": ["遊戯王", "遊☆戯☆王", "yu-gi-oh", "yugioh"],
    "圣斗士": ["聖闘士星矢", "saint seiya"],
    "火影忍者": ["ナルト", "naruto"],
    "数码宝贝": ["デジモン", "digimon"],
    "最终幻想": ["ファイナルファンタジー", "final fantasy"],
    "塞尔达": ["ゼルダ", "zelda"],
    "怪物猎人": ["モンスターハンター", "monster hunter"],
    "手办": ["フィギュア", "figure"],
    "模型": ["プラモデル", "プラモ", "model kit", "ガンプラ"],
    "游戏机": ["ゲーム機", "ゲーム"],
    "二手": ["中古", "used"],
}


def expand_keyword(keyword: str) -> List[str]:
    """把一条关键词扩展为候选检索词列表（含同义词映射），用于匹配。"""
    candidates = [keyword]
    lower = keyword.lower()
    for zh, jp_list in SYNONYMS.items():
        if zh in keyword:
            candidates.extend(jp_list)
        if zh.lower() in lower:
            candidates.extend(jp_list)
    # 去重保序
    seen: set[str] = set()
    result: List[str] = []
    for c in candidates:
        if c not in seen:
            seen.add(c)
            result.append(c)
    return result


def _normalize(text: str) -> str:
    """归一化：小写、去空白。"""
    return re.sub(r"\s+", "", (text or "").lower())


def keyword_matches(title: str, keyword: str) -> bool:
    """单条关键词是否命中标题。含空格 = AND 逻辑（多个词都出现）。"""
    norm_title = _normalize(title)
    parts = [p for p in keyword.split() if p]
    if not parts:
        return False
    return all(_normalize(p) in norm_title for p in parts)


def title_matches_any_keyword(title: str, keywords: Iterable[Keyword]) -> bool:
    """标题命中任一启用关键词（含同义词映射）即返回 True。"""
    for kw in keywords:
        if not kw.enabled:
            continue
        for candidate in expand_keyword(kw.keyword):
            if keyword_matches(title, candidate):
                return True
    return False


def rule_allows(
    platform: str,
    title: str,
    price: int,
    seller: str,
    rules: Iterable[Rule],
) -> bool:
    """高级规则过滤：价格区间 / 指定卖家 / 品牌（任一启用规则满足即可）。

    返回 True 表示通过全部规则约束。
    """
    enabled = [r for r in rules if r.enabled]
    # 无启用规则 → 全部放行
    if not enabled:
        return True

    # 平台不匹配的规则不参与约束
    platform_rules = [r for r in enabled if not r.platform or r.platform == platform]
    if not platform_rules:
        return True

    norm_title = _normalize(title)
    for r in platform_rules:
        if r.price_min is not None and price < r.price_min:
            continue
        if r.price_max is not None and price > r.price_max:
            continue
        if r.seller_id and r.seller_id not in (seller or ""):
            continue
        if r.brand and _normalize(r.brand) not in norm_title and _normalize(r.brand) not in _normalize(seller or ""):
            continue
        # 该规则所有显式条件都满足
        return True
    return False
