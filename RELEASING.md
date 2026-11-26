# Releasing: the monthly release train

**Status: DRAFT, for the maintainer to review.** The steps that tag, publish or post are marked
**HUMAN-ONLY**. **Every publish step is marked TODO until GATE-C2 merges**, because its exact commands come from
GATE-C2 (one version everywhere, tagged, published, checked). Nothing in this file has been used for a real release.

An executor prepares: reports, pull requests, checks and fact sheets. The maintainer tags, publishes and posts.

## Shape of the train

- **Cadence (proposed, not decided):** the first Thursday of each month, called D below. Rehearsal on Thursday 3 December
  2026, first real train on Thursday 7 January 2027, then Thursday 4 February 2027.
- **Components:** scanner, gate, integrations and bawbel-mcp. The Hub and the Registry join when each has a first release.
- **One version per component, not one forced version.** A component releases only if it has a user-facing change since
  its last tag. A month with nothing to ship is skipped (proposed, not decided), and nothing is posted. No filler releases.
- **Versioning:** Semantic Versioning. While a component is 0.x, release notes and posts say "pre-release".

## Prerequisites that are tracked elsewhere

GATE-1 (the first PyPI release of the gate), GATE-C2 (one version everywhere), GATE-C5 and SCAN-C5 (verify a release by
signed provenance), INT-C7 (build the extension file on a tag), and GATE-24 (resync `main` into `develop`). The train cannot
run end to end until GATE-C2 has merged. The rehearsal can run without publishing.

The first readiness check, with the state of each component on 2026-11-26, is the REL-1 report in
`docs/release-train/` (pull request #24, not merged at the time of writing).

## What the executor never does

Tag, publish, create a release, push to `main`, post anywhere, comment on a post, or decide. Those are the maintainer's.

## The calendar, as a checklist

`D` is release day. Each line says who does it.

### D-7

- [ ] **EXECUTOR.** Run the release candidate report for each component (REL-3), and publish it as an issue or a pull
      request comment for review. It lists merged pull requests since the last tag, flags breaking changes, checks that
      the version agrees in every place it is declared, and prints a draft CHANGELOG entry and draft release notes.
      It writes nothing to any repository.
- [ ] **HUMAN-ONLY.** Freeze: from now until the release only fixes and documentation merge to `develop`.

### D-7 to D-3

- [ ] **HUMAN-ONLY.** Read the report. Decide go or skip for each component. A skipped component gets no post.

### D-3

- [ ] **EXECUTOR.** For each component that is going, open a version bump and CHANGELOG pull request to `develop`, from
      the report. Draft pull requests only, with the version changed in every place the report lists.

### D-2

- [ ] **HUMAN-ONLY.** Review and merge those pull requests.
- [ ] **HUMAN-ONLY.** Promote `develop` to `main` with a merge commit. Never squash, because a squash makes `main` and
      `develop` diverge and every later promotion conflicts.

### D-1

- [ ] **EXECUTOR.** Re-check on `main`: the versions agree, the tests are green, and a clean virtual environment installs
      the built artifact and reports the expected version. Paste the output. Report anything that does not match.

### D (release day)

- [ ] **HUMAN-ONLY. TODO until GATE-C2 merges.** Tag the commit on `main`. The exact commands are not written yet.
- [ ] **HUMAN-ONLY. TODO until GATE-C2 merges.** Publish through the trusted-publishing workflow, approving the protected
      environment, and create the release. The exact commands are not written yet.
- [ ] **EXECUTOR.** After the release, the post-release check (REL-5): the live registry shows the new version, the
      install command runs in a clean environment with its output pasted, and the fact sheet is written (below).

### D+1 to D+5

- [ ] **HUMAN-ONLY.** Write and post, from the fact sheet, following the rules below. After posting, read the replies, and
      fix the fact sheet or the documentation if a reader is right.

## The fact sheet

One issue per component per release, titled "Release YYYY-MM post-release". It is the source for every post: every factual
sentence in a post must trace to a line in it. It holds the version and date, the registry page checked live, the install
command run in a clean environment with its output, the changes with pull request numbers, test and rule counts computed
by a command (the command shown), known limits, items that are unverified, and links a reader can check.

## Posting rules (HUMAN-ONLY)

- No pricing or commercial language. No em dashes. No word that claims a component is protected, accredited or
  independently reviewed.
- Numbers only from the fact sheet, with the command that produced them. State limits and what is unverified.
- Say that you maintain the project, and read the current rules of each site or subreddit on the day. If they bar project
  posts, skip that site that month.
- Posts are written and published by the maintainer. No scheduler, no automated reply, no automated like.
- A post lint script is planned (REL-6). **TODO: add the command here after the maintainer has read and approved the script.**

## Per component

The table of where each version is declared, the last tag and the registry state is in the REL-1 report. The facts that
matter for a release, as of 2026-11-26:

| Component | Before it can ship |
|---|---|
| scanner | Nothing found beyond the version strings in old scripts and guides, which the candidate report will list |
| gate | The version in `__init__.py` and in `pyproject.toml` differ (0.1.0 and 0.1.1). GATE-C2 settles that |
| integrations | `main` and `develop` conflict in six files, there is no CHANGELOG, no publish workflow, and the extension, the package and the tag carry different versions |
| bawbel-mcp | `main` and `develop` differ in three files, and a stray file named `e HEAD` is at the root |

## Open

- The cadence and the skip rule are proposals. The maintainer decides them.
- The commands for tagging and publishing are TODO. The first rehearsal (3 December) runs the train as pull requests only and
  publishes nothing.
