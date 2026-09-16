from typing import Any, Dict, List, Sequence

from rasmai.engine.insights.tags import NOT_A_SKILL

# What a trait is really asking of you. A wheel with one axis per trait puts a tag carried by nine
# charts beside one carried by eighty-eight and draws them the same size, so the noisiest groups take
# the most room. Grouping them puts the weight where the evidence is, and keeps the three separate
# things the model knows about slides from competing with each other for space.
#
# A community tag is matched on its Japanese name, which is its identity; everything else on the
# wording it is shown as.
FAMILIES: Dict[str, Dict[str, Any]] = {
    "slides": {
        "label": "slide control",
        "note": "following a star where it goes, at the speed it goes",
        "members": (
            "スライド難", "一筆書き", "連結スライド", "交差", "魔法陣", "往復スライド", "早消し", "速度違い", "停止",
            "連続同始点(8分未満)", "連続同始点(8分以上)", "連続（交互）", "タップで発射", "ウミユリ配置",
            "charts with fast slides", "charts with slides that double back", "slide-heavy charts",
        ),
    },
    "rotation": {
        "label": "rotation",
        "note": "spins, turnarounds and the sweeps that set them up",
        "members": (
            "速い回転", "遅い回転", "加減速回転", "イーチ回転", "折り返し", "速い流し", "遅い流し",
            "charts with spins",
        ),
    },
    "hands": {
        "label": "hand management",
        "note": "what each hand is doing while the other is busy",
        "members": (
            "混フレ", "持ち替え", "拘束タッチホールド", "拘束タッチホールD", "イーチ難", "巻き込み注意",
            "charts that keep both hands working", "charts with a lot struck together",
            "charts that throw you across the screen", "hold-heavy charts",
        ),
    },
    "speed": {
        "label": "speed and density",
        "note": "how much arrives, how fast, and whether you can keep up",
        "members": (
            "乱打", "物量", "縦連", "微縦連", "トリル", "速いトリル", "軸押しトリル",
            "charts with a hard burst", "dense charts (890+ notes)", "very fast songs (over 210 BPM)",
        ),
    },
    "touch": {
        "label": "touch",
        "note": "the pads, on their own and mixed into everything else",
        "members": (
            "タッチ複合", "タッチ乱打", "タッチ流し", "タッチ回転", "タッチ巻き込み",
            "charts with multi-touch", "touch-heavy charts",
        ),
    },
    "reading": {
        "label": "reading",
        "note": "knowing when to hit, when the chart will not tell you plainly",
        "members": (
            "リズム難", "ハネリズム", "ソフラン", "ホールド難",
            "charts that change tempo", "slow songs (under 130 BPM)", "light charts (under 620 notes)",
        ),
    },
    "accuracy": {
        "label": "accuracy",
        "note": "what each kind of note costs you, counted off the judgement pages rather than guessed at",
        # the other families are about what a chart asks for; this one is about what your hands did
        # with it, so every note type measured from the pages belongs here rather than scattered
        "members": ("tap notes", "hold notes", "slide notes", "touch notes", "break notes",
                    "break-heavy charts"),
    },
}

ORDER = tuple(FAMILIES)

# a family needs this many charts behind it before it is drawn at all
FAMILY_MIN_CHARTS = 12


def _member_of(trait: Dict[str, Any]) -> str:
    """The family a trait belongs to, or "" when nothing claims it."""
    label = str(trait.get("label") or "")
    name = label.split(" (")[0] if label[:1] and not label[:1].isascii() else label
    for key, family in FAMILIES.items():
        if name in family["members"] or label in family["members"]:
            return key
    return ""


def family_axes(axes: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The traits rolled up into the handful of things they are really about.

    A family's offset is its traits' offsets weighted by the charts behind them, so a tag measured
    on nine charts moves it about a ninth as far as one measured on eighty-eight. That is a summary
    of what was already fitted, not a new fit: the traits underneath keep their own numbers and are
    carried along so a family can be opened up.

    :param axes: Every trait group measured, as `trait_residuals` returns them.
    :type axes: Sequence[Dict[str, Any]]
    :rtype: List[Dict[str, Any]]
    """
    held: Dict[str, List[Dict[str, Any]]] = {key: [] for key in FAMILIES}
    for trait in axes:
        if trait.get("dimension") in NOT_A_SKILL:
            continue
        key = _member_of(trait)
        if key:
            held[key].append(trait)
    out: List[Dict[str, Any]] = []
    for key in ORDER:
        traits = held[key]
        charts = sum(int(t.get("count") or 0) for t in traits)
        if not traits or charts < FAMILY_MIN_CHARTS:
            continue
        offset = sum(float(t["offset"]) * int(t.get("count") or 0) for t in traits) / charts
        inside = sorted(traits, key=lambda t: float(t["offset"]))
        out.append({
            "key": key, "label": FAMILIES[key]["label"], "note": FAMILIES[key]["note"],
            "offset": round(offset, 2), "charts": charts, "traits": len(traits),
            "plays": sum(int(t.get("plays") or 0) for t in traits),
            # a family is only as sure as what is under it: confirmed when a confirmed trait carries
            # the way it leans, rather than when the weighted number happens to look large
            "verified": any(t.get("verified") and (float(t["offset"]) < 0) == (offset < 0) for t in inside),
            "inside": inside,
        })
    return sorted(out, key=lambda family: -float(family["offset"]))


def unclaimed(axes: Sequence[Dict[str, Any]]) -> List[str]:
    """Traits no family takes, so a new one is noticed rather than quietly dropped.

    Tags about a chart's fame or the shape of its difficulty are left out: the model never fits them
    as skills, so there is nothing for a family to hold.
    """
    from rasmai.engine.insights.tags import _is_technique
    return sorted({str(t.get("label") or "") for t in axes
                   if t.get("dimension") not in NOT_A_SKILL and not _member_of(t)
                   and _is_technique(str(t.get("dimension") or ""), str(t.get("label") or ""))})
