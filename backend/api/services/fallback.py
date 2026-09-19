"""Deterministic planner used when the AI provider is unavailable.

It produces exactly the same JSON shape as the model, so the frontend never
needs to know which one answered. The response is tagged `engine: "heuristic"`
and the UI shows a small badge — better an honest degraded answer than a spinner
that never resolves during a demo.
"""

from __future__ import annotations

from .matching import StudentProfile


def _eur(value) -> str:
    return f"€{int(value):,}" if value else "not in database"


def _pick_rows(rows: list[dict]) -> list[tuple[str, dict]]:
    """Pick one reach, two realistic and one comfortable option.

    The bands are assigned by position within this shortlist rather than against
    fixed probability thresholds. Absolute thresholds break in both directions:
    a student with a modest profile ends up with four reaches, and a very strong
    one is told four safe schools are "dreams". Relative banding always produces
    a spread the student can act on.
    """
    pool = sorted(rows, key=lambda r: r["fit_score"], reverse=True)[:12]
    if len(pool) < 4:
        pool = sorted(rows, key=lambda r: r["fit_score"], reverse=True)

    by_odds = sorted(pool, key=lambda r: r["admission_chance"])
    chosen: list[tuple[str, dict]] = []
    used: set[int] = set()

    def take(candidates: list[dict], band: str) -> None:
        for row in candidates:
            if row["university"].id not in used:
                chosen.append((band, row))
                used.add(row["university"].id)
                return

    # Hardest realistic option first, then the most comfortable, then fill the
    # middle with the two best-fitting of what's left.
    take(by_odds, "dream")
    take(list(reversed(by_odds)), "safe")
    middle = sorted(
        (r for r in pool if r["university"].id not in used),
        key=lambda r: r["fit_score"],
        reverse=True,
    )
    take(middle, "target")
    take(middle, "target")

    order = {"dream": 0, "target": 1, "safe": 2}
    chosen.sort(key=lambda pair: order[pair[0]])
    return chosen


def build_plan(profile: StudentProfile, rows: list[dict]) -> tuple[dict, dict]:
    chosen = _pick_rows(rows)
    picks = []
    for category, row in chosen:
        uni = row["university"]
        money, req = row["budget"], row["requirements"]

        why = []
        if row["matched_programmes"]:
            why.append(f"Runs {row['matched_programmes'][0]}, which lines up with what you wrote.")
        if money["verdict"] in {"comfortable", "within budget"}:
            why.append(f"Total yearly cost of {_eur(money['total_eur'])} fits inside your budget.")
        if uni.ranking_world:
            why.append(f"Ranked #{uni.ranking_world} worldwide.")
        if uni.language_of_instruction:
            why.append(f"Taught in {uni.language_of_instruction}.")

        risks = []
        for key, gap in req["gaps"].items():
            if not gap.get("meets") and not gap.get("optional"):
                risks.append(
                    f"Your {key.upper()} of {gap['yours']} is below the {gap['required']} minimum."
                )
        if money["gap_eur"] < 0:
            risks.append(f"Costs run {_eur(abs(money['gap_eur']))} over your yearly budget.")
        if not risks:
            risks.append("No blocking issues found in the database figures.")

        picks.append(
            {
                "id": uni.id,
                "category": category,
                "fit_score": row["fit_score"],
                "admission_chance": row["admission_chance"],
                "headline": f"{uni.name} — {category} school in {uni.city or uni.country}.",
                "why": why[:4],
                "risks": risks[:3],
                "requirement_verdict": _requirement_sentence(req),
                "money_verdict": (
                    f"{_eur(money['total_eur'])} per year against your budget — "
                    f"{'a ' + _eur(abs(money['gap_eur'])) + ' shortfall' if money['gap_eur'] < 0 else _eur(money['gap_eur']) + ' to spare'}."
                    if profile.budget_eur
                    else f"{_eur(money['total_eur'])} per year. Add a budget to see the gap."
                ),
                "scholarship_tip": (uni.scholarship_notes or "")[:220],
                "programme": (row["matched_programmes"] or (uni.majors or ["General programmes"]))[0],
            }
        )

    plan = {
        "summary": _summary(profile, chosen),
        "picks": picks,
        "comparison": _comparison(profile, chosen),
        "timeline": _timeline(profile),
        "advice": _advice(profile, chosen),
    }
    meta = {
        "engine": "heuristic",
        "model": "",
        "provider": "local",
        "latency_ms": 0,
        "candidates_considered": len(rows),
        "note": "Built from the app's own scoring because the AI provider was unavailable.",
    }
    return plan, meta


def _requirement_sentence(req: dict) -> str:
    parts = []
    for key, gap in req["gaps"].items():
        verb = "meets" if gap.get("meets") else "falls short of"
        parts.append(f"your {key.upper()} {gap['yours']} {verb} the {gap['required']} bar")
    return ("On paper, " + "; ".join(parts) + ".") if parts else "This school publishes no fixed cut-offs."


def _summary(profile: StudentProfile, chosen: list) -> str:
    affordable = sum(1 for _, row in chosen if row["budget"]["gap_eur"] >= 0)
    cheapest = min(chosen, key=lambda pair: pair[1]["budget"]["total_eur"] or 10**9)
    return (
        f"Based on {profile.summary_line() or 'the scores you entered'}, four schools came out of "
        f"the database. {affordable} of the four sit inside your budget, and the cheapest option is "
        f"{cheapest[1]['university'].name} at {_eur(cheapest[1]['budget']['total_eur'])} a year all in. "
        "The AI model was unreachable, so this list comes from the app's own scoring — the numbers are "
        "straight from the database, but the commentary is templated."
    )


def _comparison(profile: StudentProfile, chosen: list) -> dict:
    unis = [row["university"] for _, row in chosen]
    rows_data = [row for _, row in chosen]

    def col(fn):
        return [fn(u, r) for u, r in zip(unis, rows_data)]

    return {
        "columns": ["Metric"] + [u.name for u in unis],
        "rows": [
            {"metric": "City", "values": col(lambda u, r: f"{u.city}, {u.country}")},
            {"metric": "Tuition / year", "values": col(lambda u, r: _eur(u.tuition_eur))},
            {"metric": "Living costs / year", "values": col(lambda u, r: _eur(r["budget"]["living_eur"]))},
            {"metric": "Total / year", "values": col(lambda u, r: _eur(r["budget"]["total_eur"]))},
            {
                "metric": "vs your budget",
                "values": col(
                    lambda u, r: ("+" if r["budget"]["gap_eur"] >= 0 else "−")
                    + _eur(abs(r["budget"]["gap_eur"]))
                    if profile.budget_eur
                    else "—"
                ),
            },
            {"metric": "IELTS required", "values": col(lambda u, r: u.min_ielts or "not stated")},
            {
                "metric": "SAT",
                "values": col(
                    lambda u, r: f"{u.min_sat} required" if (u.sat_required and u.min_sat)
                    else (f"{u.min_sat} optional" if u.min_sat else "not used")
                ),
            },
            {"metric": "GPA (4.0)", "values": col(lambda u, r: u.min_gpa or "not stated")},
            {
                "metric": "Acceptance rate",
                "values": col(lambda u, r: f"{u.acceptance_rate:.0%}" if u.acceptance_rate else "not published"),
            },
            {"metric": "Language", "values": col(lambda u, r: u.language_of_instruction or "—")},
            {"metric": "Deadline", "values": col(lambda u, r: u.application_deadline or "check site")},
        ],
    }


def _timeline(profile: StudentProfile) -> list[dict]:
    deadline = profile.deadline or "your deadline"
    return [
        {"when": "This week", "task": "Lock the shortlist",
         "detail": "Open each university's admissions page and confirm the figures below still match."},
        {"when": "Weeks 2–3", "task": "Request transcripts and references",
         "detail": "Most European applications need a certified transcript, which schools are slow to issue."},
        {"when": "Weeks 3–5", "task": "Write one motivation letter, then adapt it",
         "detail": "Keep a common core and swap the final paragraph per school."},
        {"when": "6 weeks before " + deadline, "task": "Submit the safe school first",
         "detail": "Getting one acceptance in hand early takes the pressure off the rest."},
        {"when": "2 weeks before " + deadline, "task": "Submit the dream and target applications",
         "detail": "Leave room for portal outages and payment delays on application fees."},
    ]


def _advice(profile: StudentProfile, chosen: list) -> dict:
    ielts = profile.ielts
    sat = profile.sat
    cheapest = min(chosen, key=lambda pair: pair[1]["budget"]["total_eur"] or 10**9)
    return {
        "ielts": (
            f"A {ielts:g} clears most English-taught bachelor programmes in Europe."
            if ielts and ielts >= 6.5
            else "Several English-taught programmes sit at 6.5 — half a band would widen this list noticeably."
            if ielts
            else "Add an IELTS band to filter out programmes you can't yet apply to."
        ),
        "sat": (
            f"Your {sat} is optional at most of these schools; it mainly helps at the private and "
            "international-track ones."
            if sat
            else "Most European universities don't ask for the SAT, so its absence isn't a problem here."
        ),
        "gpa": (
            f"A {profile.gpa:.2f}/4.0 is the number these offices will convert into their own scale."
            if profile.gpa
            else "Add your GPA to get a sharper read on selectivity."
        ),
        "budget": f"{cheapest[1]['university'].name} is the cheapest of the four at {_eur(cheapest[1]['budget']['total_eur'])} a year.",
        "next_step": "Check the deadline on each university's own site before you plan around it.",
    }
