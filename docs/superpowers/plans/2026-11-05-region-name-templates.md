# Region display names (`name_template`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Serve a per-type display-name pattern in `regions/meta/` and give sdk-js the schema
field and a `regionDisplayName` helper, so the dashboard shows "ZIP 93702" and the like from
metadata.

**Architecture:** One constant dict on `Region`, read by `RegionMetaEndpoint.get_types`; no
model, row or query changes. In sdk-js, one schema field plus one pure helper file. Server
first (its PR into `develop`), then the SDK (its PR into `release/5.0.0`), tested against the
local stack serving the server branch.

**Tech Stack:** Django + django-resticus (sjvair.com), Deno 2 + zod (sdk-js).

**Spec:** sjvair.com `docs/superpowers/specs/2026-11-05-region-name-templates-design.md` and
sdk-js `docs/superpowers/specs/2026-11-05-region-name-templates-design.md`. This plan is saved
in both repos; the sjvair.com copy is the one to edit.

## Global Constraints

- Templates, verbatim: `zipcode` `"ZIP {name}"`, `tract` `"Census Tract {name}"`,
  `urban_area` `"{name} Urban Area"`, `ab617` `"{name} AB 617 Community"`; every other type
  `null`.
- `{name}` is the only placeholder and appears exactly once in each template.
- Region `name`, slug, `external_id`, ids and every region row stay unchanged.
- SDK `name_template` is required (`z.nullable(z.string())`, not optional): no fallbacks for
  older servers.
- Worktrees: sjvair.com `.worktrees/region-name-templates`, sdk-js
  `.worktrees/region-name-templates`, both on branch `feature/region-name-templates` (already
  created, specs committed).
- No Claude or AI attribution in commits or PRs. Never merge, tag, publish or cut a beta
  without the user's explicit yes for that specific action.
- Nothing touches production.
- Message the coordinator (`data-dashboard-b7`) before swapping the shared web container to a
  branch and again when it's back on the main checkout; don't restart the Huey workers.

## Review Focus

1. A region name holding `$&`, `$1` or `$$` comes out literally (a replacement-string
   `replace` would expand them). Test in Task 4.
2. A name that itself contains `{name}` is not expanded again (replace once, in the
   template only). Test in Task 4.
3. A type missing from the meta object (e.g. a type added server-side later) shows the plain
   name instead of throwing. Test in Task 4.
4. The `RegionsMeta` instance from `getRegionsMeta()` works as `meta`, not only the plain
   data. Test in Task 4.
5. The lazy translation strings serialize to plain JSON strings, not proxies or `null`. The
   full-map test in Task 2 asserts exact string values over HTTP.

---

### Task 1: sjvair.com test baseline

**Files:** none changed. Copy `.env`, `.env.test` and `docker-compose.override.yml` from the
main checkout into the worktree (git-ignored).

- [ ] **Step 1: Run the full suite in the worktree (still at develop 95daa0bc plus the spec commit)**

Run (from the worktree):
`podman run --rm --network sjvaircom_sjvair-net --env-file .env.test -e BAM_MIRROR_ENABLED=0 -e TWILIO_AUTH_TOKEN=test-token -v $PWD:/app:z -v ~/workspace/django-resticus/.worktrees/session-csrf/resticus:/usr/local/lib/python3.14/site-packages/resticus:ro,z -w /app sjvair-com-test:latest pytest -n 4 --dist loadscope 2>&1 | tee ../region-name-templates-baseline.log | tail -5`
Expected: record pass/fail/skip counts (ignore the trailing "not a git repository" line).
Any failures here are pre-existing; list them so later runs compare against them.

### Task 2: `name_template` in `regions/meta/`

**Files:**
- Modify: `camp/apps/regions/models.py` (beside `TYPE_LABELS_PLURAL`, ~line 58)
- Modify: `camp/api/v2/regions/endpoints.py` (`RegionMetaEndpoint.get_types`, ~line 374)
- Test: `camp/api/v2/regions/tests.py` (the meta test class holding `test_label_plural`)
- Modify: `CLAUDE.md` → "Metadata Endpoints" → **Regions**

**Interfaces:**
- Produces: `Region.TYPE_NAME_TEMPLATES: dict[Region.Type, lazy str]` holding only the four
  types; JSON key `types.<type>.name_template: str | None`.

- [ ] **Step 1: Write the failing tests**

In the meta test class:
- `test_type_fields`: add `'name_template': None,` to the expected county dict.
- New `test_name_template`:

```python
def test_name_template(self):
    response, content = self._fetch_region_meta()
    templates = {t: info['name_template'] for t, info in content['data']['types'].items()}
    assert templates == {t: None for t in Region.Type.values} | {
        'zipcode': 'ZIP {name}',
        'tract': 'Census Tract {name}',
        'urban_area': '{name} Urban Area',
        'ab617': '{name} AB 617 Community',
    }
```

- New `test_name_templates_hold_name_once`: for every value in `Region.TYPE_NAME_TEMPLATES`,
  `assert str(template).count('{name}') == 1`.

- [ ] **Step 2: Run them to verify they fail**

Run: the test command from Task 1 with `pytest camp/api/v2/regions/tests.py -k "type_fields or name_template" -v` in place of `pytest -n 4 --dist loadscope`.
Expected: FAIL (`KeyError: 'name_template'` / `AttributeError: TYPE_NAME_TEMPLATES`).

- [ ] **Step 3: Implement**

`models.py`: `TYPE_NAME_TEMPLATES` with a one-line comment ("How a region of this type is
shown, `{name}` standing for its name; types not listed show the name as it is."), values in
`_()` like `TYPE_LABELS_PLURAL`. `endpoints.py`: in `get_types`, after `label_plural`, add
`'name_template'` set to `str(template)` when `Region.TYPE_NAME_TEMPLATES.get(region_type)` is
not `None`, else `None`.

- [ ] **Step 4: Run them to verify they pass**

Same command as Step 2. Expected: PASS.

- [ ] **Step 5: Document**

`CLAUDE.md` **Regions** bullet: after the `label_plural` clause, add that `regions/meta/`
types carry `name_template` (`Region.TYPE_NAME_TEMPLATES`): a pattern with `{name}` once, for
showing a region (`"ZIP {name}"`, `"Census Tract {name}"`, `"{name} Urban Area"`,
`"{name} AB 617 Community"`), `null` for types shown by their plain name; region rows don't
carry it.

- [ ] **Step 6: Full suite**

Run the Task 1 command (tee to `../region-name-templates-final.log`). Expected: same counts
as the baseline plus the new tests, no new failures.

- [ ] **Step 7: Commit**

```bash
git add camp/apps/regions/models.py camp/api/v2/regions/endpoints.py camp/api/v2/regions/tests.py CLAUDE.md
git commit -m "feat(regions): name_template for region types in regions/meta/"
```

### Task 3: sjvair.com PR

- [ ] **Step 1:** `git fetch`, rebase on `origin/develop` if it moved, rerun the Task 2 tests.
- [ ] **Step 2:** Push `feature/region-name-templates` and open a PR into `develop`: what
  changed, the four templates, "no row/name/code changes", the deferred tract short form
  (data-dashboard `DEFERRED.md`), test counts vs baseline. No attribution lines.
- [ ] **Step 3:** Tell the coordinator the PR number. Do not merge.

### Task 4: sdk-js schema field and `regionDisplayName`

Work in the sdk-js worktree. Copy `.env` from the sdk-js main checkout.

**Files:**
- Modify: `lib/regions/schemas/regions_meta.ts` (`RegionTypeMetaSchema` interface and
  `regionTypeMetaSchema`)
- Modify: `lib/regions/fixtures/regions_meta.json` (add `name_template` to every type, values
  per Global Constraints)
- Modify: `lib/regions/regions_hierarchy_test.ts` (next to "regions meta types carry a plural
  label")
- Create: `lib/regions/region_display_name.ts`
- Create: `lib/regions/region_display_name_test.ts`
- Modify: `lib/regions/mod.ts` (re-export), `deno.json` `exports`
  (`"./regions/region_display_name": "./lib/regions/region_display_name.ts"`, in sorted
  position)
- Modify: `CHANGELOG.md` (5.0.0 section: an "Added" line)

**Interfaces:**
- Consumes: server JSON `types.<type>.name_template: string | null` (Task 2).
- Produces:
  `regionDisplayName(region: { type: RegionType; name: string }, meta: Pick<RegionsMetaData, "types">): string`
  exported from `@sjvair/sdk/regions` and `@sjvair/sdk/regions/region_display_name`;
  `RegionTypeMeta.name_template: string | null`.

- [ ] **Step 1: Write the failing tests**

In `regions_hierarchy_test.ts`, "regions meta types carry a name template":
- `assertEquals(metaData.types.zipcode.name_template, "ZIP {name}")`, same for `tract`,
  `urban_area`, `ab617` with their exact templates; `assertEquals(metaData.types.city.name_template, null)`.
- Without the key, `regionTypeMetaSchema.safeParse(...)` fails (mirror the `label_plural`
  destructuring check).

In `region_display_name_test.ts` (network-free, uses the fixture as `RegionsMetaData`):
- `regionDisplayName({ type: "zipcode", name: "93702" }, meta)` → `"ZIP 93702"`
- `{ type: "ab617", name: "Arvin, Lamont" }` → `"Arvin, Lamont AB 617 Community"`
- `{ type: "city", name: "Arvin" }` → `"Arvin"` (null template)
- type missing: pass `{ types: {} } as unknown as Pick<RegionsMetaData, "types">` with
  `{ type: "zipcode", name: "93702" }` → `"93702"`
- `{ type: "urban_area", name: "A $& $1 $$ B" }` → `"A $& $1 $$ B Urban Area"`
- `{ type: "zipcode", name: "{name}" }` → `"ZIP {name}"`
- `new RegionsMeta(meta)` as `meta` with `{ type: "tract", name: "06019000100" }` →
  `"Census Tract 06019000100"`

- [ ] **Step 2: Run them to verify they fail**

Run: `deno test --allow-read lib/regions/region_display_name_test.ts lib/regions/regions_hierarchy_test.ts`
Expected: FAIL (module not found / `name_template` undefined).

- [ ] **Step 3: Implement**

- Schema: `name_template: z.nullable(z.string())` after `label_plural`, interface entry
  `name_template: z.ZodNullable<z.ZodString>` with the doc comment from the sdk-js spec.
- Fixture: add the key to every type in `regions_meta.json` (recaptured in Task 5 if the live
  response differs in any other way).
- Helper: module doc with a usage example like the other `lib/regions` files; look up
  `meta.types[region.type]?.name_template`; when a string, return
  `template.split("{name}").join(region.name)`; otherwise `region.name`.
- `mod.ts` re-export, `deno.json` export, and under `CHANGELOG.md` 5.0.0 → "Added":
  `` `regions/meta/` types carry `name_template`; `regionDisplayName(region, meta)` shows a region with it (falls back to `name`). ``

- [ ] **Step 4: Run them to verify they pass**

Same command as Step 2. Expected: PASS.

- [ ] **Step 5: Static checks**

Run: `deno fmt --check && deno lint && deno check mod.ts`
Expected: no output errors. (`deno fmt` fixes formatting if needed.)

- [ ] **Step 6: Commit**

```bash
git add lib/regions deno.json CHANGELOG.md
git commit -m "feat(regions): name_template and regionDisplayName"
```

### Task 5: Live check against the server branch, then the sdk-js PR

- [ ] **Step 1:** Message the coordinator that the shared web container is about to serve
  sjvair.com `feature/region-name-templates`.
- [ ] **Step 2:** Swap: copy `docker-compose.override.yml`, `.env`, `.env.test` into the
  sjvair.com worktree; `podman stop sjvaircom_web_1 && podman rm sjvaircom_web_1`; from the
  worktree, `podman-compose -p sjvaircom --profile web up -d --no-deps web`.
  Check: `curl -s localhost:8000/api/2.0/regions/meta/ | python -m json.tool | grep name_template | sort | uniq -c`
  shows 4 strings and 12 `null`.
- [ ] **Step 3:** Compare the live `regions/meta/` `types` to the fixture (counts aside); if
  anything besides `count` differs, recapture the fixture from the live response.
- [ ] **Step 4:** From the sdk-js worktree:
  `deno fmt --check && deno lint && deno check mod.ts && deno test --allow-net --allow-env --allow-read --env-file=.env --ignore=lib/account`
  Expected: pass, except `closest/` steps that need current PM2.5 (note them). Never run the
  account tests.
- [ ] **Step 5:** Restore: `podman stop sjvaircom_web_1 && podman rm sjvaircom_web_1`; from
  the main checkout, `podman-compose -p sjvaircom --profile web up -d --no-deps web`; confirm
  `regions/meta/` no longer has `name_template`. Message the coordinator the stack is back.
- [ ] **Step 6:** `git fetch`, rebase on `origin/release/5.0.0` if it moved, push, open a PR
  into `release/5.0.0` naming the matching sjvair.com PR (they go live together). Tell the
  coordinator the PR number.
- [ ] **Step 7: Stop.** Ask the user for: merging the sjvair.com PR, merging the sdk-js PR,
  and, separately, the `5.0.0-beta.4` release (which also ships #48). Nothing more until each
  yes. After a published beta, add its line to `CHANGELOG.md`'s betas paragraph (via the
  release flow in sdk-js `CLAUDE.md`) and send the version to the coordinator.
