"""HTTP layer.

One endpoint does the real work: POST /api/recommend. The rest exist to keep the
frontend honest — country and subject lists come from the database rather than
being hardcoded in JavaScript, so the form can never offer a filter that returns
nothing.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time

from django.conf import settings
from django.db.models import Count
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .models import RecommendationRun, University
from .serializers import RecommendationRequestSerializer
from .services import ai, fallback
from .services.assemble import assemble, serialise_university
from .services.images import ensure_images, ensure_images_bulk
from .services.matching import build_profile, shortlist

log = logging.getLogger(__name__)


def fingerprint(payload: dict) -> str:
    stable = json.dumps({k: v for k, v in sorted(payload.items()) if k != "refresh"}, default=str)
    return hashlib.sha256(stable.encode()).hexdigest()


@api_view(["GET"])
def health(request):
    return Response(
        {
            "status": "ok",
            "universities": University.objects.count(),
            "ai_configured": bool(settings.AI_API_KEY),
            "ai_provider": settings.AI_PROVIDER,
            "ai_model": settings.AI_MODEL if settings.AI_API_KEY else None,
            "image_lookup": settings.IMAGE_LOOKUP_ENABLED,
        }
    )


@api_view(["GET"])
def filters(request):
    """Everything the form needs to populate its dropdowns."""
    countries = (
        University.objects.exclude(country="")
        .values("country")
        .annotate(count=Count("id"))
        .order_by("country")
    )
    subjects: dict[str, int] = {}
    for majors in University.objects.values_list("majors", flat=True):
        for major in majors or []:
            key = str(major).strip()
            if key:
                subjects[key] = subjects.get(key, 0) + 1
    popular = sorted(subjects.items(), key=lambda kv: kv[1], reverse=True)[:40]

    costs = [u.annual_cost_eur for u in University.objects.all() if u.annual_cost_eur]
    return Response(
        {
            "countries": [{"name": c["country"], "count": c["count"]} for c in countries],
            "subjects": [name for name, _ in popular],
            "cost_range_eur": {
                "min": min(costs) if costs else 0,
                "max": max(costs) if costs else 0,
                "median": sorted(costs)[len(costs) // 2] if costs else 0,
            },
            "total_universities": University.objects.count(),
        }
    )


@api_view(["POST"])
def recommend(request):
    serializer = RecommendationRequestSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(
            {"error": "Some answers need fixing.", "fields": serializer.errors},
            status=status.HTTP_400_BAD_REQUEST,
        )

    data = serializer.validated_data
    profile = build_profile(data)
    key = fingerprint(dict(data))

    if not data.get("refresh"):
        cached = RecommendationRun.objects.filter(fingerprint=key).first()
        if cached:
            log.info("Serving cached plan %s", key[:8])
            return Response({**cached.result, "cached": True})

    started = time.monotonic()
    rows = shortlist(profile, limit=settings.AI_CANDIDATE_LIMIT)
    if not rows:
        return Response(
            {
                "error": "No universities in the database match those filters.",
                "hint": "Widen the budget or clear the country preference and try again.",
            },
            status=status.HTTP_404_NOT_FOUND,
        )

    try:
        plan, meta = ai.select_universities(profile, rows)
    except ai.AIUnavailable as exc:
        log.warning("Falling back to local ranking: %s", exc)
        plan, meta = fallback.build_plan(profile, rows)
        meta["fallback_reason"] = str(exc)

    # Only the four chosen schools get an image lookup — running it across the
    # whole shortlist would cost a dozen seconds for photos nobody sees.
    chosen_ids = {pick["id"] for pick in plan["picks"]}
    ensure_images_bulk([row["university"] for row in rows if row["university"].id in chosen_ids])

    result = assemble(profile, plan, rows, meta)
    result["total_ms"] = int((time.monotonic() - started) * 1000)

    RecommendationRun.objects.create(
        fingerprint=key,
        profile=profile.as_dict(),
        result=result,
        engine=result["engine"],
        model_name=meta.get("model", ""),
        latency_ms=meta.get("latency_ms", 0),
    )
    return Response({**result, "cached": False})


@api_view(["GET"])
def university_detail(request, pk: int):
    try:
        uni = University.objects.get(pk=pk)
    except University.DoesNotExist:
        return Response({"error": "No university with that id."}, status=status.HTTP_404_NOT_FOUND)
    if uni.missing_image_slots():
        ensure_images(uni)
    return Response(serialise_university(uni))


@api_view(["POST"])
def university_images(request, pk: int):
    """Force a fresh image lookup — handy on stage when a photo looks wrong."""
    try:
        uni = University.objects.get(pk=pk)
    except University.DoesNotExist:
        return Response({"error": "No university with that id."}, status=status.HTTP_404_NOT_FOUND)
    return Response(ensure_images(uni, force=True))


@api_view(["GET"])
def universities(request):
    """Browse the database directly. Supports ?country=&max_cost=&q=&limit="""
    qs = University.objects.all()
    if country := request.GET.get("country"):
        qs = qs.filter(country__iexact=country)
    if query := request.GET.get("q"):
        qs = qs.filter(name__icontains=query)
    limit = min(int(request.GET.get("limit", 60)), 300)

    max_cost = request.GET.get("max_cost")
    items = list(qs[: limit * 2])
    if max_cost:
        ceiling = int(max_cost)
        items = [u for u in items if u.annual_cost_eur <= ceiling]

    return Response(
        {"count": len(items[:limit]), "results": [serialise_university(u) for u in items[:limit]]}
    )
