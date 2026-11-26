"""Release candidate report for one component repository. Read-only.

    python3 scripts/release_candidate.py REPO [--ref origin/develop] [--tag vX.Y.Z]
                                         [--next-version X.Y.Z] [--date YYYY-MM-DD]
                                         [--json] [--strict]

For the local clone REPO it prints, to standard output only:

  1. the merged pull requests since the last version tag, grouped by prefix;
  2. the changes flagged as breaking;
  3. the version in every declared place, with a flag when they differ;
  4. a draft CHANGELOG entry and draft release notes.

It writes nothing. It runs only the git commands in READ_ONLY, it opens no file for writing,
and it makes no network request. Grouping is by prefix: the conventional prefix of the title,
of the squash subject, or of the branch name of a merge commit. Labels are not read, because
they need the GitHub API. Everything it says about breaking changes comes from the text of
commit messages, so a breaking change that is not written down is not flagged.

The suggested next version is a suggestion and the maintainer decides the version.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

# The only git subcommands this script runs. None of them writes to the repository.
READ_ONLY = frozenset({"log", "tag", "show", "ls-tree", "rev-parse", "remote", "merge-base"})

PREFIXES = (
    "feat",
    "fix",
    "docs",
    "chore",
    "ci",
    "test",
    "build",
    "perf",
    "refactor",
    "style",
    "revert",
    "deps",
    "design",
    "release",
)
CHANGELOG_SECTIONS = {
    "feat": "Added",
    "fix": "Fixed",
    "perf": "Changed",
    "refactor": "Changed",
    "revert": "Changed",
    "other": "Changed",
}
MAINTENANCE = ("docs", "chore", "ci", "test", "build", "style", "deps", "design", "release")
BRANCH_PREFIX = {"dependabot": "deps", "feature": "feat", "hotfix": "fix", "bugfix": "fix"}
VERSION_TAG = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")
TITLE = re.compile(r"^(?P<type>[a-z]+)(\([^)]*\))?(?P<bang>!)?:\s*(?P<text>.+)$")
MERGE = re.compile(r"^Merge pull request #(?P<pr>\d+) from (?P<owner>[^/\s]+)/(?P<branch>\S+)")
SQUASH_PR = re.compile(r"\(#(?P<pr>\d+)\)\s*$")
BREAKING_WORDS = re.compile(r"behaviou?r change|BREAKING CHANGE", re.IGNORECASE)


class GitError(RuntimeError):
    pass


def git(repo: Path, *args: str) -> str:
    """Run one read-only git command in `repo` and return its standard output."""
    if args[0] not in READ_ONLY:
        raise GitError(f"refusing to run `git {args[0]}`: not a read-only command")
    done = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    if done.returncode != 0:
        raise GitError(f"git {' '.join(args)}: {done.stderr.strip()}")
    return done.stdout


@dataclass
class Change:
    sha: str
    pr: int | None
    kind: str
    title: str
    breaking: bool = False
    reasons: list[str] = field(default_factory=list)


@dataclass
class Place:
    path: str
    line: int
    value: str


def version_tags(repo: Path) -> list[str]:
    tags = [t for t in git(repo, "tag").split() if VERSION_TAG.match(t)]
    return sorted(tags, key=lambda t: tuple(int(x) for x in VERSION_TAG.match(t).groups()))


def last_tag(repo: Path) -> str:
    tags = version_tags(repo)
    if not tags:
        raise GitError("no version tag (vX.Y.Z) found")
    return tags[-1]


def tag_reachable(repo: Path, tag: str, ref: str) -> bool:
    """True if the tag's commit is an ancestor of `ref`. After squash merges it often is not."""
    base = git(repo, "merge-base", tag, ref).strip()
    return base == git(repo, "rev-parse", f"{tag}^{{commit}}").strip()


def classify(subject: str, body: str) -> tuple[int | None, str, str, bool]:
    """Return (pr number, kind, title, breaking-by-prefix) for one first-parent commit."""
    merge = MERGE.match(subject)
    if merge:
        title = body.strip().splitlines()[0] if body.strip() else merge["branch"]
        pr = int(merge["pr"])
        branch_kind = merge["branch"].split("/", 1)[0].lower()
    else:
        title, pr, branch_kind = subject, None, ""
        squash = SQUASH_PR.search(subject)
        if squash:
            pr = int(squash["pr"])
            title = subject[: squash.start()].rstrip()
    match = TITLE.match(title)
    if match and match["type"] in PREFIXES:
        return pr, match["type"], match["text"], bool(match["bang"])
    kind = BRANCH_PREFIX.get(branch_kind, branch_kind)
    return pr, kind if kind in PREFIXES else "other", title, False


def changes_since(repo: Path, tag: str, ref: str) -> list[Change]:
    raw = git(repo, "log", "--first-parent", "--format=%H%x1f%s%x1f%b%x1e", f"{tag}..{ref}")
    out = []
    for record in raw.split("\x1e"):
        record = record.strip("\n")
        if not record.strip():
            continue
        sha, subject, body = (record.split("\x1f") + ["", ""])[:3]
        pr, kind, title, bang = classify(subject, body)
        reasons = []
        if bang:
            reasons.append("a `!` after the type")
        if BREAKING_WORDS.search(subject + "\n" + body):
            reasons.append("the words 'behaviour change' or 'BREAKING CHANGE'")
        out.append(Change(sha[:7], pr, kind, title, bool(reasons), reasons))
    return out


def group(changes: list[Change]) -> dict[str, list[Change]]:
    grouped: dict[str, list[Change]] = {}
    for change in changes:
        grouped.setdefault(change.kind, []).append(change)
    return dict(sorted(grouped.items()))


def _names(repo: Path, ref: str) -> list[str]:
    return git(repo, "ls-tree", "-r", "--name-only", ref).splitlines()


def declared_versions(repo: Path, ref: str) -> list[Place]:
    """The version in every place this script knows how to read, at `ref`."""
    places: list[Place] = []
    for path in _names(repo, ref):
        name = path.rsplit("/", 1)[-1]
        if "node_modules/" in path or path.count("/") > 2:
            continue
        reader = None
        if name == "pyproject.toml":
            reader = re.compile(r'^version\s*=\s*"([^"]+)"')
        elif name in ("package.json", "server.json"):
            reader = re.compile(r'^\s*"version"\s*:\s*"([^"]+)"')
        elif name == "__init__.py":
            reader = re.compile(r'^__version__\s*=\s*["\']([^"\']+)["\']')
        elif name == "Dockerfile":
            reader = re.compile(r"^ARG VERSION=(\S+)")
        if reader is None:
            continue
        for number, line in enumerate(git(repo, "show", f"{ref}:{path}").splitlines(), start=1):
            hit = reader.match(line)
            if hit:
                places.append(Place(path, number, hit.group(1)))
                if name in ("pyproject.toml", "package.json"):
                    break  # the first match is the project's own version
    return places


def suggest_version(tag: str, changes: list[Change]) -> str:
    major, minor, patch = (int(x) for x in VERSION_TAG.match(tag).groups())
    breaking = any(c.breaking for c in changes)
    feature = any(c.kind == "feat" for c in changes)
    if major == 0:
        return f"0.{minor + 1}.0" if breaking or feature else f"0.{minor}.{patch + 1}"
    if breaking:
        return f"{major + 1}.0.0"
    return f"{major}.{minor + 1}.0" if feature else f"{major}.{minor}.{patch + 1}"


def _line(change: Change) -> str:
    return f"- {change.title}" + (f" (#{change.pr})" if change.pr else "")


def changelog_entry(grouped: dict[str, list[Change]], version: str, date: str) -> str:
    sections: dict[str, list[str]] = {}
    for kind, items in grouped.items():
        title = CHANGELOG_SECTIONS.get(kind)
        if title:
            sections.setdefault(title, []).extend(_line(c) for c in items)
    lines = [f"## [{version}] - {date}", ""]
    for title in ("Added", "Changed", "Fixed"):
        if title in sections:
            lines += [f"### {title}", "", *sections[title], ""]
    if len(lines) == 2:
        lines += ["No user-facing change found in the commit messages.", ""]
    return "\n".join(lines).rstrip("\n") + "\n"


def release_notes(
    grouped: dict[str, list[Change]],
    breaking: list[Change],
    version: str,
    tag: str,
    compare: str,
) -> str:
    pre = version.startswith("0.")
    lines = [f"# {version}" + (" (pre-release)" if pre else ""), ""]
    for title, kinds in (("Added", ("feat",)), ("Fixed", ("fix",))):
        items = [c for kind in kinds for c in grouped.get(kind, [])]
        if items:
            lines += [f"## {title}", "", *[_line(c) for c in items], ""]
    other = [c for kind in ("perf", "refactor", "revert", "other") for c in grouped.get(kind, [])]
    if other:
        lines += ["## Changed", "", *[_line(c) for c in other], ""]
    lines += ["## Breaking changes", ""]
    lines += [_line(c) for c in breaking] or [
        "None found in the commit messages (a text check only)."
    ]
    maintenance = sum(len(grouped.get(kind, [])) for kind in MAINTENANCE)
    lines += [
        "",
        f"Also {maintenance} maintenance changes (documentation, CI, tests, dependencies).",
    ]
    if compare:
        lines += ["", f"Full list: {compare}"]
    return "\n".join(lines) + "\n"


def compare_url(repo: Path, tag: str, version: str) -> str:
    try:
        url = git(repo, "remote", "get-url", "origin").strip()
    except GitError:
        return ""
    hit = re.search(r"github\.com[:/](?P<slug>[^/]+/[^/.]+)", url)
    return f"https://github.com/{hit['slug']}/compare/{tag}...v{version}" if hit else ""


def build(repo: Path, ref: str, tag: str | None, next_version: str | None, date: str) -> dict:
    tag = tag or last_tag(repo)
    changes = changes_since(repo, tag, ref)
    grouped = group(changes)
    breaking = [c for c in changes if c.breaking]
    places = declared_versions(repo, ref)
    values = sorted({p.value for p in places})
    tag_version = tag[1:]
    flags = []
    if len(values) > 1:
        flags.append("the declared versions differ from each other: " + ", ".join(values))
    if values and tag_version not in values:
        flags.append(f"no declared version equals the last tag ({tag_version})")
    if values == [tag_version]:
        flags.append(
            "every declared version equals the last tag: no version bump has been made yet"
        )
    if not tag_reachable(repo, tag, ref):
        flags.append(
            f"{tag} is not an ancestor of {ref} (squash merges make main and develop diverge): "
            "changes already released in the tag can be listed again. Compare against main too"
        )
    if not changes:
        flags.append("no change since the last tag")
    unlabelled = [c for c in changes if c.pr is None]
    if unlabelled:
        flags.append(f"{len(unlabelled)} change(s) have no pull request number (direct commits)")
    suggested = suggest_version(tag, changes)
    version = next_version or suggested
    return {
        "repo": str(repo),
        "ref": ref,
        "last_tag": tag,
        "count": len(changes),
        "suggested_next_version": suggested,
        "version_used": version,
        "grouped": {k: [asdict(c) for c in v] for k, v in grouped.items()},
        "breaking": [asdict(c) for c in breaking],
        "declared_versions": [asdict(p) for p in places],
        "flags": flags,
        "changelog": changelog_entry(grouped, version, date),
        "release_notes": release_notes(
            grouped, breaking, version, tag, compare_url(repo, tag, version)
        ),
    }


def render(report: dict) -> str:
    out = [
        f"Release candidate report: {report['repo']} at {report['ref']}",
        f"Last tag: {report['last_tag']}    changes since: {report['count']}",
        "",
    ]
    out.append("1. Merged pull requests since the tag, by prefix")
    for kind, items in report["grouped"].items():
        out.append(f"  {kind} ({len(items)})")
        out += [
            f"    - {c['title']}" + (f" (#{c['pr']})" if c["pr"] else " (no PR number)")
            for c in items
        ]
    out += ["", "2. Breaking changes (from commit message text only)"]
    out += [f"  - {c['title']}  [{'; '.join(c['reasons'])}]" for c in report["breaking"]] or [
        "  none flagged"
    ]
    out += ["", "3. Declared versions"]
    out += [f"  {p['path']}:{p['line']}  {p['value']}" for p in report["declared_versions"]] or [
        "  none found"
    ]
    out += [f"  FLAG: {flag}" for flag in report["flags"]]
    out += [
        "",
        (
            f"4. Suggested next version: {report['suggested_next_version']} (a suggestion; "
            f"the maintainer decides). Drafts below use {report['version_used']}."
        ),
        "",
        "Draft CHANGELOG entry",
        "---",
        report["changelog"],
        "---",
        "",
        "Draft release notes",
        "---",
        report["release_notes"],
        "---",
    ]
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only release candidate report.")
    parser.add_argument("repo", type=Path)
    parser.add_argument("--ref", default="origin/develop")
    parser.add_argument("--tag", help="the tag to compare from (default: the highest vX.Y.Z)")
    parser.add_argument("--next-version", help="version for the drafts (default: the suggestion)")
    parser.add_argument("--date", default=dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d"))
    parser.add_argument("--json", action="store_true", help="print JSON instead of text")
    parser.add_argument("--strict", action="store_true", help="exit 1 if any flag is raised")
    args = parser.parse_args(argv)
    try:
        report = build(args.repo, args.ref, args.tag, args.next_version, args.date)
    except GitError as exc:
        print(f"release_candidate: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(report, indent=2) if args.json else render(report))
    return 1 if args.strict and report["flags"] else 0


if __name__ == "__main__":
    sys.exit(main())
