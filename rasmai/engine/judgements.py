from typing import Any, Dict, List, Optional

from rasmai.engine.losses import WEIGHTS, note_losses

KINDS = tuple(WEIGHTS)
MIN_PLAYS = 3            # one play says little; three is enough to name the note type that costs most
TILT = 1.5               # a type carrying this many times its share of the loss is called out


def judgement_profile(rows: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Loss and timing across every stored play, per note type; None until there are a few plays.

    :param rows: The stored judgement pages.
    :type rows: List[Dict[str, Any]]
    :rtype: Optional[Dict[str, Any]]
    """
    if len(rows) < MIN_PLAYS:
        return None
    notes = {k: 0 for k in KINDS}
    clean = {k: 0 for k in KINDS}
    lost = {k: 0.0 for k in KINDS}
    stake = {k: 0.0 for k in KINDS}
    bonus = 0.0
    fast = late = 0
    for row in rows:
        counts = row.get("notes") or {}
        weighted = sum(WEIGHTS[k] * sum(int(v) for v in (counts.get(k) or {}).values()) for k in KINDS)
        for kind, judged in counts.items():
            if kind in notes:
                held = sum(int(v) for v in judged.values())
                notes[kind] += held
                clean[kind] += int(judged.get("critical", 0)) + int(judged.get("perfect", 0))
                if weighted > 0:
                    stake[kind] += 100.0 * WEIGHTS[kind] * held / weighted
        for kind, value in note_losses(counts, float(row.get("achievement") or 0), bonus_apart=True).items():
            if kind in lost:
                lost[kind] += value
            else:
                bonus += value
        fast += int(row.get("fast") or 0)
        late += int(row.get("late") or 0)
    all_notes = sum(notes.values())
    all_lost = sum(lost.values()) + bonus
    all_stake = sum(stake.values())
    if not all_notes:
        return None
    types = []
    for kind in KINDS:
        if not notes[kind]:
            continue
        share = notes[kind] / all_notes
        loss_share = lost[kind] / all_lost if all_lost else 0.0
        # a break is worth five taps, so measure a type against what it was worth, not against how
        # many of them there were: by note count every player alive is weak at breaks
        at_stake = stake[kind] / all_stake if all_stake else 0.0
        types.append({
            "kind": kind, "notes": notes[kind], "share": round(share, 4), "lossShare": round(loss_share, 4),
            "stakeShare": round(at_stake, 4),
            "per100": round(100 * lost[kind] / notes[kind], 3),           # points lost per hundred notes of this type
            "clean": round(clean[kind] / notes[kind], 4),                  # critical or perfect
            "tilt": round(loss_share / at_stake, 2) if at_stake else 0.0,  # 1.0 = costs what it was worth
        })
    weak = max((t for t in types if t["tilt"] >= TILT and t["lossShare"] >= 0.15), key=lambda t: t["tilt"], default=None)
    hits = fast + late
    return {
        "plays": len(rows), "types": types, "weak": weak["kind"] if weak else None,
        "fast": fast, "late": late, "lateShare": round(late / hits, 3) if hits else None,
        "lostPerPlay": round(all_lost / len(rows), 3),
        # the slice of the 1% only a critical earns. Everyone who is not hunting criticals loses it,
        # so it is reported on its own rather than counted against the breaks it rode on.
        "bonus": round(bonus, 3), "bonusPerPlay": round(bonus / len(rows), 3),
        "bonusShare": round(bonus / all_lost, 4) if all_lost else 0.0,
    }


JUDGEMENT_LEAN_PLAYS = 10     # plays before a note type is worth mentioning as a lean
JUDGEMENT_CONFIRM_PLAYS = 25  # plays before it is stated as measured
JUDGEMENT_MIN_NOTES = 200     # notes of that type before its rate means anything
JUDGEMENT_OFFSET = 0.5        # points a play a type has to cost beyond the player's own rate to be stated
JUDGEMENT_LEAN_OFFSET = 0.3   # and this much to be worth showing as a lean


def judgement_traits(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Each note type as a trait: the points per play it costs against the player's own average rate.

    A note is not worth the same as its neighbours, so comparing a type's share of the loss with its
    share of the notes would call every player weak at breaks. This compares what a type cost with
    what was at stake on it, against the rate the player loses at overall, which makes the offsets
    sum to zero the way the chart traits do: a negative one is where the points actually go.

    The 1% bonus is left out of this. Only a critical perfect earns a break its whole slice, so a
    player who is not hunting criticals drops it on a run with nothing else wrong, and counting it
    here made breaks the weakness of every player measured. It is reported on its own instead.

    :param rows: The stored judgement pages.
    :type rows: List[Dict[str, Any]]
    :returns: Trait rows shaped like the chart ones, so both lists read the same.
    :rtype: List[Dict[str, Any]]
    """
    if len(rows) < JUDGEMENT_LEAN_PLAYS:
        return []
    notes = {k: 0 for k in KINDS}
    stake = {k: 0.0 for k in KINDS}      # achievement the type was worth, so the rates are comparable
    lost = {k: 0.0 for k in KINDS}
    plays = 0
    for row in rows:
        counts = row.get("notes") or {}
        weighted = sum(WEIGHTS[k] * sum(int(v) for v in (counts.get(k) or {}).values()) for k in KINDS)
        if weighted <= 0:
            continue
        plays += 1
        for kind in KINDS:
            held = sum(int(v) for v in (counts.get(kind) or {}).values())
            notes[kind] += held
            stake[kind] += 100.0 * WEIGHTS[kind] * held / weighted
        for kind, value in note_losses(counts, float(row.get("achievement") or 0), bonus_apart=True).items():
            if kind in lost:
                lost[kind] += value
    total_stake = sum(stake.values())
    if not plays or total_stake <= 0:
        return []
    overall = sum(lost.values()) / total_stake
    out: List[Dict[str, Any]] = []
    for kind in KINDS:
        if notes[kind] < JUDGEMENT_MIN_NOTES or stake[kind] <= 0:
            continue
        # what the type costs per play beyond the player's own rate; negative is where points go
        offset = round(-(lost[kind] / stake[kind] - overall) * stake[kind] / plays, 2)
        out.append({
            "dimension": "judgement", "label": f"{kind} notes", "offset": offset, "count": plays, "plays": plays,
            "notes": notes[kind], "perPlay": round(lost[kind] / plays, 3), "p": 0.0,
            "verified": bool(plays >= JUDGEMENT_CONFIRM_PLAYS and abs(offset) >= JUDGEMENT_OFFSET),
            # anything short of stating it outright but still off the player's own rate is a lean,
            # whether it fell short on plays or on size; more plays must never hide a real gap
            "leaning": bool(abs(offset) >= JUDGEMENT_LEAN_OFFSET) and not (
                plays >= JUDGEMENT_CONFIRM_PLAYS and abs(offset) >= JUDGEMENT_OFFSET),
        })
    out.sort(key=lambda trait: trait["offset"])
    return out
