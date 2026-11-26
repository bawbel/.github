"""Tests for scripts/release_candidate.py. A fixture repository is built in a temporary directory.
No network, and the script under test must write nothing."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location(
    "release_candidate", ROOT / "scripts/release_candidate.py"
)
rc = importlib.util.module_from_spec(SPEC)
sys.modules["release_candidate"] = rc
SPEC.loader.exec_module(rc)

ENV = {
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.invalid",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.invalid",
    "GIT_AUTHOR_DATE": "2026-11-01T00:00:00Z",
    "GIT_COMMITTER_DATE": "2026-11-01T00:00:00Z",
    "HOME": "/nonexistent",
    "PATH": "/usr/bin:/bin:/usr/local/bin",
}


def sh(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
        env=ENV,
    ).stdout


def commit(repo: Path, message: str, files: dict[str, str] | None = None) -> None:
    for name, text in (files or {"f.txt": message}).items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    sh(repo, "add", "-A")
    sh(repo, "commit", "-q", "-m", message)


def merge(repo: Path, branch: str, number: int, title: str) -> None:
    sh(repo, "checkout", "-q", "-b", branch)
    commit(repo, title, {f"{branch.replace('/', '_')}.txt": title})
    sh(repo, "checkout", "-q", "main")
    sh(
        repo,
        "merge",
        "-q",
        "--no-ff",
        branch,
        "-m",
        f"Merge pull request #{number} from o/{branch}",
        "-m",
        title,
    )


def versions(py: str, init: str, server: str, ext: str) -> dict[str, str]:
    return {
        "pyproject.toml": f'[project]\nname = "x"\nversion = "{py}"\n',
        "pkg/__init__.py": f'__version__ = "{init}"\n',
        "server.json": json.dumps({"name": "x", "version": server}, indent=2) + "\n",
        "vscode/package.json": json.dumps({"name": "x", "version": ext}, indent=2) + "\n",
    }


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    r = tmp_path / "fixture"
    r.mkdir()
    sh(r, "init", "-q", "-b", "main")
    commit(r, "release: 0.1.0", versions("0.1.0", "0.1.0", "0.1.0", "0.1.0"))
    sh(r, "tag", "v0.1.0")
    commit(r, "feat: add the probe tool (#2)")
    commit(r, "fix: stop a crash on empty input (#3)")
    commit(r, "docs: explain the config (#4)")
    commit(r, "feat!: drop the old flag (#5)")
    merge(r, "fix/6-timeout", 6, "fix: raise the default timeout")
    merge(r, "docs/7-readme", 7, "README wording")
    commit(r, "chore: tidy")
    commit(r, "ci: pin the actions (#8)")
    commit(r, "refactor: rename a helper\n\nBehaviour change: the helper now returns None.")
    commit(r, "bump", versions("0.2.0", "0.1.0", "0.2.0", "0.1.0"))
    return r


def test_the_last_tag_is_the_highest_version_tag(repo):
    sh(repo, "tag", "v0.0.9")
    sh(repo, "tag", "not-a-version")
    sh(repo, "tag", "v0.10.0")
    sh(repo, "tag", "v0.9.0")
    assert rc.last_tag(repo) == "v0.10.0"


def test_changes_are_grouped_by_prefix_from_squash_merge_and_branch_forms(repo):
    report = rc.build(repo, "main", None, None, "2026-12-01")
    grouped = report["grouped"]
    assert [c["pr"] for c in grouped["feat"]] == [5, 2]
    assert [c["title"] for c in grouped["fix"]] == [
        "raise the default timeout",
        "stop a crash on empty input",
    ]
    assert grouped["fix"][0]["pr"] == 6, "a merge commit takes its number from the merge message"
    assert {c["pr"] for c in grouped["docs"]} == {4, 7}, "a branch prefix groups a title with none"
    assert [c["title"] for c in grouped["ci"]] == ["pin the actions"]


def test_a_change_with_no_pull_request_number_is_listed_and_flagged(repo):
    report = rc.build(repo, "main", None, None, "2026-12-01")
    assert any("no pull request number" in flag for flag in report["flags"])
    assert any(c["pr"] is None for items in report["grouped"].values() for c in items)


def test_breaking_changes_are_flagged_from_the_message_text_only(repo):
    report = rc.build(repo, "main", None, None, "2026-12-01")
    titles = sorted(c["title"] for c in report["breaking"])
    assert titles == ["drop the old flag", "rename a helper"]
    reasons = {c["title"]: c["reasons"] for c in report["breaking"]}
    assert any("`!`" in r for r in reasons["drop the old flag"])
    assert any("behaviour change" in r for r in reasons["rename a helper"])


def test_the_version_in_every_declared_place_is_read_and_a_mismatch_is_flagged(repo):
    report = rc.build(repo, "main", None, None, "2026-12-01")
    found = {(p["path"], p["value"]) for p in report["declared_versions"]}
    assert found == {
        ("pyproject.toml", "0.2.0"),
        ("pkg/__init__.py", "0.1.0"),
        ("server.json", "0.2.0"),
        ("vscode/package.json", "0.1.0"),
    }
    assert any("differ from each other" in flag for flag in report["flags"])


def test_agreeing_versions_equal_to_the_tag_say_no_bump_has_been_made(tmp_path):
    r = tmp_path / "r"
    r.mkdir()
    sh(r, "init", "-q", "-b", "main")
    commit(r, "release: 1.0.0", versions("1.0.0", "1.0.0", "1.0.0", "1.0.0"))
    sh(r, "tag", "v1.0.0")
    commit(r, "fix: one (#1)")
    flags = rc.build(r, "main", None, None, "2026-12-01")["flags"]
    assert any("no version bump" in flag for flag in flags)
    assert not any("differ from each other" in flag for flag in flags)


def test_the_suggested_version_follows_semver_and_is_labelled_a_suggestion(repo):
    report = rc.build(repo, "main", None, None, "2026-12-01")
    assert report["suggested_next_version"] == "0.2.0", (
        "0.x: a feature or a breaking change bumps the minor"
    )
    assert "a suggestion" in rc.render(report)
    assert rc.suggest_version("v1.4.2", [rc.Change("a", 1, "fix", "x")]) == "1.4.3"
    assert rc.suggest_version("v1.4.2", [rc.Change("a", 1, "feat", "x")]) == "1.5.0"
    assert rc.suggest_version("v1.4.2", [rc.Change("a", 1, "fix", "x", True)]) == "2.0.0"
    assert rc.suggest_version("v0.3.1", [rc.Change("a", 1, "fix", "x")]) == "0.3.2"


def test_the_draft_changelog_has_added_changed_and_fixed_and_leaves_out_maintenance(repo):
    entry = rc.build(repo, "main", None, "0.2.0", "2026-12-01")["changelog"]
    assert entry.startswith("## [0.2.0] - 2026-12-01\n")
    added = entry.split("### Added\n\n")[1].split("\n\n")[0].splitlines()
    assert added == ["- drop the old flag (#5)", "- add the probe tool (#2)"]
    assert "- raise the default timeout (#6)" in entry and "### Fixed" in entry
    assert "### Changed" in entry and "rename a helper" in entry
    assert "explain the config" not in entry and "pin the actions" not in entry


def test_the_draft_release_notes_say_pre_release_for_0_x_and_list_breaking_changes(repo):
    notes = rc.build(repo, "main", None, "0.2.0", "2026-12-01")["release_notes"]
    assert notes.startswith("# 0.2.0 (pre-release)")
    breaking = notes.split("## Breaking changes\n\n")[1].split("\n\n")[0].splitlines()
    assert breaking == ["- rename a helper", "- drop the old flag (#5)"]
    assert "maintenance changes" in notes


def test_a_one_point_oh_release_is_not_called_pre_release(repo):
    notes = rc.build(repo, "main", None, "1.0.0", "2026-12-01")["release_notes"]
    assert notes.startswith("# 1.0.0\n")


def test_it_writes_nothing_to_the_repository(repo):
    before_status = sh(repo, "status", "--porcelain")
    before_refs = sh(repo, "for-each-ref")
    before_files = sorted(p.name for p in repo.rglob("*") if ".git" not in p.parts)
    before_git = sorted(
        str(p.relative_to(repo))
        for p in (repo / ".git").rglob("*")
        if p.is_file() and p.name not in ("index",) and "logs" not in p.parts
    )
    rc.main([str(repo), "--ref", "main"])
    assert sh(repo, "status", "--porcelain") == before_status
    assert sh(repo, "for-each-ref") == before_refs
    assert sorted(p.name for p in repo.rglob("*") if ".git" not in p.parts) == before_files
    after_git = sorted(
        str(p.relative_to(repo))
        for p in (repo / ".git").rglob("*")
        if p.is_file() and p.name not in ("index",) and "logs" not in p.parts
    )
    assert after_git == before_git


def test_it_refuses_any_git_command_that_is_not_read_only(repo):
    for command in ("commit", "tag-delete", "push", "checkout", "merge", "reset", "branch"):
        with pytest.raises(rc.GitError):
            rc.git(repo, command)


def test_it_never_opens_a_file_for_writing():
    source = (ROOT / "scripts/release_candidate.py").read_text(encoding="utf-8")
    for needle in ("write_text", "open(", ".write(", "mkdir", "unlink", "shutil"):
        assert needle not in source


def test_json_output_and_strict_exit_code(repo, capsys):
    assert rc.main([str(repo), "--ref", "main", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["last_tag"] == "v0.1.0" and data["flags"]
    assert rc.main([str(repo), "--ref", "main", "--strict"]) == 1


def test_a_repository_with_no_version_tag_is_a_usage_error(tmp_path, capsys):
    r = tmp_path / "none"
    r.mkdir()
    sh(r, "init", "-q", "-b", "main")
    commit(r, "first")
    assert rc.main([str(r), "--ref", "main"]) == 2
    assert "no version tag" in capsys.readouterr().err


def test_a_tag_that_is_not_an_ancestor_of_the_ref_is_flagged(tmp_path):
    r = tmp_path / "diverged"
    r.mkdir()
    sh(r, "init", "-q", "-b", "main")
    commit(r, "base", versions("1.0.0", "1.0.0", "1.0.0", "1.0.0"))
    sh(r, "checkout", "-q", "-b", "release")
    commit(r, "release: 1.0.0 (#1)")
    sh(r, "tag", "v1.0.0")
    sh(r, "checkout", "-q", "main")
    commit(r, "fix: a thing (#2)")
    flags = rc.build(r, "main", None, None, "2026-12-01")["flags"]
    assert any("is not an ancestor" in flag for flag in flags)


def test_a_tag_that_is_an_ancestor_is_not_flagged(repo):
    flags = rc.build(repo, "main", None, None, "2026-12-01")["flags"]
    assert not any("is not an ancestor" in flag for flag in flags)
