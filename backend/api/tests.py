"""Tests for the parts that would fail quietly.

The riskiest code here isn't the Django plumbing, it's everything that touches
data we don't control: model output that may not be valid JSON, a university
database with unpredictable column names, and GPAs on five different scales.
"""

from __future__ import annotations

import json
from unittest.mock import patch

from django.test import Client, TestCase, override_settings

from api.models import University
from api.services import ai
from api.services.matching import build_profile, normalise_gpa, shortlist, tokenise

SETTINGS = {"ALLOWED_HOSTS": ["testserver"], "IMAGE_LOOKUP_ENABLED": False}


def make_university(**overrides) -> University:
    defaults = dict(
        name="Test University", city="Utrecht", country="Netherlands",
        ranking_world=120, acceptance_rate=0.45, tuition_max_eur=12000,
        living_cost_eur=8000, housing_cost_eur=0, min_ielts=6.5, min_gpa=3.0,
        min_sat=1200, sat_required=False, language_of_instruction="English",
        majors=["Computer Science", "Data Science"], latitude=52.09, longitude=5.12,
    )
    defaults.update(overrides)
    return University.objects.create(**defaults)


class JSONExtractionTests(TestCase):
    def test_plain_json(self):
        self.assertEqual(ai.extract_json('{"a": 1}')["a"], 1)

    def test_fenced_json(self):
        self.assertEqual(ai.extract_json('```json\n{"a": 2}\n```')["a"], 2)

    def test_json_with_preamble(self):
        text = 'Here is the plan you asked for:\n{"a": 3}\nHope that helps.'
        self.assertEqual(ai.extract_json(text)["a"], 3)

    def test_braces_inside_strings_do_not_confuse_the_scanner(self):
        text = '{"note": "a } inside a string", "ok": true}'
        self.assertTrue(ai.extract_json(text)["ok"])

    def test_escaped_quote_inside_string(self):
        text = r'{"note": "he said \"hi\" }", "ok": true}'
        self.assertTrue(ai.extract_json(text)["ok"])

    def test_truncated_json_raises(self):
        with self.assertRaises(ai.AIUnavailable):
            ai.extract_json('{"picks": [{"id": 1,')

    def test_empty_response_raises(self):
        with self.assertRaises(ai.AIUnavailable):
            ai.extract_json("")


class PlanValidationTests(TestCase):
    def test_drops_universities_not_in_the_shortlist(self):
        """The model must not be able to introduce a school we never offered."""
        plan = {"picks": [{"id": 1, "category": "dream"}, {"id": 999, "category": "safe"}]}
        cleaned = ai.validate_plan(plan, {1, 2})
        self.assertEqual([p["id"] for p in cleaned["picks"]], [1])

    def test_rejects_plan_where_nothing_is_valid(self):
        with self.assertRaises(ai.AIUnavailable):
            ai.validate_plan({"picks": [{"id": 999}]}, {1, 2})

    def test_clamps_out_of_range_scores(self):
        plan = {"picks": [{"id": 1, "category": "wat", "fit_score": 480, "admission_chance": 7.5}]}
        pick = ai.validate_plan(plan, {1})["picks"][0]
        self.assertEqual(pick["fit_score"], 100)
        self.assertEqual(pick["admission_chance"], 0.99)
        self.assertEqual(pick["category"], "target")

    def test_deduplicates_repeated_picks(self):
        plan = {"picks": [{"id": 1}, {"id": 1}]}
        self.assertEqual(len(ai.validate_plan(plan, {1})["picks"]), 1)


class GPAScaleTests(TestCase):
    def test_four_point_scale_passes_through(self):
        self.assertEqual(normalise_gpa(3.6, "auto"), (3.6, "4"))

    def test_hundred_point_scale_is_converted(self):
        value, scale = normalise_gpa(88, "auto")
        self.assertEqual((value, scale), (3.52, "100"))

    def test_five_point_scale_is_converted(self):
        self.assertEqual(normalise_gpa(4.5, "auto")[0], 3.6)

    def test_explicit_scale_overrides_the_guess(self):
        # 4.0 on a 5-point scale is a B, not a perfect score.
        self.assertEqual(normalise_gpa(4.0, "5")[0], 3.2)


class SubjectMatchingTests(TestCase):
    def test_abbreviations_expand_to_programme_vocabulary(self):
        tokens = tokenise("I want to study CS")
        self.assertIn("computer", tokens)

    def test_unrelated_words_do_not_match(self):
        self.assertNotIn("computer", tokenise("I want to study law"))


@override_settings(**SETTINGS)
class ShortlistTests(TestCase):
    def setUp(self):
        make_university(name="Cheap Safe", acceptance_rate=0.8, tuition_max_eur=2000,
                        living_cost_eur=5000, min_ielts=5.5, min_gpa=2.0, ranking_world=800)
        make_university(name="Mid Target", acceptance_rate=0.28, tuition_max_eur=10000,
                        living_cost_eur=8000, min_ielts=6.5, min_gpa=3.0, ranking_world=120)
        make_university(name="Hard Dream", acceptance_rate=0.08, tuition_max_eur=15000,
                        living_cost_eur=12000, min_ielts=7.5, min_gpa=3.9, ranking_world=5)

    def test_all_three_risk_bands_are_represented(self):
        profile = build_profile({"ielts": 7.0, "gpa": 3.5, "budget": 30000, "major": "computer science"})
        bands = {row["category"] for row in shortlist(profile)}
        self.assertEqual(bands, {"dream", "target", "safe"})

    def test_wildly_unaffordable_schools_are_excluded(self):
        profile = build_profile({"ielts": 7.0, "gpa": 3.5, "budget": 4000, "major": "computer science"})
        names = {row["university"].name for row in shortlist(profile)}
        self.assertNotIn("Hard Dream", names)

    def test_missing_requirement_lowers_the_odds(self):
        strong = build_profile({"ielts": 8.0, "gpa": 4.0, "budget": 40000})
        weak = build_profile({"ielts": 5.5, "gpa": 2.1, "budget": 40000})
        odds = lambda p: {r["university"].name: r["admission_chance"] for r in shortlist(p)}
        self.assertGreater(odds(strong)["Mid Target"], odds(weak)["Mid Target"])


FAKE_AI_RESPONSE = json.dumps({
    "summary": "A plan built from three schools.",
    "picks": [
        {"id": None, "category": "dream", "fit_score": 88, "admission_chance": 0.15,
         "headline": "A reach worth taking.", "why": ["Strong department"], "risks": ["Very selective"],
         "requirement_verdict": "Your IELTS clears the bar.", "money_verdict": "Inside budget.",
         "scholarship_tip": "Apply by December.", "programme": "Computer Science"},
        {"id": None, "category": "safe", "fit_score": 74, "admission_chance": 0.8,
         "headline": "A comfortable option.", "why": ["Cheap"], "risks": ["Lower ranked"],
         "requirement_verdict": "Comfortably above.", "money_verdict": "Well inside budget.",
         "scholarship_tip": "", "programme": "Data Science"},
    ],
    "comparison": {"columns": ["Metric", "A", "B"], "rows": [{"metric": "Tuition", "values": ["€1", "€2"]}]},
    "timeline": [{"when": "Now", "task": "Start", "detail": "Begin the applications."}],
    "advice": {"ielts": "Fine.", "sat": "Optional.", "gpa": "Good.", "budget": "Workable.", "next_step": "Apply."},
})


@override_settings(**SETTINGS, AI_API_KEY="test-key", AI_MODEL="test-model")
class RecommendEndpointTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.dream = make_university(name="Hard Dream", acceptance_rate=0.08, min_ielts=7.5,
                                     min_gpa=3.9, ranking_world=5)
        self.safe = make_university(name="Cheap Safe", acceptance_rate=0.85, tuition_max_eur=2000,
                                    living_cost_eur=5000, min_ielts=5.5, min_gpa=2.0, ranking_world=700)
        self.payload = {"ielts": 7.0, "sat": 1300, "gpa": 3.5, "budget": 25000,
                        "countries": ["Netherlands"], "major": "computer science",
                        "deadline": "2027-01-15"}

    def post(self, payload=None):
        return self.client.post("/api/recommend", data=json.dumps(payload or self.payload),
                                content_type="application/json")

    def test_ai_path_returns_a_plan(self):
        body = FAKE_AI_RESPONSE.replace('"id": null', f'"id": {self.dream.id}', 1)
        body = body.replace('"id": null', f'"id": {self.safe.id}', 1)
        with patch.object(ai, "call_model", return_value=body):
            response = self.post()
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["engine"], "ai")
        self.assertEqual(data["meta"]["model"], "test-model")
        self.assertEqual([p["category"] for p in data["picks"]], ["dream", "safe"])
        # Facts come from the database, not from the model.
        self.assertEqual(data["picks"][0]["university"]["name"], "Hard Dream")
        self.assertTrue(data["picks"][0]["university"]["map"]["available"])

    def test_falls_back_when_the_provider_fails(self):
        with patch.object(ai, "call_model", side_effect=ai.AIUnavailable("boom")):
            data = self.post().json()
        self.assertEqual(data["engine"], "heuristic")
        self.assertEqual(len(data["picks"]), 4 if University.objects.count() >= 4 else 2)
        self.assertIn("boom", data["meta"]["fallback_reason"])

    def test_falls_back_when_the_model_returns_nonsense(self):
        with patch.object(ai, "call_model", return_value="I'm afraid I can't do that."):
            self.assertEqual(self.post().json()["engine"], "heuristic")

    def test_identical_submissions_are_served_from_cache(self):
        with patch.object(ai, "call_model", side_effect=ai.AIUnavailable("x")):
            self.post()
            second = self.post().json()
        self.assertTrue(second["cached"])

    def test_rejects_an_empty_profile(self):
        response = self.post({"major": "law"})
        self.assertEqual(response.status_code, 400)

    def test_charts_line_up_with_the_picks(self):
        with patch.object(ai, "call_model", side_effect=ai.AIUnavailable("x")):
            data = self.post().json()
        charts = data["charts"]
        self.assertEqual(len(charts["cost"]["labels"]), len(data["picks"]))
        self.assertEqual(len(charts["admission"]["ai"]), len(data["picks"]))
        for series in charts["cost"]["series"]:
            self.assertEqual(len(series["values"]), len(data["picks"]))


class ImporterTests(TestCase):
    def test_messy_headers_map_onto_model_fields(self):
        from api.management.commands.import_universities import build_header_map

        mapping, unmapped = build_header_map(
            ["University Name", "Country", "Tuition Fee (EUR/year)", "IELTS Requirement",
             "Minimum GPA", "Programs Offered", "random_extra_column"]
        )
        self.assertEqual(mapping["University Name"], "name")
        self.assertEqual(mapping["Tuition Fee (EUR/year)"], "tuition_max_eur")
        self.assertEqual(mapping["IELTS Requirement"], "min_ielts")
        self.assertEqual(mapping["Programs Offered"], "majors")
        self.assertIn("random_extra_column", unmapped)

    def test_number_parsing_handles_both_thousand_separators(self):
        from api.management.commands.import_universities import parse_number

        self.assertEqual(parse_number("€12,500"), 12500)
        self.assertEqual(parse_number("12.500,75"), 12501)  # European separators
        self.assertEqual(parse_number("n/a"), None)
        self.assertEqual(parse_number("~9 000 EUR"), 9000)  # space-separated thousands
        self.assertEqual(parse_number("7 200"), 7200)
        self.assertEqual(parse_number("1 600"), 1600)

    def test_percentages_become_fractions(self):
        from api.management.commands.import_universities import coerce

        self.assertEqual(coerce("acceptance_rate", "18%"), 0.18)
        self.assertEqual(coerce("acceptance_rate", "0.18"), 0.18)
        self.assertEqual(coerce("acceptance_rate", "18"), 0.18)

    def test_programme_lists_split_on_any_common_separator(self):
        from api.management.commands.import_universities import parse_list

        self.assertEqual(parse_list("CS; Law; Physics"), ["CS", "Law", "Physics"])
        self.assertEqual(parse_list('["CS", "Law"]'), ["CS", "Law"])
        self.assertEqual(parse_list("CS|Law"), ["CS", "Law"])
