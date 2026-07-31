# GitHub Actions CI + Branch Protection

## Purpose

Run the pytest suite automatically on every push and pull request, and block
merges into `main` until that check passes.

## Context

- Tests are fully dockerized today: `docker compose run --rm test pytest`
  (see CLAUDE.md). The `test` profile in `docker-compose.yml` builds a `test`
  target image and depends on `db` (postgis), `queue` (redis), and `cache`
  (memcached) healthchecks.
- `camp.settings.test` runs Huey in immediate/synchronous mode and swaps in
  locmem cache — no external services beyond Postgres/Redis/Memcached are
  required for tests.
- `.env.test` is gitignored (confirmed via `git ls-files`) and contains only
  dummy/test-only values: a fake `SECRET_KEY`, an in-network `DATABASE_URL`
  (`db:5432`), and PurpleAir test keys already checked into no tracked file.
  None of these are production credentials.
- There is currently no `.github/workflows/` directory and no branch
  protection configured on `main` (confirmed via `gh api
  repos/SJVAir/sjvair.com/branches/main/protection` → 404). The repo owner
  has `admin` permission on the repo, sufficient to configure branch
  protection via `gh api`.

## Design

### CI workflow: `.github/workflows/test.yml`

- Triggers: `push` (any branch) and `pull_request`.
- Single job named `test`, runs on `ubuntu-latest`.
- Steps:
  1. `actions/checkout`
  2. Write `.env` and `.env.test` files inline in the workflow (heredoc/echo
     steps), using the same non-sensitive values already present in the
     local gitignored `.env.test` and `.env.template`. Nothing sensitive is
     introduced — these are dev/test-only dummy values, not secrets.
  3. Enable Docker Buildx and layer caching via `actions/cache` (keyed on
     `Dockerfile`/`requirements/*.txt` hashes) so image builds are fast on
     repeat runs.
  4. `docker compose --profile test build test`
  5. `docker compose --profile test up -d db queue cache` and wait for the
     existing healthchecks (compose already defines these).
  6. `docker compose --profile test run --rm test pytest`
  7. Always tear down with `docker compose down -v` in a final step (even on
     failure), to avoid leaking containers between runs.
- The job name `test` is what branch protection will require as a status
  check context.

### Branch protection on `main`

Configured once via:

```
gh api -X PUT repos/SJVAir/sjvair.com/branches/main/protection \
  -f required_status_checks.strict=false \
  -f 'required_status_checks.contexts[]=test' \
  -F enforce_admins=false \
  ...
```

(exact flags finalized during implementation; classic branch protection API,
not the newer rulesets API, since it's simpler for a single required check).

- `required_status_checks.contexts`: `["test"]` — must match the CI job name
  exactly.
- `strict: false` — do not require the branch to be up-to-date with `main`
  before merging (keeps things simple; can be tightened later if needed).
- `enforce_admins: false` — repo admins can still push directly to `main` in
  an emergency; this only blocks PRs that don't have a passing `test` check.
- No changes to required review counts — out of scope, not requested.

## Out of scope

Linting, coverage reporting, multi-version Python test matrix, deploy
workflows. None of this was requested; adding it now would be scope creep.

## Testing / Verification

- Push a branch and open a PR; confirm the `test` check appears and runs to
  completion (pass or fail matches local `docker compose run --rm test
  pytest` result).
- Confirm the PR merge button is disabled while the check is pending/failing
  and enabled once it passes.
- Confirm a direct push to `main` still succeeds (admin bypass) as a sanity
  check that `enforce_admins: false` took effect.
