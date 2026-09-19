"""Turns a student profile into a ranked shortlist of universities.

This runs before the AI. Its job is to do the boring, deterministic work —
budget maths, requirement gaps, subject matching — so the model receives a small,
clean candidate list and can spend its attention on judgement instead of
arithmetic. It's also the fallback: if the AI is unreachable, the ranking here is
good enough to still produce a sensible plan.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field, asdict

from api.models import University

STOPWORDS = {
    "and", "or", "of", "the", "in", "for", "with", "a", "an", "to", "science",
    "sciences", "studies", "study", "degree", "bachelor", "master", "program",
    "programme", "major", "i", "want", "would", "like", "am", "interested",
}

# Subject vocabulary: maps the words a 17-year-old actually types onto the
# words universities print in their programme catalogues.
SUBJECT_SYNONYMS = {
    "cs": ["computer", "computing", "informatics", "software"],
    "coding": ["computer", "software", "informatics"],
    "programming": ["computer", "software", "informatics"],
    "ai": ["artificial", "intelligence", "machine", "learning", "data", "computer"],
    "ml": ["machine", "learning", "data", "artificial", "intelligence"],
    "it": ["information", "technology", "computer", "informatics"],
    "econ": ["economics", "economic"],
    "business": ["management", "business", "administration", "commerce"],
    "biz": ["business", "management"],
    "med": ["medicine", "medical", "health"],
    "medicine": ["medical", "health", "biomedical"],
    "bio": ["biology", "biological", "biomedical", "life"],
    "psych": ["psychology", "psychological", "cognitive"],
    "law": ["law", "legal", "jurisprudence"],
    "eng": ["engineering", "engineer"],
    "mech": ["mechanical", "engineering"],
    "ee": ["electrical", "electronic", "engineering"],
    "civil": ["civil", "engineering", "architecture"],
    "arch": ["architecture", "architectural", "design"],
    "ir": ["international", "relations", "politics", "political"],
    "poli": ["political", "politics", "government"],
    "finance": ["finance", "financial", "economics", "accounting"],
    "data": ["data", "statistics", "analytics", "computer"],
    "design": ["design", "arts", "creative", "media"],
    "math": ["mathematics", "mathematical", "applied"],
    "maths": ["mathematics", "mathematical"],
    "physics": ["physics", "physical"],
    "chem": ["chemistry", "chemical"],
    "env": ["environmental", "sustainability", "climate", "earth"],
    "aero": ["aerospace", "aeronautical", "aviation"],
    "robotics": ["robotics", "mechatronics", "automation", "mechanical"],
}

COUNTRY_ALIASES = {
    "holland": "netherlands",
    "nl": "netherlands",
    "the netherlands": "netherlands",
    "deutschland": "germany",
    "de": "germany",
    "uk": "united kingdom",
    "england": "united kingdom",
    "britain": "united kingdom",
    "great britain": "united kingdom",
    "scotland": "united kingdom",
    "czechia": "czech republic",
    "cz": "czech republic",
    "espana": "spain",
    "es": "spain",
    "italia": "italy",
    "it": "italy",
    "fr": "france",
    "ie": "ireland",
    "eire": "ireland",
    "pl": "poland",
    "polska": "poland",
    "suomi": "finland",
    "sverige": "sweden",
    "danmark": "denmark",
    "norge": "norway",
    "osterreich": "austria",
    "schweiz": "switzerland",
    "swiss": "switzerland",
    "belgie": "belgium",
    "portugal ": "portugal",
    "magyarorszag": "hungary",
    "hellas": "greece",
    "any": "",
    "anywhere": "",
    "no preference": "",
    "europe": "",
}


# ---------------------------------------------------------------------------
# Profile normalisation
# ---------------------------------------------------------------------------
@dataclass
class StudentProfile:
    ielts: float | None = None
    sat: int | None = None
    gpa: float | None = None          # always normalised to /4.0
    gpa_raw: float | None = None
    gpa_scale: str = "4.0"
    budget_eur: int | None = None
    countries: list[str] = field(default_factory=list)
    major: str = ""
    deadline: str = ""
    notes: str = ""

    def as_dict(self) -> dict:
        return asdict(self)

    def summary_line(self) -> str:
        bits = []
        if self.ielts is not None:
            bits.append(f"IELTS {self.ielts:g}")
        if self.sat:
            bits.append(f"SAT {self.sat}")
        if self.gpa is not None:
            bits.append(f"GPA {self.gpa:.2f}/4.0")
        if self.budget_eur:
            bits.append(f"budget €{self.budget_eur:,}/year")
        if self.major:
            bits.append(self.major)
        return " · ".join(bits)


def normalise_gpa(value: float | None, scale: str = "auto") -> tuple[float | None, str]:
    """Accept 4.0, 5.0, 10, 20 or 100-point GPAs and return a /4.0 value.

    Students type whatever their school uses. Guessing wrong would quietly
    mis-rank every university, so the guess is explicit and returned alongside
    the number for display.
    """
    if value is None:
        return None, scale
    v = float(value)
    if scale and scale not in {"auto", ""}:
        try:
            top = float(scale)
        except ValueError:
            top = 4.0
    elif v <= 4.0:
        top = 4.0
    elif v <= 5.0:
        top = 5.0
    elif v <= 10.0:
        top = 10.0
    elif v <= 20.0:
        top = 20.0
    else:
        top = 100.0
    top = max(top, 0.001)
    return round(min(v / top, 1.0) * 4.0, 2), f"{top:g}"


def normalise_country(value: str) -> str:
    key = re.sub(r"[^a-z ]", "", (value or "").strip().lower())
    key = COUNTRY_ALIASES.get(key, key)
    return key


def build_profile(data: dict) -> StudentProfile:
    gpa_norm, detected_scale = normalise_gpa(data.get("gpa"), data.get("gpa_scale", "auto"))
    countries_raw = data.get("countries") or []
    if isinstance(countries_raw, str):
        countries_raw = [c for c in re.split(r"[,;/]", countries_raw)]
    countries = [c for c in (normalise_country(c) for c in countries_raw) if c]
    return StudentProfile(
        ielts=float(data["ielts"]) if data.get("ielts") not in (None, "") else None,
        sat=int(data["sat"]) if data.get("sat") not in (None, "") else None,
        gpa=gpa_norm,
        gpa_raw=float(data["gpa"]) if data.get("gpa") not in (None, "") else None,
        gpa_scale=detected_scale,
        budget_eur=int(data["budget"]) if data.get("budget") not in (None, "") else None,
        countries=countries,
        major=(data.get("major") or "").strip(),
        deadline=(data.get("deadline") or "").strip(),
        notes=(data.get("notes") or "").strip(),
    )


# ---------------------------------------------------------------------------
# Subject matching
# ---------------------------------------------------------------------------
def tokenise(text: str) -> set[str]:
    words = re.findall(r"[a-z]+", (text or "").lower())
    expanded: set[str] = set()
    for w in words:
        if w in STOPWORDS or len(w) < 2:
            continue
        expanded.add(w)
        expanded.update(SUBJECT_SYNONYMS.get(w, []))
        if len(w) > 5:
            expanded.add(w[:5])  # crude stemming: "engineering" ~ "engin"
    return expanded


def subject_score(profile_tokens: set[str], uni: University) -> tuple[float, list[str]]:
    if not profile_tokens:
        return 0.55, []
    matched_programmes: list[str] = []
    best = 0.0
    for programme in uni.majors or []:
        prog_tokens = tokenise(str(programme))
        if not prog_tokens:
            continue
        overlap = profile_tokens & prog_tokens
        if overlap:
            ratio = len(overlap) / max(len(prog_tokens), 1)
            score = min(1.0, 0.45 + ratio)
            if score > best:
                best = score
            matched_programmes.append(str(programme))
    haystack = tokenise(f"{uni.description} {uni.name}")
    if profile_tokens & haystack:
        best = max(best, 0.6)
    return (best if best else 0.25), matched_programmes[:4]


# ---------------------------------------------------------------------------
# Requirement + budget fit
# ---------------------------------------------------------------------------
def _ratio(student: float | None, required: float | None, ceiling: float) -> float | None:
    """1.0 = comfortably above the bar, 0.0 = far below it."""
    if student is None or required is None:
        return None
    if required <= 0:
        return 1.0
    delta = (student - required) / max(ceiling, 0.001)
    return max(0.0, min(1.0, 0.5 + delta * 2.5))


def requirement_fit(profile: StudentProfile, uni: University) -> dict:
    gaps: dict[str, dict] = {}
    parts: list[float] = []

    ielts_req = uni.min_ielts
    if ielts_req and profile.ielts is not None:
        parts.append(_ratio(profile.ielts, ielts_req, 2.0) or 0.5)
        gaps["ielts"] = {
            "required": ielts_req,
            "yours": profile.ielts,
            "delta": round(profile.ielts - ielts_req, 1),
            "meets": profile.ielts >= ielts_req,
        }

    if uni.sat_required and uni.min_sat and profile.sat:
        parts.append(_ratio(profile.sat, uni.min_sat, 300) or 0.5)
        gaps["sat"] = {
            "required": uni.min_sat,
            "yours": profile.sat,
            "delta": profile.sat - uni.min_sat,
            "meets": profile.sat >= uni.min_sat,
        }
    elif uni.min_sat and profile.sat:
        # SAT is optional here — treat a strong score as a bonus, never a penalty.
        parts.append(max(0.6, _ratio(profile.sat, uni.min_sat, 300) or 0.6))
        gaps["sat"] = {
            "required": uni.min_sat,
            "yours": profile.sat,
            "delta": profile.sat - uni.min_sat,
            "meets": profile.sat >= uni.min_sat,
            "optional": True,
        }

    gpa_req = uni.min_gpa
    if gpa_req and profile.gpa is not None:
        parts.append(_ratio(profile.gpa, gpa_req, 1.0) or 0.5)
        gaps["gpa"] = {
            "required": gpa_req,
            "yours": profile.gpa,
            "delta": round(profile.gpa - gpa_req, 2),
            "meets": profile.gpa >= gpa_req,
        }

    score = sum(parts) / len(parts) if parts else 0.5
    hard_misses = [k for k, v in gaps.items() if not v.get("meets") and not v.get("optional")]
    return {"score": round(score, 3), "gaps": gaps, "unmet": hard_misses}


def budget_fit(profile: StudentProfile, uni: University) -> dict:
    total = uni.annual_cost_eur
    tuition = uni.tuition_eur
    living = (uni.living_cost_eur or 0) + (uni.housing_cost_eur or 0)
    if not profile.budget_eur:
        return {
            "score": 0.6, "total_eur": total, "tuition_eur": tuition,
            "living_eur": living, "gap_eur": 0, "verdict": "unknown",
        }
    gap = profile.budget_eur - total
    if total <= 0:
        score, verdict = 0.7, "unknown"
    elif gap >= 0:
        headroom = gap / max(profile.budget_eur, 1)
        score = min(1.0, 0.8 + headroom * 0.4)
        verdict = "comfortable" if headroom > 0.15 else "within budget"
    else:
        over = -gap / max(profile.budget_eur, 1)
        score = max(0.0, 0.8 - over * 1.6)
        verdict = "stretch" if over <= 0.2 else "over budget"
    return {
        "score": round(score, 3),
        "total_eur": total,
        "tuition_eur": tuition,
        "living_eur": living,
        "gap_eur": gap,
        "verdict": verdict,
    }


def prestige_factor(uni: University) -> float:
    """Published acceptance rates flatter the famous schools: everyone who applies
    to ETH already cleared a self-selection filter. Ranking is used as a proxy for
    how strong the applicant pool is."""
    rank = uni.ranking_world
    if not rank:
        return 1.0
    if rank <= 10:
        return 0.55
    if rank <= 50:
        return 0.70
    if rank <= 150:
        return 0.85
    return 1.0


def admission_chance(profile: StudentProfile, uni: University, req: dict) -> float:
    """A rough probability. Selectivity sets the baseline; the student's margin
    over the published minimums moves it, but never far enough to promise a place.

    Clearing every stated minimum roughly multiplies the base rate by 1.35 — it
    does not make admission certain, which is the mistake a naive version of this
    makes and the reason students end up with four reach schools.
    """
    base = uni.acceptance_rate if uni.acceptance_rate is not None else 0.45
    base = max(0.02, min(0.95, base))
    strength = req["score"]
    adjusted = base * (0.30 + 1.05 * strength) * prestige_factor(uni)
    for key in req["unmet"]:
        adjusted *= 0.45 if key != "sat" else 0.7
    return round(max(0.01, min(0.92, adjusted)), 3)


def categorise(chance: float) -> str:
    if chance < 0.25:
        return "dream"
    if chance < 0.55:
        return "target"
    return "safe"


# ---------------------------------------------------------------------------
# Shortlisting
# ---------------------------------------------------------------------------
def score_university(profile: StudentProfile, uni: University, tokens: set[str]) -> dict:
    req = requirement_fit(profile, uni)
    money = budget_fit(profile, uni)
    subj, matched = subject_score(tokens, uni)
    chance = admission_chance(profile, uni, req)

    # Weights sum to 1.0 at their maxima, so the score uses the full 0–100 range
    # instead of pinning four different schools at 100.
    #
    # Country carries real weight. When a student names a country it's usually
    # driven by visas, family or language rather than taste, so a small bonus
    # gets swamped by ranking and ends up recommending Germany to someone who
    # asked for Ireland.
    country_bonus = 0.0
    if profile.countries:
        country_bonus = 0.15 if normalise_country(uni.country) in profile.countries else -0.10

    prestige = 0.0
    if uni.ranking_world:
        prestige = max(0.0, 0.09 * (1 - math.log10(max(uni.ranking_world, 1)) / 3.2))

    fit = (
        0.30 * req["score"]
        + 0.24 * money["score"]
        + 0.22 * subj
        + prestige
        + country_bonus
    )
    fit = max(0.0, min(1.0, fit))

    return {
        "university": uni,
        "fit_score": round(fit * 100),
        "admission_chance": chance,
        "category": categorise(chance),
        "requirements": req,
        "budget": money,
        "subject_score": round(subj, 3),
        "matched_programmes": matched,
    }


def shortlist(profile: StudentProfile, limit: int = 24) -> list[dict]:
    """Prefilter, score, then return a diverse top-N for the AI to choose from."""
    qs = University.objects.all()

    preferred_ids: list[int] = []
    if profile.countries:
        preferred_ids = [
            u.pk for u in qs.only("pk", "country")
            if normalise_country(u.country) in profile.countries
        ]
        # A student who asks for Poland should get Poland. Only when the chosen
        # countries hold too few universities to build a four-school list do we
        # backfill from elsewhere — and the country bonus keeps the preferred
        # ones ahead whenever quality is comparable.
        if len(preferred_ids) >= 4:
            qs = qs.filter(pk__in=preferred_ids)

    if profile.budget_eur:
        hard_ceiling = int(profile.budget_eur * 1.9)
        qs = qs.filter(
            models_q_cost_under(hard_ceiling)
        )

    tokens = tokenise(f"{profile.major} {profile.notes}")
    scored = [score_university(profile, uni, tokens) for uni in qs]
    scored.sort(key=lambda row: row["fit_score"], reverse=True)

    # Backfill case: the chosen countries were too thin to fill a list on their
    # own, so keep every one of them and add only a handful of alternatives.
    # Without this cap the alternatives outnumber the preference and the student
    # gets a list from countries they didn't ask for.
    if preferred_ids and len(preferred_ids) < 4:
        preferred_set = set(preferred_ids)
        in_country = [r for r in scored if r["university"].pk in preferred_set]
        others = [r for r in scored if r["university"].pk not in preferred_set]
        # Just enough alternatives to build a four-school list, no more.
        scored = in_country + others[: max(4, 8 - len(in_country))]

    # Guarantee the shortlist spans all three risk bands, otherwise the AI has
    # nothing sensible to label as a "safe" option.
    buckets: dict[str, list[dict]] = {"dream": [], "target": [], "safe": []}
    for row in scored:
        buckets[row["category"]].append(row)

    picked: list[dict] = []
    quotas = {"dream": max(4, limit // 5), "target": max(8, limit // 2), "safe": max(4, limit // 4)}
    for cat, quota in quotas.items():
        picked.extend(buckets[cat][:quota])
    for row in scored:
        if len(picked) >= limit:
            break
        if row not in picked:
            picked.append(row)

    picked.sort(key=lambda row: row["fit_score"], reverse=True)
    return picked[:limit]


def models_q_cost_under(ceiling: int):
    """Cost filter expressed over possibly-null columns."""
    from django.db.models import F, Q, Value
    from django.db.models.functions import Coalesce

    zero = Value(0)
    return Q(
        pk__in=University.objects.annotate(
            _total=Coalesce(F("tuition_max_eur"), F("tuition_min_eur"), zero)
            + Coalesce(F("living_cost_eur"), zero)
            + Coalesce(F("housing_cost_eur"), zero)
        )
        .filter(_total__lte=ceiling)
        .values("pk")
    )
