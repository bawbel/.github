# Claims register

Every number and phrase Bawbel publishes was true once. The ones that drifted had no owner
and no check. The register gives each claim one owner, one evidence check, and the list of
places it appears.

| File | Role |
|---|---|
| `claims/register.yaml` | One entry per claim |
| `scripts/verify_claims.py` | Runs every check, writes `claims/STATUS.md` |
| `claims/STATUS.md` | The last run. Generated, never edited by hand |

## Run it

```bash
pip install -r scripts/requirements-claims.txt
python scripts/verify_claims.py                                # clones sources, uses the network
python scripts/verify_claims.py --offline --workspace ../clones  # local clones only
```

`--workspace` is a directory with one clone per source name from `register.yaml`
(`ave`, `scanner`, `gate`, ...). Without it, sources are cloned shallow into a temporary
directory and deleted afterwards. The exit status is 1 when any claim fails.

Tests: `pip install pytest && python -m pytest tests`.

## Monthly review

`.github/workflows/claims-review.yml` runs on the first of each month, UTC, and can be started
by hand from the Actions tab. It runs `scripts/verify_claims.py` and opens an issue titled
`Claims review YYYY-MM`. The issue lists every FAIL claim and every UNVERIFIED claim by id,
with the whole `claims/STATUS.md` under a fold. It changes nothing in the repository, and it
does not open a second issue for a month that already has one.

A person closes each failing claim by fixing the surface or the register, as described under
"Change a claim". An UNVERIFIED claim is listed so it does not stay unverified in silence.

The workflow has no access to private repositories, so a claim that reads one, such as
`registry`, shows as UNVERIFIED in the issue. Run the verifier locally for those.

## Results

| Result | Meaning |
|---|---|
| PASS | The check ran completely, the measurement equals `expect`, and every listed surface states that value |
| FAIL | The measurement differs from `expect`, a surface states something else, or a forbidden phrase is present |
| UNVERIFIED | Some input could not be read: offline, a private repository, or a value the source cannot settle |

A check that cannot run is never PASS. When a claim has both a failure and a gap, FAIL wins,
and the gap is still listed under Details.

## Entry fields

```yaml
- id: C-01                 # never reused
  claim: AVE records published
  kind: number             # number | state | wording
  check: ave_published     # a function in CHECKS in scripts/verify_claims.py
  expect: 87               # null keeps the claim UNVERIFIED until someone sets it
  owner: maintainer
  params: {}               # passed to the check
  appears_in:              # where the claim is stated
    - {source: website, path: index.html, pattern: '(?i)\b(\d+) AVE records\b'}
  note: free text
```

- **number** and **state**: the check measures a value, and it must equal `expect`.
- **wording**: the check counts violations, such as forbidden phrases. Zero passes.
- **appears_in**: the first group of each `pattern` captures the stated number, as digits
  or a word up to twenty. Every match must equal `expect`. A pattern that matches nothing
  fails, because the claim moved or was removed and the register is out of date.

## Add a claim

1. Take the next free id.
2. Use an existing check, or add a function to `CHECKS`. A check reads files by parsing
   (AST, regex, `yaml.safe_load`). It never imports or runs code from a source. When an
   input is missing it raises `Unavailable`, which makes the claim UNVERIFIED.
3. List every surface that states the claim in `appears_in`.
4. Run the verifier and commit `claims/STATUS.md` in the same PR.

## Change a claim

When reality moves, for example new AVE records are published, the claim fails with
"measured X, register expects Y". Update `expect` in the same PR as the surfaces, or update
`expect` first and let the surface failures drive the follow-up PR in each repository.
Never change `expect` to match a surface without measuring.

## Retire a claim

Delete the entry and add a row to the table below. Ids are not reused.

| Id | Retired | Reason |
|---|---|---|
| none yet | | |

## Scope and limits

- Wording checks read documentation files in the public repositories: `.md`, `.html`,
  `.rst`, `.txt`, `package.json`, `pyproject.toml`. Stale-host checks read every tracked
  text file except `dist/`, `node_modules/`, lock files and binaries.
- Files in this repository that quote claims on purpose are excluded from every scan:
  `claims/`, `docs/CLAIMS.md`, `scripts/verify_claims.py`, `tests/`.
- The verifier reads repository sources, not served pages. A deployed site that differs
  from its repository is not caught.
- `bawbel-registry` is private. Without read access, C-14 is UNVERIFIED.
- Logos are detected by file name only, not by image content.

## Security

- No shell anywhere. Subprocess calls take fixed argument lists.
- Clones are `https://github.com/<org>/<repo>` only, shallow, with `GIT_ALLOW_PROTOCOL=https`
  and no interactive credential prompts.
- HTTP goes through `urllib` with a timeout, https only. `GITHUB_TOKEN`, if set, is sent to
  `api.github.com` only.
- C-10 installs `bawbel-gate` from PyPI into a throwaway virtual environment and runs
  `bawbel-gate --version`. That is the only place the verifier runs code it did not write.
