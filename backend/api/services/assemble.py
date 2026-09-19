"""Stitches the model's plan together with the database records.

The model returns judgement (which schools, why, what's risky). Everything
factual — prices, coordinates, photos, deadlines — is re-attached here straight
from the database, so no figure shown to a student ever passes through the model
unchecked.
"""

from __future__ import annotations

from api.models import University

from .images import campus_map
from .matching import StudentProfile

CATEGORY_RANK = {"dream": 0, "target": 1, "safe": 2}


def serialise_university(uni: University) -> dict:
    return {
        "id": uni.id,
        "slug": uni.slug,
        "name": uni.name,
        "city": uni.city,
        "country": uni.country,
        "website": uni.website,
        "description": uni.description,
        "ranking_world": uni.ranking_world,
        "ranking_national": uni.ranking_national,
        "acceptance_rate": uni.acceptance_rate,
        "tuition_eur": uni.tuition_eur or None,
        "tuition_min_eur": uni.tuition_min_eur,
        "tuition_max_eur": uni.tuition_max_eur,
        "living_cost_eur": uni.living_cost_eur,
        "housing_cost_eur": uni.housing_cost_eur,
        "application_fee_eur": uni.application_fee_eur,
        "total_cost_eur": uni.annual_cost_eur or None,
        "min_ielts": uni.min_ielts,
        "min_sat": uni.min_sat,
        "sat_required": uni.sat_required,
        "min_gpa": uni.min_gpa,
        "language_of_instruction": uni.language_of_instruction,
        "majors": uni.majors or [],
        "application_deadline": uni.application_deadline,
        "scholarship_notes": uni.scholarship_notes,
        "has_housing": uni.has_housing,
        "images": {
            "front": uni.image_front,
            "inside": uni.image_inside,
            "housing": uni.image_housing,
            "credits": uni.image_credits or {},
        },
        "map": campus_map(uni),
    }


def assemble(profile: StudentProfile, plan: dict, rows: list[dict], meta: dict) -> dict:
    by_id = {row["university"].id: row for row in rows}

    picks: list[dict] = []
    for pick in plan["picks"]:
        row = by_id.get(pick["id"])
        if row is None:
            continue
        uni = row["university"]
        picks.append(
            {
                "category": pick["category"],
                "fit_score": pick["fit_score"],
                "admission_chance": pick["admission_chance"],
                "headline": pick.get("headline", ""),
                "why": pick.get("why", []),
                "risks": pick.get("risks", []),
                "requirement_verdict": pick.get("requirement_verdict", ""),
                "money_verdict": pick.get("money_verdict", ""),
                "scholarship_tip": pick.get("scholarship_tip", ""),
                "programme": pick.get("programme", ""),
                "university": serialise_university(uni),
                # The app's own maths, kept alongside the model's view so the UI
                # can show both and the student can see where they disagree.
                "computed": {
                    "fit_score": row["fit_score"],
                    "admission_chance": row["admission_chance"],
                    "band": row["category"],
                    "budget": row["budget"],
                    "requirements": row["requirements"]["gaps"],
                    "unmet": row["requirements"]["unmet"],
                    "matched_programmes": row["matched_programmes"],
                },
            }
        )

    # Stable sort on category only. The comparison table's columns are built in
    # the order the picks were produced, so adding a secondary sort key here
    # would silently misalign every column header with its data.
    picks.sort(key=lambda p: CATEGORY_RANK.get(p["category"], 9))

    return {
        "engine": meta.get("engine", "ai"),
        "meta": meta,
        "student": {
            **profile.as_dict(),
            "summary_line": profile.summary_line(),
        },
        "summary": plan.get("summary", ""),
        "picks": picks,
        "comparison": plan.get("comparison") or {"columns": [], "rows": []},
        "timeline": plan.get("timeline", []),
        "advice": plan.get("advice", {}),
        "charts": build_charts(profile, picks),
        "shortlist_size": len(rows),
        "budget_warning": budget_warning(profile, picks),
    }


def budget_warning(profile: StudentProfile, picks: list[dict]) -> str:
    """If nothing on the list is affordable, say so at the top rather than
    leaving the student to work it out from four separate cost lines."""
    if not profile.budget_eur or not picks:
        return ""
    gaps = [p["computed"]["budget"]["gap_eur"] for p in picks]
    if all(gap < 0 for gap in gaps):
        smallest = min(abs(gap) for gap in gaps)
        return (
            f"None of these fit a €{profile.budget_eur:,} budget. The closest is "
            f"€{smallest:,} a year short, so this list only works with a scholarship, "
            "a student job, or a country with lower living costs."
        )
    if sum(1 for gap in gaps if gap >= 0) == 1:
        return (
            "Only one of these four sits inside your budget. Treat the others as "
            "conditional on funding."
        )
    return ""


# ---------------------------------------------------------------------------
# Chart datasets — shaped so the frontend can draw SVG without post-processing
# ---------------------------------------------------------------------------
def build_charts(profile: StudentProfile, picks: list[dict]) -> dict:
    labels = [p["university"]["name"] for p in picks]
    short_labels = [_short(p["university"]["name"], p["university"]["city"]) for p in picks]
    categories = [p["category"] for p in picks]

    cost = {
        "labels": short_labels,
        "full_labels": labels,
        "categories": categories,
        "series": [
            {"key": "tuition", "label": "Tuition", "values": [p["computed"]["budget"]["tuition_eur"] for p in picks]},
            {"key": "living", "label": "Living + housing", "values": [p["computed"]["budget"]["living_eur"] for p in picks]},
        ],
        "budget": profile.budget_eur,
    }

    admission = {
        "labels": short_labels,
        "categories": categories,
        "ai": [round(p["admission_chance"] * 100) for p in picks],
        "computed": [round(p["computed"]["admission_chance"] * 100) for p in picks],
    }

    radar = {
        "axes": ["English", "Test scores", "Grades", "Affordability", "Subject match"],
        "series": [
            {
                "label": _short(p["university"]["name"], p["university"]["city"]),
                "category": p["category"],
                "values": _radar_values(profile, p),
            }
            for p in picks
        ],
    }

    gaps = {
        "labels": short_labels,
        "categories": categories,
        "values": [p["computed"]["budget"]["gap_eur"] for p in picks],
        "budget": profile.budget_eur,
    }

    scatter = {
        "points": [
            {
                "label": _short(p["university"]["name"], p["university"]["city"]),
                "category": p["category"],
                "x": p["computed"]["budget"]["total_eur"],
                "y": round(p["admission_chance"] * 100),
                "rank": p["university"]["ranking_world"],
            }
            for p in picks
        ],
        "budget": profile.budget_eur,
    }

    return {"cost": cost, "admission": admission, "radar": radar, "gaps": gaps, "scatter": scatter}


def _radar_values(profile: StudentProfile, pick: dict) -> list[int]:
    """Each axis: 100 means the student is comfortably clear of that school's bar."""
    req = pick["computed"]["requirements"]
    uni = pick["university"]

    def axis(key: str, span: float) -> int:
        gap = req.get(key)
        if not gap:
            return 60
        delta = float(gap["delta"]) / span
        return int(max(5, min(100, 62 + delta * 55)))

    afford = pick["computed"]["budget"]
    if profile.budget_eur and afford["total_eur"]:
        ratio = profile.budget_eur / max(afford["total_eur"], 1)
        afford_score = int(max(5, min(100, ratio * 62)))
    else:
        afford_score = 55

    subject = int(min(100, max(10, pick["computed"].get("matched_programmes") and 85 or 45)))

    return [
        axis("ielts", 1.5),
        axis("sat", 250) if uni["min_sat"] else 60,
        axis("gpa", 0.8),
        afford_score,
        subject,
    ]


SMALL_WORDS = {"of", "and", "the", "in", "for", "de", "di", "der", "van"}


def _short(name: str, city: str = "", limit: int = 20) -> str:
    """Shorten an official name to something that fits a chart axis and is still
    recognisable — "Technical University of Munich" should read "TU Munich",
    not "Technical Munich".
    """
    import re

    clean = re.sub(r"\s*\([^)]*\)", "", name).strip()
    if len(clean) <= limit:
        return clean

    # "<qualifier> University of <place>" → initials + place, which is usually
    # how the school is actually referred to (TU Munich, LMU Munich, CTU Prague).
    match = re.search(r"^(.*?)\b(?:University|Universit\w+|Institute)\b\s+(?:of|in)\s+(.+)$", clean, re.I)
    if match:
        head, tail = match.group(1).strip(), match.group(2).strip()
        if len(tail) <= 14:
            initials = "".join(w[0] for w in head.split() if w.lower() not in SMALL_WORDS).upper()
            candidate = f"{initials}U {tail}" if initials else tail
            if len(candidate) <= limit:
                return candidate

    if city and len(city) <= limit:
        return city
    return clean[: limit - 1].rstrip() + "…"
