# CDPR's Restricted Flag — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A product's restricted status comes from CDPR's per-product `RESTRICTED.txt` (2023+ archives), with the ingredient rule only for products CDPR's file doesn't list; the "Restricted materials" narrowing follows the product.

**Architecture:** `Product` gains `california_restricted` (nullable bool: True/False from CDPR's file, NULL = not in the file → ingredient fallback) and `federally_restricted` (nullable bool, stored only). `import_pur` reads `RESTRICTED.txt`. `Product.is_restricted` / `ProductQuerySet.with_restricted()` and the restricted narrowing (`stats.narrow_rows`, `stats.narrow_notices`) read the product flag with the fallback. Chemical badges stay on the curated 3 CCR 6400 list.

**Tech Stack:** Django models/migrations, the PUR importer, rollup narrowing.

**Spec (approved in conversation, 2026-10-06):** CDPR's flag is authoritative for products (it applies 6400's formulation/use exemptions a per-ingredient rule can't — e.g. zinc-phosphide and strychnine baits are exempt; paraquat/atrazine/simazine/bentazon/norflurazon/dicamba products are restricted though our list misses them: 248 + 566 of 2,472 products disagree today). Products absent from the file (mostly unrestricted; some cancelled before 2023, e.g. chlorpyrifos) fall back to the ingredient rule. The narrowing means records whose *product* is restricted. Chemical badges unchanged. Federal flag stored, not displayed.

## Global Constraints
- Worktree `/home/derek/dev/ccac/sjvair.com/.claude/worktrees/feature+pesticides-explorer`, branch `feature/pesticides-explorer`; absolute paths, `git -C <worktree>`; never the main checkout.
- Tests: `django.test.TestCase`, plain `assert`; verbose names `_('Label')` as first positional arg; don't align `=`.
- **Commit messages: no `Co-Authored-By` trailer and no AI attribution of any kind**; check `git log -1 --format=%B` after each commit. Commit locally; never push.
- Fallback rule, exactly: `california_restricted is True` → restricted; `is False` → not restricted (even if an ingredient is on our list); `is None` → restricted iff any ingredient is in `stats.restricted_chemicals()`.
- 2022-and-older archives have no `RESTRICTED.txt`: their import must leave existing flags untouched (never reset to NULL).

## Review Focus
1. A 2022 import after a 2023 import must not wipe the flags (Task 1 test).
2. Products CDPR's file lists as `california_restricted` blank → False, not NULL (the file lists them because they're federally restricted) (Task 1 test).
3. Narrowed record counts (`records`) stay exact under the product-level narrowing — product is report-level, so every row of a report is kept or dropped together (Task 2 test via the rollup).
4. Notices narrowed to restricted follow the product flag + fallback (Task 2 test).

---

### Task 1: Model fields and the importer

**Files:** `camp/apps/pesticides/models.py` (Product), new migration, `camp/apps/pesticides/management/commands/import_pur.py` (`_import_products` or a new `_import_restricted`, called from the lookup block in `handle`), `camp/apps/pesticides/tests/test_import_pur.py`.

- Fields: `california_restricted = models.BooleanField(_('California restricted'), null=True, default=None)` and `federally_restricted = models.BooleanField(_('Federally restricted'), null=True, default=None)`, with a comment: NULL = not in CDPR's RESTRICTED.txt (2023+), see `is_restricted`.
- Importer: `_find(lookup_dir, 'RESTRICTED.txt', 'restricted.txt')`; absent → print "  [restricted] file not found, flags unchanged" and return. Present → for every row, set both flags from `x`/blank (`clean(value).lower() == 'x'`) on the product by `prodno` (bulk: collect, then `Product.objects.filter(prodno__in=…)` updates or `bulk_update`); products in the file but not in the DB are skipped (counted). Products in the DB but not in the file are left as they are (NULL until a file lists them → the ingredient fallback). Print counts.
- Replace/retire the tests and comments that say CDPR publishes no RESTRICTED.txt (`ProductRestrictedTests` docstring etc.).
- Tests: a lookup dir with `RESTRICTED.txt` → flags set (x → True, blank → False); a product absent from the file stays NULL; a later import with no RESTRICTED file leaves flags unchanged.
- Commit: `feat(pesticides): import CDPR's per-product restricted flags`

### Task 2: Restricted status and the narrowing read the product flag

**Files:** `camp/apps/pesticides/models.py` (`Product.is_restricted` ~259, `ProductQuerySet.with_restricted`), `camp/apps/pesticides/stats.py` (`narrow_rows` ~286, `narrow_notices` ~299), tests.

- `is_restricted` / `with_restricted()` implement the fallback rule exactly (annotation: `Case(When(california_restricted=True, then=True), When(california_restricted=False, then=False), default=<exists restricted ingredient>)`).
- `narrow_rows(rows, NARROW_RESTRICTED)`: `rows.filter(Q(product__california_restricted=True) | Q(product__california_restricted__isnull=True, product__chemicals__in=restricted_chemicals()))` — check how `rows` (rollup / totals) reference the product (FK `product`?); for totals rows without a product dimension, check `narrow_needs_rollup` already routes restricted to the rollup (it must now — add `NARROW_RESTRICTED` if not). Use `.distinct()` only if the join can duplicate; prefer an `Exists` subquery on the product's chemicals to avoid duplication.
- `narrow_notices(notices, NARROW_RESTRICTED)`: notices list products; a notice is restricted if any of its products is restricted by the same rule (Exists over `products`).
- Anywhere else that decides "restricted" for a product (grep `is_restricted`, `restricted_chemicals(` in views/templates/API serializers — product badges, the API's `california_restricted` key) follows the product rule; chemical-level uses stay on the curated list.
- Tests: a product CDPR-flagged True whose ingredients aren't on our list is restricted; a product flagged False with a listed ingredient isn't; a NULL product falls back; narrowed rollup totals/records for a report with that product are kept/dropped together; restricted notices follow it; the product badge/API key reflect it.
- Commit: `feat(pesticides): restricted products and the narrowing follow CDPR's flag`

---

## After the tasks
- Dev DB (background): `import_pur --year 2023`, `rebuild_pesticide_rollup --all`, cache flush.
- PR description line (no deploy steps — staging/prod get a full re-import).
