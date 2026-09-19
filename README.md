# UniPath

Enter your IELTS, SAT, GPA and yearly budget. UniPath scores every university in
its database against your profile, hands a shortlist to an AI model, and returns
**one dream school, two targets and one safe option** — with real costs, campus
photos, an interactive map, comparison tables and charts.

Vite + vanilla JS + Tailwind CSS v4 on the front, Django + DRF on the back.

---

## Quick start

Two terminals. Python 3.11+ and Node 18+.

**Terminal 1 — backend**

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env               # then paste your AI key into it
python manage.py migrate
python manage.py seed_universities # demo data, replace with the real database
python manage.py runserver
```

**Terminal 2 — frontend**

```bash
cd frontend
npm install
npm run dev
```

Open <http://localhost:5173>.

Or run both at once with `./dev.sh` from the repo root.

The frontend calls `/api` and Vite proxies that to Django on port 8000, so there
is no CORS setup to get wrong and no hardcoded hostname to change at deploy time.

---

## Loading the real university database

The bundled dataset exists only so the app runs before your data arrives.
Replace it in one command:

```bash
cd backend
python manage.py import_universities --path ../data/universities.csv --truncate
```

Accepts **CSV, TSV, JSON, XLSX and SQLite**. For SQLite the table is auto-detected,
or name it with `--table universities`.

Column names are matched loosely — case, spacing and punctuation are ignored, and
common synonyms are recognised. All of these land in the same field:

| Your column might say | Goes to |
|---|---|
| `Tuition Fee (EUR/year)`, `tuition`, `annual_tuition`, `fees` | `tuition_max_eur` |
| `University Name`, `institution`, `school` | `name` |
| `IELTS Requirement`, `ielts_min`, `english_requirement` | `min_ielts` |
| `Programs Offered`, `courses`, `faculties`, `subjects` | `majors` |
| `Acceptance Rate`, `admission_rate`, `selectivity` | `acceptance_rate` |
| `Living Costs`, `cost_of_living` | `living_cost_eur` |

**Check the mapping before you commit to it:**

```bash
python manage.py import_universities --path yourfile.csv --dry-run
```

This prints every column, where it will land, and what the first row will look
like once stored — without writing anything.

Useful flags:

- `--truncate` — clear existing rows first
- `--currency-rate 0.92` — multiply every money column (e.g. USD → EUR)
- `--table <name>` — pick the SQLite table explicitly

**Nothing is discarded.** Columns that don't map to a known field are preserved
in the row's `extra` JSON, so no data is lost on import. Numbers are parsed
leniently: `€12,500`, `12.500,50`, `~9 000 EUR` and `18%` all work.

If a column keeps landing in the wrong place, add it to `FIELD_ALIASES` at the
top of `backend/api/management/commands/import_universities.py`.

---

## Connecting the AI

Put your key in `backend/.env`:

```ini
AI_PROVIDER=anthropic
AI_API_KEY=sk-ant-...
AI_MODEL=claude-sonnet-4-5
```

For any OpenAI-compatible endpoint instead:

```ini
AI_PROVIDER=openai
AI_API_KEY=sk-...
AI_MODEL=gpt-4o
AI_BASE_URL=https://api.openai.com/v1
```

Confirm it's live: `curl http://127.0.0.1:8000/api/health` should report
`"ai_configured": true`.

### What the model is and isn't allowed to do

This is the important design decision in the project.

The model receives a **shortlist of candidates with all their figures already
attached** and returns *judgement*: which four schools, which band each belongs
in, why each one is there, what the risks are. It never supplies a fact.

After it answers, every tuition figure, deadline, coordinate and photo is
**re-attached from the database**, and any pick whose ID wasn't in the shortlist
is dropped (`validate_plan` in `services/ai.py`). The model cannot invent a
university, misremember a price, or hallucinate a deadline into the UI.

### It degrades instead of breaking

No API key, a timeout, a rate limit, or prose where JSON was expected — all fall
through to a deterministic planner that returns the **identical response shape**,
tagged `engine: "heuristic"`. The UI stays fully functional and says plainly that
the commentary is templated.

This matters for a live demo: a spinner that never resolves in front of judges is
worse than a slightly duller answer.

---

## How a recommendation is built

```
form submit
   │
   ├─ 1. validate            serializers.py       friendly per-field messages
   ├─ 2. normalise           matching.py          GPA on any scale → /4.0
   ├─ 3. prefilter + score   matching.py          budget, requirements, subject, country
   │                                              → top ~24 candidates
   ├─ 4. choose              ai.py                model picks 4, explains them
   │       └─ on failure ──► fallback.py          same schema, deterministic
   ├─ 5. re-attach facts     assemble.py          DB is the source of truth
   ├─ 6. photos + map        images.py            parallel lookup, cached to DB
   └─ 7. chart datasets      assemble.py          shaped for direct SVG rendering
```

Steps 2 and 3 exist so the model spends its attention on judgement rather than
arithmetic, and so the prompt stays small enough to be fast and cheap.

### Scoring, in brief

- **Requirements** — how far your IELTS/SAT/GPA sit above or below each school's
  published bar. A missing SAT is never a penalty where the SAT is optional,
  which is most of continental Europe.
- **Budget** — tuition + living + housing against your figure. Anything over
  190% of your budget is filtered out entirely.
- **Subject** — your words are expanded through a synonym map ("CS" → computer,
  computing, informatics, software) and matched against programme names.
- **Country** — weighted heavily. Naming a country is usually about visas,
  family or language, not taste, so it filters strictly once a country has four
  or more universities in the database.
- **Admission odds** — the published acceptance rate, adjusted by your margin
  over the minimums and damped by a prestige factor. Clearing every minimum at a
  35%-acceptance school does not mean a 95% chance, and treating it that way is
  how students end up with four reach schools.

---

## Photos and campus maps

For each of the four picks, three image slots are filled — **the building, an
interior, and student housing** — in this order:

1. Whatever the provided database holds.
2. Wikipedia's page image (reliable for exteriors).
3. Wikimedia Commons, searched per slot, filtering out logos, crests and maps.
4. Openverse, for interiors and housing.

Results are written back to the row with attribution, so each university is
looked up once. Lookups run in parallel and only for the four chosen schools.
If the network is unavailable the UI draws a deterministic gradient placeholder —
it never shows a broken image.

Maps are **OpenStreetMap embeds** keyed off the university's coordinates. No API
key, so the map works on a judge's laptop immediately. If the database has an
official campus map URL, it's linked alongside.

Disable web lookups entirely with `IMAGE_LOOKUP_ENABLED=False`.

---

## API

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | Status, university count, whether the AI is configured |
| GET | `/api/filters` | Countries, subjects and cost range — populates the form |
| POST | `/api/recommend` | The main endpoint |
| GET | `/api/universities` | Browse the database (`?country=&q=&max_cost=&limit=`) |
| GET | `/api/universities/<id>` | One university, with images and map |
| POST | `/api/universities/<id>/images` | Force a fresh image lookup |

**Request**

```json
{
  "ielts": 7.0, "sat": 1380, "gpa": 3.6, "gpa_scale": "auto",
  "budget": 22000, "countries": ["Netherlands", "Germany"],
  "major": "computer science and AI", "deadline": "2027-01-15"
}
```

Every field is optional except that at least one of `ielts`, `sat` or `gpa` must
be present. `gpa_scale` accepts `auto`, `4`, `5`, `10`, `20` or `100`.
`budget` is a plain number, read as **euros per academic year**.

**Response** — `picks[]` (each with the full university record, the model's
reasoning and UniPath's own computed figures), `comparison`, `charts`,
`timeline`, `advice`, `budget_warning`, plus `engine` and `meta`.

Identical submissions are served from a cache keyed on the profile, so
re-demoing the same student costs nothing.

---

## Tests

```bash
cd backend && python manage.py test api
```

30 tests. They cover the parts most likely to fail quietly: extracting JSON from
a model response that arrived fenced or with a preamble, rejecting picks that
weren't in the shortlist, GPA scale conversion, the importer's fuzzy column
matching and number parsing, and the full `/api/recommend` path with the provider
stubbed — including both fallback routes.

Writing these changed the product three times: admission odds were reaching 95%,
fit scores saturated at 100 for four different schools, and an Ireland-only
request returned zero Irish universities.

---

## Design

UniPath uses a restrained editorial product system: **DM Sans** for interface
copy, **Source Serif 4** for page-level hierarchy, a deep blue product accent,
and muted dream/target/safe semantic colours. The light theme uses a quiet paper
canvas; dark mode has its own layered blue-charcoal surfaces rather than a simple
inversion. The navigation remains compact and keeps the route and theme controls
easy to reach at every viewport.

The landing page introduces the workflow and the kind of plan a student receives,
while the form is organised around academic profile, preferences, and optional
timing context. Both use shared tokens for controls, spacing, borders and focus
states instead of page-specific effects.

Charts are hand-written SVG (`src/ui/charts.js`). A charting library would have
added ~200KB and still needed overriding to match the type scale and the
dream/target/safe colours. Five chart types: stacked cost bars with a budget
reference line, admission odds showing the model's estimate against UniPath's own,
a profile radar, a diverging budget-gap chart and a cost-versus-odds scatter.

Accessibility: visible focus rings, `prefers-reduced-motion` respected, keyboard
dismissal for modal and lightbox, live-region announcements, and focus moved to
the heading on route change.

---

## Project layout

```
backend/
  api/
    services/
      matching.py     normalisation, scoring, shortlisting
      prompts.py      system prompt + strict output schema
      ai.py           provider calls, JSON extraction, validation
      fallback.py     deterministic planner, same schema
      assemble.py     re-attach DB facts, build chart datasets
      images.py       photo resolution + OSM campus map
    management/commands/
      import_universities.py   fuzzy importer for the provided database
      seed_universities.py     bundled demo data
    models.py  serializers.py  views.py  tests.py
frontend/
  src/
    pages/    landing.js  apply.js  results.js
    ui/       nav.js  components.js  charts.js
    lib/      dom.js  format.js  flip.js
    api.js  router.js  state.js  style.css
tools/build_seed.py
```

---

## About the bundled data

`seed_universities` loads **61 approximate entries across 23 countries**, marked
`data_source: "seed"` in the database and described as approximate in the app.

They exist to make the project runnable and demonstrable before the real database
arrives. **They are not authoritative and shouldn't be presented as researched
figures.** Tuition and living costs are indicative annual amounts for
international students; they move every year and vary by programme, nationality
and income band. Replace them before judging:

```bash
python manage.py seed_universities --clear
python manage.py import_universities --path <real file> --truncate
```

---

## Deployment notes

- Set `DJANGO_DEBUG=False`, a real `DJANGO_SECRET_KEY`, and your domain in
  `DJANGO_ALLOWED_HOSTS`.
- `DATABASE_URL=postgres://...` switches off SQLite (`pip install psycopg[binary]`).
- `npm run build` outputs to `frontend/dist`; serve it statically and reverse-proxy
  `/api` to Django. `npm run preview` serves the build locally with the proxy intact.
- The in-memory cache is per-process. Use Redis if you run more than one worker.

## Troubleshooting

**"Can't reach the server"** — Django isn't running, or it's not on port 8000.
Point Vite elsewhere with `VITE_API_TARGET=http://host:port`.

**`engine` says `heuristic`** — the AI call failed. `meta.fallback_reason` says
why; `/api/health` confirms whether the key was picked up.

**No photos** — check `IMAGE_LOOKUP_ENABLED`, and that outbound HTTPS to
wikipedia.org, wikimedia.org and openverse.org is allowed.

**Recommendations ignore a country** — that country probably has fewer than four
universities in the loaded database, so the shortlist is topped up from
neighbouring ones to fill all four bands.
