"""Load the bundled demo dataset.

    python manage.py seed_universities

Use this to get a working demo before the real database arrives. Rows are marked
`data_source="seed"` so they're easy to clear later:

    python manage.py seed_universities --clear
    python manage.py import_universities --path real.csv --truncate
"""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand
from django.db import transaction

from api.models import University

DATA_FILE = Path(__file__).resolve().parents[2] / "data" / "seed_universities.json"


class Command(BaseCommand):
    help = "Load the bundled demo university dataset."

    def add_arguments(self, parser):
        parser.add_argument("--clear", action="store_true", help="Remove seed rows and stop.")
        parser.add_argument("--replace", action="store_true", help="Remove seed rows, then reload.")

    def handle(self, *args, **options):
        if options["clear"] or options["replace"]:
            deleted, _ = University.objects.filter(
                data_source=University.DataSource.SEED
            ).delete()
            self.stdout.write(self.style.WARNING(f"Removed {deleted} seed rows."))
            if options["clear"]:
                return

        payload = json.loads(DATA_FILE.read_text(encoding="utf-8"))
        rows = payload["universities"]

        created = updated = 0
        with transaction.atomic():
            for row in rows:
                existing = University.objects.filter(
                    name__iexact=row["name"], city__iexact=row["city"]
                ).first()
                if existing:
                    for key, value in row.items():
                        setattr(existing, key, value)
                    existing.data_source = University.DataSource.SEED
                    existing.save()
                    updated += 1
                else:
                    University.objects.create(**row, data_source=University.DataSource.SEED)
                    created += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded {created} new and {updated} existing universities. "
                f"{University.objects.count()} total.\n"
                "These are approximate demo figures — replace them with "
                "`import_universities` once you have the real file."
            )
        )
