from typing import Any, Dict, List, Tuple

from rasmai.engine.analysis import ChartRef


def chart_traits(chart: ChartRef) -> List[Tuple[str, str]]:
    """The attributes a chart is judged on: tempo, note count, era, genre, designer, chart type.

    When mai-notes has been read, the chart's note mix (break-heavy, slide-heavy) and the pattern
    tags its editors gave it (streams, hard slides) join the list, so a weakness can be named as a
    pattern rather than only as a property of the song.

    :param chart: The chart being judged.
    :type chart: ChartRef
    :rtype: List[Tuple[str, str]]
    """
    traits: List[Tuple[str, str]] = [("type", "DX charts" if chart.chart_type == "dx" else "standard charts")]
    try:
        from rasmai.scraping import mai_notes
        row = mai_notes.cached_facts().get(chart.key)
    except Exception:                     # the model must never fail because a fan site is unreadable
        row = None
    if row:
        traits.extend(mai_notes.note_traits(row))
        traits.extend(mai_notes.pattern_traits(row))
    # only the tails of tempo and density are named. A band holding a third of the game sits on the
    # player's own average by construction, so it can never say anything, and it takes a place on the
    # wheel that a trait with something to say would have had. These are the deciles and the quartiles
    # of every chart at level 12 and above.
    if chart.bpm > 0:
        if chart.bpm <= 130:
            traits.append(("tempo", "slow songs (under 130 BPM)"))
        elif chart.bpm >= 210:
            traits.append(("tempo", "very fast songs (over 210 BPM)"))
    if chart.notes > 0:
        if chart.notes < 620:
            traits.append(("density", "light charts (under 620 notes)"))
        elif chart.notes >= 890:
            traits.append(("density", "dense charts (890+ notes)"))
    if chart.version:
        era = "maimai-era songs (before DX)" if chart.version < 20 else "DX to FESTiVAL songs" if chart.version < 24 else "BUDDiES and newer songs"
        traits.append(("era", era))
    if chart.genre:
        traits.append(("genre", chart.genre))
    if chart.designer:
        traits.append(("designer", f"charts by {chart.designer}"))
    return traits


# a chart page prints these in its own header, so the tag row does not repeat them
NOT_A_DEMAND = {"type", "era", "genre", "designer"}


def chart_tags(chart: ChartRef) -> List[Dict[str, Any]]:
    """What a chart asks of you, for showing on its page: the community's pattern tags first, then what its own numbers say.

    mai-notes' editors have tagged a third of the Master charts and half the Re:MASTERs, and
    almost nothing below Expert, so a page that shows only those is blank for most charts. The
    note mix, tempo band and note density are measured from the chart itself and cover nearly all
    of them, so they fill the row out. They are marked as measured rather than community-written, because the two are not the
    same kind of claim.

    :param chart: The chart being shown.
    :type chart: ChartRef
    :rtype: List[Dict[str, Any]]
    """
    tags = [{"dimension": dimension, "label": label, "community": dimension == "pattern"}
            for dimension, label in chart_traits(chart) if dimension not in NOT_A_DEMAND]
    tags.sort(key=lambda tag: not tag["community"])     # the editors' words lead, the measured ones follow
    return tags


NON_TECHNIQUE = {"notorious", "good to practice on", "a maimai standard", "one hard section", "hard throughout", "hard to score"}


# what a chart is rather than what it asks of the hands. These are still measured, because a
# charter's habits and an era's style soak up differences that would otherwise be blamed on a
# pattern, but a trait is only worth telling a player about if it is a skill they can work on,
# so none of them are ever named on the wheel or in the lists.
NOT_A_SKILL = {"type", "era", "genre", "designer"}


def _is_technique(dimension: str, label: str) -> bool:
    """Whether a tag says something about play rather than about fame or difficulty shape."""
    if dimension != "pattern":
        return True
    try:
        from rasmai.scraping.mai_notes import english_label
        gloss = english_label(label)
    except Exception:
        gloss = label
    return gloss not in NON_TECHNIQUE and label not in NON_TECHNIQUE
