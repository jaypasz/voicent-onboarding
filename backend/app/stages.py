"""Stages: an onboarding's sections, in the document's order, each holding its steps.

A stage that needs a sign-off (the section's `signoff`, on unless set to false) holds back every stage after it until someone on
our team signs it off. Signing off is only possible once every step in the stage is done or skipped. A step in a held-back stage
is locked for the client: they can see it, but not answer it, and nobody reminds them about it. Our own team can still work ahead.
Steps outside any section belong to no stage and are never held back. An onboarding finishes only when every stage that needs a
sign-off has one.

States: locked (an earlier stage isn't signed off) | open (steps left) | ready (all steps finished, waiting for the sign-off) |
signed_off | done (all steps finished, no sign-off needed).
"""
from __future__ import annotations

from dataclasses import dataclass

from . import models as m

FINISHED = ("done", "skipped")


def needs_signoff(section: dict) -> bool:
    return section.get("signoff", True) is not False


@dataclass
class Stage:
    key: str
    title: str
    signoff: bool
    steps: list[m.Step]
    state: str
    signed: m.StageSignoff | None


def stages(ob: m.Onboarding) -> list[Stage]:
    """The stages that hold at least one step, in order, with their state."""
    signed = {s.section_key: s for s in ob.signoffs}
    out: list[Stage] = []
    held = False
    for sec in ob.document.get("sections", []):
        steps = [s for s in ob.steps if s.section == sec["key"]]
        if not steps:
            continue
        signoff = needs_signoff(sec)
        row = signed.get(sec["key"]) if signoff else None
        finished = all(s.status in FINISHED for s in steps)
        if held:
            state = "locked"
        elif row is not None:
            state = "signed_off"
        elif finished:
            state = "ready" if signoff else "done"
        else:
            state = "open"
        out.append(Stage(sec["key"], sec["title"], signoff, steps, state, row))
        if signoff and row is None:
            held = True
    return out


def locked_keys(ob: m.Onboarding) -> set[str]:
    """Keys of the steps the client can't work on yet."""
    return {s.key for st in stages(ob) if st.state == "locked" for s in st.steps}


def all_signed_off(ob: m.Onboarding) -> bool:
    return all(st.state in ("signed_off", "done") or not st.signoff for st in stages(ob))


def find(ob: m.Onboarding, key: str) -> Stage | None:
    return next((st for st in stages(ob) if st.key == key), None)


def ordered_steps(ob: m.Onboarding, steps: list[m.Step]) -> list[m.Step]:
    """Steps in stage order, then their own order; steps outside a stage come last. A template that lists steps out of their
    stages' order still reads (and is worked through) one stage at a time."""
    rank = {sec["key"]: i for i, sec in enumerate(ob.document.get("sections", []))}
    return sorted(steps, key=lambda s: (rank.get(s.section, len(rank)), s.position))
