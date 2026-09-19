"""Data model for the European university database.

The schema is deliberately forgiving: every field except `name` is optional, and
anything in the source file that doesn't map onto a known column is kept in
`extra` rather than thrown away. That way the organisers' database can be
imported as-is and nothing is lost.
"""

from __future__ import annotations

from django.db import models
from django.utils import timezone
from django.utils.text import slugify


class University(models.Model):
    class DataSource(models.TextChoices):
        PROVIDED = "provided", "Provided database"
        SEED = "seed", "Bundled demo data"
        MANUAL = "manual", "Entered by hand"

    # --- identity -----------------------------------------------------------
    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=280, unique=True, blank=True)
    country = models.CharField(max_length=80, blank=True, db_index=True)
    city = models.CharField(max_length=120, blank=True)
    website = models.URLField(blank=True)
    description = models.TextField(blank=True)

    # --- rankings -----------------------------------------------------------
    ranking_world = models.PositiveIntegerField(null=True, blank=True)
    ranking_national = models.PositiveIntegerField(null=True, blank=True)
    acceptance_rate = models.FloatField(
        null=True, blank=True, help_text="0–1. 0.12 means 12% of applicants are admitted."
    )

    # --- money (all stored in EUR per academic year) ------------------------
    tuition_min_eur = models.PositiveIntegerField(null=True, blank=True)
    tuition_max_eur = models.PositiveIntegerField(null=True, blank=True)
    living_cost_eur = models.PositiveIntegerField(null=True, blank=True)
    housing_cost_eur = models.PositiveIntegerField(null=True, blank=True)
    application_fee_eur = models.PositiveIntegerField(null=True, blank=True)
    scholarship_notes = models.TextField(blank=True)
    scholarship_max_eur = models.PositiveIntegerField(null=True, blank=True)

    # --- entry requirements -------------------------------------------------
    min_ielts = models.FloatField(null=True, blank=True)
    avg_ielts = models.FloatField(null=True, blank=True)
    min_sat = models.PositiveIntegerField(null=True, blank=True)
    avg_sat = models.PositiveIntegerField(null=True, blank=True)
    sat_required = models.BooleanField(default=False)
    min_gpa = models.FloatField(null=True, blank=True, help_text="On a 4.0 scale.")
    avg_gpa = models.FloatField(null=True, blank=True)
    language_of_instruction = models.CharField(max_length=120, blank=True)
    majors = models.JSONField(default=list, blank=True)
    application_deadline = models.CharField(
        max_length=120, blank=True, help_text="Free text, e.g. '15 January' or '2026-01-15'."
    )

    # --- campus & location --------------------------------------------------
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)
    campus_map_url = models.URLField(blank=True, help_text="Official interactive or PDF campus map.")
    has_housing = models.BooleanField(default=False)

    # --- imagery ------------------------------------------------------------
    image_front = models.URLField(max_length=700, blank=True)
    image_inside = models.URLField(max_length=700, blank=True)
    image_housing = models.URLField(max_length=700, blank=True)
    image_credits = models.JSONField(default=dict, blank=True)
    images_fetched_at = models.DateTimeField(null=True, blank=True)

    # --- bookkeeping --------------------------------------------------------
    data_source = models.CharField(
        max_length=20, choices=DataSource.choices, default=DataSource.PROVIDED
    )
    extra = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["ranking_world", "name"]
        indexes = [
            models.Index(fields=["country", "city"]),
            models.Index(fields=["tuition_min_eur"]),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.city}, {self.country})" if self.city else self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(f"{self.name}-{self.city or self.country}")[:270] or "university"
            candidate, n = base, 2
            while University.objects.filter(slug=candidate).exclude(pk=self.pk).exists():
                candidate = f"{base}-{n}"
                n += 1
            self.slug = candidate
        super().save(*args, **kwargs)

    # --- derived helpers ----------------------------------------------------
    @property
    def tuition_eur(self) -> int:
        """A single tuition figure to plan against — the top of the range."""
        if self.tuition_max_eur is not None:
            return self.tuition_max_eur
        return self.tuition_min_eur or 0

    @property
    def annual_cost_eur(self) -> int:
        living = self.living_cost_eur or 0
        housing = self.housing_cost_eur or 0
        # `living_cost_eur` is treated as all-in when no separate housing figure
        # exists; when both exist they are summed.
        return self.tuition_eur + living + housing

    @property
    def images_are_stale(self) -> bool:
        if not (self.image_front or self.image_inside or self.image_housing):
            return True
        if self.images_fetched_at is None:
            return False
        from django.conf import settings

        age = timezone.now() - self.images_fetched_at
        return age.days > settings.IMAGE_CACHE_DAYS

    def missing_image_slots(self) -> list[str]:
        slots = []
        if not self.image_front:
            slots.append("front")
        if not self.image_inside:
            slots.append("inside")
        if not self.image_housing:
            slots.append("housing")
        return slots


class RecommendationRun(models.Model):
    """One submitted form + the plan that came back. Useful for the demo, and
    it doubles as a cache so repeated submissions don't re-bill the API."""

    fingerprint = models.CharField(max_length=64, db_index=True)
    profile = models.JSONField(default=dict)
    result = models.JSONField(default=dict)
    engine = models.CharField(max_length=32, default="ai")
    model_name = models.CharField(max_length=120, blank=True)
    latency_ms = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.fingerprint[:8]} · {self.engine} · {self.created_at:%Y-%m-%d %H:%M}"
