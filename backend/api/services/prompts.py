"""Prompt construction for the university-selection model.

Two rules drive the design here:
1. The model may only choose from the candidates we send. No invented schools,
   no remembered tuition figures — every number in the answer has to come from
   the database rows in the prompt.
2. The output is strict JSON with a fixed schema, so the frontend can render
   tables, charts and cards without any parsing guesswork.
"""

from __future__ import annotations

import json

from .matching import StudentProfile

SYSTEM_PROMPT = """You are the admissions advisor inside UniPath, a tool that \
helps school students in their final year build a realistic application list for \
European universities.

You will be given one student profile and a shortlist of candidate universities \
drawn from the app's database. Choose exactly four:
  - 1 "dream"  — a genuine reach. The student is below the typical admit on at \
least one dimension, or the school is highly selective.
  - 2 "target" — the student is at or slightly above the published bar and the \
cost works. These are the applications most likely to convert.
  - 1 "safe"   — comfortably above the requirements and comfortably inside the \
budget. This one exists so the student is never left with nothing.

Hard rules:
- Only choose universities from the candidate list. Never invent one.
- Only use the figures given for each candidate. Never substitute numbers from \
memory. If a figure is missing, say it is not in the database rather than guessing.
- All money is euros per academic year.
- Judge affordability on tuition + living costs against the student's budget. A \
university the student cannot pay for is not a target, no matter how good the fit.
- Be candid about risk. If the dream school is a long shot, say so plainly and \
say what would move the needle.
- Write to the student, in plain second person ("your IELTS is half a band \
below..."). No hedging filler, no congratulating them on their question.
- Keep every string free of markdown syntax. Plain sentences only.

Respond with a single JSON object and nothing else. No prose before or after, no \
markdown code fences."""


OUTPUT_SCHEMA = """{
  "summary": "3-4 sentences to the student: what their profile qualifies for overall, the single biggest lever they have, and how the four picks fit together.",
  "picks": [
    {
      "id": 0,                          // candidate id, copied exactly
      "category": "dream|target|safe",
      "fit_score": 0-100,               // how well the school matches their goals
      "admission_chance": 0.0-1.0,      // your estimate for THIS student
      "headline": "One line on why this school is on the list.",
      "why": ["2-4 concrete reasons, each referencing a real figure"],
      "risks": ["1-3 honest concerns: cost gap, score gap, language, competition"],
      "requirement_verdict": "Sentence comparing their IELTS/SAT/GPA to this school's bar.",
      "money_verdict": "Sentence on total yearly cost vs their budget, naming the gap in euros.",
      "scholarship_tip": "One specific, actionable funding route for this school, or \\"\\" if none is in the data.",
      "programme": "Best-matching programme name from the candidate's programme list."
    }
  ],
  "comparison": {
    "columns": ["Metric", "<uni 1 short name>", "<uni 2>", "<uni 3>", "<uni 4>"],
    "rows": [
      {"metric": "Tuition / year", "values": ["€X", "€Y", "€Z", "€W"]},
      {"metric": "Living costs / year", "values": [...]},
      {"metric": "Total / year", "values": [...]},
      {"metric": "vs your budget", "values": ["-€1,200", "+€3,400", ...]},
      {"metric": "IELTS required", "values": [...]},
      {"metric": "SAT", "values": [...]},
      {"metric": "GPA (4.0)", "values": [...]},
      {"metric": "Acceptance rate", "values": [...]},
      {"metric": "Language", "values": [...]},
      {"metric": "Application deadline", "values": [...]}
    ]
  },
  "timeline": [
    {"when": "Now – <month>", "task": "Short imperative task", "detail": "One sentence of specifics tied to their deadline."}
  ],
  "advice": {
    "ielts": "What their band opens and closes, and whether retaking is worth it.",
    "sat": "Whether the SAT helps at these schools at all, and what to do with it.",
    "gpa": "How their GPA reads to these admissions offices.",
    "budget": "The honest funding picture, including the cheapest of the four.",
    "next_step": "The one thing to do this week."
  }
}"""


def candidate_payload(rows: list[dict]) -> list[dict]:
    """Compact database rows — small enough to keep the prompt cheap, complete
    enough that the model never needs to guess a number."""
    payload = []
    for row in rows:
        u = row["university"]
        payload.append(
            {
                "id": u.id,
                "name": u.name,
                "city": u.city,
                "country": u.country,
                "world_rank": u.ranking_world,
                "acceptance_rate": u.acceptance_rate,
                "tuition_eur_year": u.tuition_eur or None,
                "living_cost_eur_year": (u.living_cost_eur or 0) + (u.housing_cost_eur or 0) or None,
                "total_cost_eur_year": u.annual_cost_eur or None,
                "min_ielts": u.min_ielts,
                "min_sat": u.min_sat,
                "sat_required": u.sat_required,
                "min_gpa_4": u.min_gpa,
                "language": u.language_of_instruction,
                "deadline": u.application_deadline,
                "programmes": (u.majors or [])[:12],
                "scholarships": (u.scholarship_notes or "")[:240],
                "has_housing": u.has_housing,
                "precomputed": {
                    "fit_score": row["fit_score"],
                    "admission_estimate": row["admission_chance"],
                    "band": row["category"],
                    "budget_verdict": row["budget"]["verdict"],
                    "budget_gap_eur": row["budget"]["gap_eur"],
                    "unmet_requirements": row["requirements"]["unmet"],
                    "matched_programmes": row["matched_programmes"],
                },
            }
        )
    return payload


def build_user_prompt(profile: StudentProfile, rows: list[dict]) -> str:
    student = {
        "ielts": profile.ielts,
        "sat": profile.sat,
        "gpa_on_4_scale": profile.gpa,
        "gpa_as_entered": f"{profile.gpa_raw} on a {profile.gpa_scale} scale" if profile.gpa_raw else None,
        "budget_eur_per_year": profile.budget_eur,
        "preferred_countries": profile.countries or ["no preference"],
        "intended_field": profile.major or "undecided",
        "application_deadline": profile.deadline or "not given",
        "extra_notes": profile.notes or "",
    }
    return (
        "STUDENT PROFILE\n"
        f"{json.dumps(student, indent=2)}\n\n"
        "CANDIDATE UNIVERSITIES (the only schools you may choose from)\n"
        "`precomputed` holds the app's own arithmetic. Treat it as a starting "
        "point you may disagree with, not an instruction.\n"
        f"{json.dumps(rows, indent=1)}\n\n"
        "OUTPUT SCHEMA — return exactly this shape, values replaced:\n"
        f"{OUTPUT_SCHEMA}\n\n"
        "Return the four picks ordered dream, target, target, safe."
    )
