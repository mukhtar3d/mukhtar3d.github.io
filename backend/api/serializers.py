"""Request validation.

Error messages are written to be shown directly to a student under the field
that caused them, so they say what to do rather than what went wrong.
"""

from __future__ import annotations

from rest_framework import serializers


class RecommendationRequestSerializer(serializers.Serializer):
    ielts = serializers.FloatField(
        required=False, allow_null=True, min_value=0, max_value=9,
        error_messages={"max_value": "IELTS is scored out of 9.", "min_value": "IELTS can't be negative."},
    )
    sat = serializers.IntegerField(
        required=False, allow_null=True, min_value=400, max_value=1600,
        error_messages={
            "min_value": "The lowest possible SAT total is 400.",
            "max_value": "The highest possible SAT total is 1600.",
        },
    )
    gpa = serializers.FloatField(
        required=False, allow_null=True, min_value=0, max_value=100,
        error_messages={"max_value": "Enter your GPA on a 4, 5, 10, 20 or 100-point scale."},
    )
    gpa_scale = serializers.CharField(required=False, allow_blank=True, default="auto")
    budget = serializers.IntegerField(
        required=False, allow_null=True, min_value=0, max_value=500_000,
        error_messages={"max_value": "That looks like a typo — enter your yearly budget in euros."},
    )
    countries = serializers.ListField(
        child=serializers.CharField(allow_blank=True), required=False, default=list
    )
    major = serializers.CharField(required=False, allow_blank=True, default="", max_length=400)
    deadline = serializers.CharField(required=False, allow_blank=True, default="", max_length=80)
    notes = serializers.CharField(required=False, allow_blank=True, default="", max_length=1000)
    refresh = serializers.BooleanField(required=False, default=False)

    def validate_ielts(self, value):
        if value is None:
            return value
        # IELTS only comes in half bands; silently snapping avoids rejecting a
        # student for typing 7.3 when they meant 7.5.
        return round(value * 2) / 2

    def validate(self, attrs):
        if attrs.get("ielts") is None and attrs.get("gpa") is None and attrs.get("sat") is None:
            raise serializers.ValidationError(
                "Enter at least one of IELTS, SAT or GPA so there's something to match on."
            )
        return attrs
