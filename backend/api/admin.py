from django.contrib import admin

from .models import RecommendationRun, University


@admin.register(University)
class UniversityAdmin(admin.ModelAdmin):
    list_display = (
        "name", "city", "country", "ranking_world",
        "tuition_max_eur", "min_ielts", "min_gpa", "has_images",
    )
    list_filter = ("country", "sat_required", "has_housing", "data_source")
    search_fields = ("name", "city", "country", "description")
    readonly_fields = ("created_at", "updated_at", "images_fetched_at")

    @admin.display(boolean=True, description="Photos")
    def has_images(self, obj):
        return bool(obj.image_front)


@admin.register(RecommendationRun)
class RecommendationRunAdmin(admin.ModelAdmin):
    list_display = ("fingerprint", "engine", "model_name", "latency_ms", "created_at")
    list_filter = ("engine",)
    readonly_fields = ("profile", "result")
