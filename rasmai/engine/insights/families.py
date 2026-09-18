from typing import Any, Dict, List, Sequence

from rasmai.engine.insights.tags import NOT_A_SKILL

# What a trait is really asking of you. A wheel with one axis per trait puts a tag carried by nine
# charts beside one carried by eighty-eight and draws them the same size, so the noisiest groups take
# the most room. Grouping them puts the weight where the evidence is, and keeps the three separate
# things the model knows about slides from competing with each other for space.
#
# A community tag is matched on its Japanese name, which is its identity; everything else on the
# wording it is shown as.
#
# What a note type costs, measured off the judgement pages, is deliberately not here. Those offsets
# are taken against the player's own overall rate, so the five of them sum to zero: any average of
# them is zero whatever the player does, and rolling them up buried a confirmed -0.86 on breaks at
# +0.09. They are counted in plays rather than charts as well, which is not the same evidence. They
# keep their own panel and their own places in the lists.
FAMILIES: Dict[str, Dict[str, Any]] = {
    "slides": {
        "label": "slide control",
        "note": "following a star where it goes, at the speed it goes",
        "members": (
            "スライド難", "一筆書き", "連結スライド", "交差", "魔法陣", "往復スライド", "早消し", "速度違い", "停止",
            "連続同始点(8分未満)", "連続同始点(8分以上)", "連続（交互）", "タップで発射", "ウミユリ配置",
            "fast slides", "slide-heavy",
            "delayed slides", "fan slides", "chained slides",
            "overlapping loop slides", "slides at different speeds",
            "slides fired from one spot", "a slide traced straight back",
        ),
    },
    "rotation": {
        "label": "rotation",
        "note": "spins, turnarounds and the sweeps that set them up",
        "members": (
            "速い回転", "遅い回転", "加減速回転", "イーチ回転", "折り返し", "速い流し", "遅い流し",
            "spinning round the ring",
        ),
    },
    "hands": {
        "label": "hand management",
        "note": "what each hand is doing while the other is busy",
        "members": (
            "混フレ", "持ち替え", "拘束タッチホールド", "拘束タッチホールD", "イーチ難", "巻き込み注意",
            "both hands at once", "a trill over a slide",
            "reaching across the screen", "hold-heavy", "break-heavy",
        ),
    },
    "speed": {
        "label": "speed and density",
        "note": "how much arrives, how fast, and whether you can keep up",
        "members": (
            "乱打", "物量", "縦連", "微縦連", "トリル", "速いトリル", "軸押しトリル",
            "bursts", "a lot of notes (890+)", "very fast (over 210 BPM)",
            "long streams", "trills", "jacks",
            "trills on the spot", "trills across the screen",
            "trills against a held button", "a bouncing rhythm",
        ),
    },
    "touch": {
        "label": "touch",
        "note": "the pads, on their own and mixed into everything else",
        "members": (
            "タッチ複合", "タッチ乱打", "タッチ流し", "タッチ回転", "タッチ巻き込み",
            "multi-touch", "touch-heavy", "touch sweeps",
            "touch clusters",
        ),
    },
    "reading": {
        "label": "reading",
        "note": "knowing when to hit, when the chart will not tell you plainly",
        "members": (
            "リズム難", "ハネリズム", "ソフラン", "ホールド難",
            "tempo changes", "slow songs (under 130 BPM)", "light charts (under 620 notes)",
        ),
    },
}

ORDER = tuple(FAMILIES)

# A family needs this many charts behind it before it is drawn. The count adds up its traits, and a
# chart carrying two of them is counted twice, so the bar sits well above the twelve a single trait
# needs: below this a family is one thin tag wearing a family's name, which is the problem it exists
# to solve. On the six players measured it drops one family, of two tags over twenty-three charts.
FAMILY_MIN_CHARTS = 30

# and this many traits. A family averaging one trait is that trait wearing a family's name, drawn on
# the wheel the same size as a family averaging thirteen: on one player it put rotation furthest out
# of all six, off a single trait the model would not even call a lean.
FAMILY_MIN_TRAITS = 2


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
        if trait.get("dimension") in NOT_A_SKILL or trait.get("dimension") == "judgement":
            continue
        key = _member_of(trait)
        if key:
            held[key].append(trait)
    out: List[Dict[str, Any]] = []
    for key in ORDER:
        traits = held[key]
        charts = sum(int(t.get("count") or 0) for t in traits)
        if len(traits) < FAMILY_MIN_TRAITS or charts < FAMILY_MIN_CHARTS:
            continue
        offset = sum(float(t["offset"]) * int(t.get("count") or 0) for t in traits) / charts
        inside = sorted(traits, key=lambda t: float(t["offset"]))
        out.append({
            "key": key, "label": FAMILIES[key]["label"], "note": FAMILIES[key]["note"],
            # charts is the sum over its traits, so a chart carrying two of them counts twice: it is
            # the weight behind the family rather than a tally of distinct charts
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
                   if t.get("dimension") not in NOT_A_SKILL and t.get("dimension") != "judgement"
                   and not _member_of(t)
                   and _is_technique(str(t.get("dimension") or ""), str(t.get("label") or ""))})
