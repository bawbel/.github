# REL-1: release readiness per component

Report, 2026-11-26, for [#23](https://github.com/bawbel/.github/issues/23). Report only: nothing was tagged,
published or posted, and nothing is decided. It covers scanner, gate, integrations and bawbel-mcp, from
`origin/develop` and `origin/main` of each repository, with the live registries queried read-only on
2026-11-26 at 13:29 UTC.

Every cell carries a tag. **VERIFIED**: a command was run, on the date above. **SOURCED**: read from the file and
line named, at the commit named. **UNVERIFIED**: stated without either, and why.

Commits read: scanner `develop` 0ddf560 and `main` dc3bbcd; gate `develop` b9d76a9 and `main` 78b8c6d;
integrations `develop` 9e6efc1 and `main` d3a0d4b; bawbel-mcp `develop` 332f69c and `main` 40a5c3c.

## The table

| | scanner | gate | integrations | bawbel-mcp |
|---|---|---|---|---|
| **Where the version is declared** (develop and main agree unless said) | `pyproject.toml:9` 1.3.0, `scanner/__init__.py:17` 1.3.0, `Dockerfile:27` and `:104` (`ARG VERSION`), README.md:644 (`bawbel-scanner==1.3.0`), `docs/VERIFYING-RELEASES.md:19-39`. Stale: `scanner/engines/sandbox/harness.py:29` 1.2.0, `docs/guides/publishing.md:20,27` 1.2.0, `scripts/setup.sh:207` and `scripts/test_all.sh:156` assert 1.2.3 | `pyproject.toml:7` **0.1.1**, `src/bawbel_gate/__init__.py:3` **0.1.0**. ARCHITECTURE.md:34,70,220 and README.md:37 say 0.1.0 | `pyproject.toml:7` **1.1.1**, `vscode/package.json:5` **1.1.0**. README.md:18 and :126 say 1.1.1. Action pins name `v1.1.0` (README.md:53, RELEASING.md:27, `examples/basic.yml:10`) | `pyproject.toml:7` 1.1.0, `server.json:6` and `:16` 1.1.0 |
| **Last tag** | `v1.3.0` at 9292c2c, 2026-06-28, lightweight | `v0.1.0` at 1ba66c2, 2026-10-11, lightweight | `v1.1.0` at ee77de3, 2026-04-26, lightweight. Also `v1.0.1` and a `v1` tag | `v1.1.0` at d0b2272, 2026-05-24, lightweight |
| **GitHub release** | v1.3.0, 2026-06-27, not a pre-release | v0.1.0, 2026-10-11, **pre-release** | v1.1.0, 2026-04-26 | v1.1.0, 2026-05-23 |
| **Live registry** | PyPI `bawbel-scanner` **1.3.0**, uploaded 2026-06-27 20:03 UTC, 2 files | PyPI `bawbel-gate` **0.1.0**, uploaded 2026-10-11 14:01 UTC, 2 files, the only version | not on PyPI (no project `bawbel-integrations`). VS Code marketplace `bawbel.bawbel-scanner` **1.1.0**, updated 2026-04-26 15:59 UTC | PyPI `bawbel-mcp` **1.1.0**, uploaded 2026-05-23 17:31 UTC, 2 files |
| **Provenance on the registry** | the PyPI attestation endpoint answered HTTP 200 for the 1.3.0 wheel | HTTP 200 for the 0.1.0 wheel | not applicable to PyPI | HTTP 200 for the 1.1.0 wheel |
| **Commits since the tag** | develop 61, main 28 | develop 133, main 143 | develop 54, main 16 | develop 18, main 11 |
| **CHANGELOG** | Keep a Changelog 1.0.0, `## [Unreleased]` at line 7 | Keep a Changelog 1.1.0, `## [Unreleased]` at line 12 | **none** | Keep a Changelog 1.0.0, `## [Unreleased]` at line 9 |
| **Publish workflow** | `.github/workflows/publish.yml`, on a published release or a manual dispatch. A `pypi` environment with manual approval (comment at line 6), `id-token: write` (line 115), `pypa/gh-action-pypi-publish` pinned by SHA at 1.14.3 (line 125). No attestation setting in the file | `publish.yml`, on a published release. `environment` and `id-token: write` in two jobs (lines 54 to 83), the same action pinned at 1.14.3. A comment at line 75 says the `pypi` environment must require reviewers. No attestation setting in the file | **none.** Workflows on `main`: `action-local`, `action-smoke`, `gate-lint-local`, `pins`. How the tag and the marketplace version were published is not in the repository | `publish.yml`, on a published release or a manual dispatch. `environment` and `id-token: write` (lines 104 to 108). A second block is commented out (lines 74 to 91) |
| **`main` has content `develop` lacks** | **no.** A trial merge of `main` into `develop` changes nothing (`git merge-tree`). One commit is on `main` only, by graph | **no.** Same result. 10 commits are on `main` only, by graph, and `develop` has none that `main` lacks | **yes.** A trial merge changes `develop`, with 6 conflicting files: `.github/workflows/pins.yml`, `.pre-commit-hooks.yaml`, `README.md`, `RELEASING.md`, `bawbel_hooks/README.md`, `vscode/README.md`. `main` has 3 commits `develop` lacks (#68, #77, #78, 2026-11-21) | **yes.** A trial merge changes `develop` with no conflict. 3 files differ: `publish.yml`, `self-scan.yml`, `pyproject.toml`. `main` has 5 commits `develop` lacks (#19, #24, #25, #28, #31) |
| **Runs on pull requests** | `ci.yml` (jobs `lint`, `test`, `test-integration`, `docker`, `self-scan`, `audit`, `counts`), `code-scan.yml`, `doc-links.yml`, `pr-review.yml` | `ci.yml` (jobs `test`, `lint`, `wheel`, `typecheck`), `code-scan`, `dependency-scan`, `secret-scan`, `contributor-smoke` | `action-local`, `action-smoke`, `gate-lint-local`, `pins`. Job names were not read | `tests.yml` (job `test`), `self-scan.yml` |

Sources for the table: `git show` and `git grep` on the commits above; `git rev-list --count`; `git merge-tree --write-tree`;
`gh api repos/bawbel/<repo>/releases`; `https://pypi.org/pypi/<name>/json`;
`https://pypi.org/integrity/<name>/<version>/<file>/provenance` (read as HTTP status only);
`https://marketplace.visualstudio.com/_apis/public/gallery/extensionquery`. All VERIFIED on 2026-11-26.

## What looks wrong

1. **gate: the code says 0.1.0 and the metadata says 0.1.1, on both branches.** `pyproject.toml:7` and
   `src/bawbel_gate/__init__.py:3` disagree, and PyPI has only 0.1.0. A release would ship a version that the
   package does not report the same way twice. SOURCED.
2. **integrations: three versions.** `pyproject.toml` 1.1.1, the VS Code extension 1.1.0, the tag 1.1.0. The README says
   1.1.1 is released and the marketplace has 1.1.0. It has no CHANGELOG, no publish workflow and no PyPI project, and `main`
   and `develop` conflict in 6 files. This component cannot run the train as it is. SOURCED and VERIFIED.
3. **bawbel-mcp: a stray file named `e HEAD` is at the root of both branches.** SOURCED: it holds pasted `git log` output.
   `main` also differs from `develop` in three files.
4. **scanner: scripts that assert an old version.** `scripts/setup.sh:207` and `scripts/test_all.sh:156` check for 1.2.3, and
   `harness.py:29` and the publishing guide say 1.2.0. I did not run the scripts. SOURCED.
5. **All tags are lightweight.** A lightweight tag cannot carry a signature of its own. SOURCED, `git cat-file -t`.
6. **Three of four components publish through the PyPI trusted-publishing action** with a protected environment, and
   the registry shows an attestation for the latest wheel of each. VERIFIED by status code only: I did not fetch or
   verify the attestation, which is GATE-C5 and SCAN-C5. The workflows set no attestation option, so why the registry has
   one is UNVERIFIED.
7. **The runbook says `bawbel/.github` has no `develop`.** It has one. `origin/develop` is 3 commits behind `origin/main`.
   REL-2's pull request targets `develop`.
8. **Required checks were not read.** This report lists the workflows that run on pull requests. Whether a branch rule makes
   any of them required needs administrator access to the rules, which this session did not use. UNVERIFIED.

## What this means for the train

- **scanner** has an Unreleased section, a trusted-publishing workflow and a registry that matches `main`. Its `main` and
  `develop` agree in content. It has 61 commits since the tag to review for a candidate.
- **gate** needs the 0.1.0 and 0.1.1 mismatch settled before anything is tagged, and has no content gap between branches.
- **integrations** and **bawbel-mcp** need their `main` and `develop` brought together first. integrations also needs a
  CHANGELOG, one version, and a publish path (INT-C7).
- Whether a component ships in a given month is the maintainer's call. This report states facts only.

## Not done

- No required-checks or branch-rule read (item 8). The VS Code marketplace listing was read through its public query
  endpoint, and the publishing path of the extension is not in the repository.
- The attestations were not downloaded or verified. No install of any released artifact was run: that is REL-4.
- Hub and Registry are not in the train yet and are not covered.

## Not changed

No file in any component repository was changed, and nothing was written to any registry.
