"""Tests for scripts/verify_claims.py. No network, no clones: sources are temp dirs."""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location("verify_claims", ROOT / "scripts/verify_claims.py")
vc = importlib.util.module_from_spec(SPEC)
sys.modules["verify_claims"] = vc  # dataclasses resolve annotations through it
SPEC.loader.exec_module(vc)


def make_ave(root: Path, count: int) -> Path:
    records = root / "ave" / "records"
    records.mkdir(parents=True)
    for i in range(1, count + 1):
        rid = f"AVE-2026-{i:05d}"
        (records / f"{rid}.json").write_text(
            json.dumps({"ave_id": rid, "detection_stage": "static_detection"})
        )
    return root / "ave"


def number_claim(**extra) -> dict:
    claim = {"id": "C-T", "claim": "test", "kind": "number", "check": "ave_published",
             "expect": 3}
    claim.update(extra)
    return claim


def test_missing_source_is_unverified_never_pass():
    ctx = vc.Context(sources={"ave": None}, reasons={"ave": "offline"})
    out = vc.evaluate(ctx, number_claim())
    assert out.status == vc.UNVERIFIED


def test_measurement_matching_expect_passes(tmp_path):
    ctx = vc.Context(sources={"ave": make_ave(tmp_path, 3)})
    assert vc.evaluate(ctx, number_claim()).status == vc.PASS


def test_measurement_drift_fails(tmp_path):
    ctx = vc.Context(sources={"ave": make_ave(tmp_path, 4)})
    out = vc.evaluate(ctx, number_claim())
    assert out.status == vc.FAIL
    assert "measured 4" in out.problems[0]


def test_surface_stating_another_number_fails(tmp_path):
    site = tmp_path / "site"
    site.mkdir()
    (site / "index.html").write_text("<p>51 AVE records</p>\n")
    ctx = vc.Context(sources={"ave": make_ave(tmp_path, 3), "website": site})
    surface = {"source": "website", "path": "index.html",
               "pattern": r"(?i)\b(\d+) AVE records\b"}
    out = vc.evaluate(ctx, number_claim(appears_in=[surface]))
    assert out.status == vc.FAIL
    assert "website:index.html:1: states 51" in out.problems[0]


def test_surface_pattern_missing_fails(tmp_path):
    site = tmp_path / "site"
    site.mkdir()
    (site / "index.html").write_text("nothing here\n")
    ctx = vc.Context(sources={"ave": make_ave(tmp_path, 3), "website": site})
    surface = {"source": "website", "path": "index.html", "pattern": r"(\d+) records"}
    assert vc.evaluate(ctx, number_claim(appears_in=[surface])).status == vc.FAIL


def test_fail_outranks_unverified(tmp_path):
    site = tmp_path / "site"
    site.mkdir()
    (site / "index.html").write_text("51 AVE records\n")
    ctx = vc.Context(sources={"ave": None, "website": site})
    surface = {"source": "website", "path": "index.html", "pattern": r"(\d+) AVE records"}
    out = vc.evaluate(ctx, number_claim(appears_in=[surface]))
    assert out.status == vc.FAIL
    assert any(p.startswith(vc.UNVERIFIED) for p in out.problems)


@pytest.mark.parametrize("check", ["license_apache", "gate_pip_install"])
def test_network_checks_offline_are_unverified(check):
    ctx = vc.Context(sources={}, offline=True)
    claim = {"id": "C-T", "claim": "t", "kind": "state", "check": check, "expect": True,
             "params": {"repos": ["bawbel/gate"]}}
    assert vc.evaluate(ctx, claim).status == vc.UNVERIFIED


def test_null_expect_is_unverified(tmp_path):
    ctx = vc.Context(sources={"ave": make_ave(tmp_path, 3)})
    assert vc.evaluate(ctx, number_claim(expect=None)).status == vc.UNVERIFIED


def test_unknown_check_fails():
    ctx = vc.Context(sources={})
    assert vc.evaluate(ctx, number_claim(check="no_such_check")).status == vc.FAIL


def wording_claim(scope: list[str]) -> dict:
    return {"id": "C-T", "claim": "t", "kind": "wording", "check": "forbidden_text",
            "params": {"scope": scope, "forbidden": ["(?i)never executes code"],
                       "qualifiers": ["(?i)by default"]}}


def test_forbidden_text_respects_qualifiers(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "README.md").write_text("Never executes code by default.\n")
    ctx = vc.Context(sources={"repo": repo})
    assert vc.evaluate(ctx, wording_claim(["repo"])).status == vc.PASS
    (repo / "README.md").write_text("Never executes code.\n")
    ctx = vc.Context(sources={"repo": repo})
    out = vc.evaluate(ctx, wording_claim(["repo"]))
    assert out.status == vc.FAIL
    assert out.details[0].startswith("repo:README.md:1:")


def test_wording_with_missing_scope_is_unverified(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "README.md").write_text("fine\n")
    ctx = vc.Context(sources={"repo": repo, "gone": None})
    assert vc.evaluate(ctx, wording_claim(["repo", "gone"])).status == vc.UNVERIFIED


def test_self_source_skips_register_files(tmp_path):
    repo = tmp_path / "self"
    (repo / "claims").mkdir(parents=True)
    (repo / "claims" / "register.yaml").write_text("never executes code\n")
    (repo / "README.md").write_text("ok\n")
    ctx = vc.Context(sources={"self": repo}, self_source="self")
    assert vc.evaluate(ctx, wording_claim(["self"])).status == vc.PASS


@pytest.mark.parametrize("url", [
    "ext::sh -c touch% /tmp/pwned",
    "file:///etc",
    "https://evil.example/bawbel/scanner",
    "https://github.com/bawbel/scanner; rm -rf /",
])
def test_clone_refuses_anything_but_github_https(tmp_path, url):
    with pytest.raises(vc.Unavailable):
        vc.clone(url, tmp_path / "x")


@pytest.mark.parametrize("text,value", [("51", 51), ("Six", 6), ("five", 5), ("static", None)])
def test_parse_number(text, value):
    assert vc.parse_number(text) == value


def test_no_shell_true_in_verifier():
    source = (ROOT / "scripts/verify_claims.py").read_text()
    assert not re.search(r"shell\s*=\s*True", source)


def test_register_is_complete():
    register = yaml.safe_load((ROOT / "claims/register.yaml").read_text())
    ids = [c["id"] for c in register["claims"]]
    assert ids == [f"C-{i:02d}" for i in range(1, 22)]
    for claim in register["claims"]:
        assert claim["check"] in vc.CHECKS, claim["id"]
        assert claim["kind"] in ("number", "wording", "state", "link"), claim["id"]
        for surface in claim.get("appears_in") or []:
            assert surface["source"] in register["sources"], claim["id"]
            assert re.compile(surface["pattern"]).groups >= 1, claim["id"]


def contract_claim(**params) -> dict:
    base = {"source": "self", "path": "docs/AVE-CONSUMPTION.md", "rules": 10}
    base.update(params)
    return {"id": "C-T", "claim": "contract", "kind": "state", "check": "consumption_contract",
            "expect": 10, "params": base}


def contract_repo(tmp_path: Path, rows: list[str]) -> "vc.Context":
    repo = tmp_path / "self"
    (repo / "docs").mkdir(parents=True)
    table = "| # | Rule |\n|---|---|\n" + "\n".join(f"| {r} | **Name.** text |" for r in rows)
    (repo / "docs" / "AVE-CONSUMPTION.md").write_text("# Contract\n\n" + table + "\n")
    return vc.Context(sources={"self": repo}, self_source="self")


def test_contract_with_ten_rules_in_order_passes(tmp_path):
    ctx = contract_repo(tmp_path, [f"R{i}" for i in range(1, 11)])
    assert vc.evaluate(ctx, contract_claim()).status == vc.PASS


@pytest.mark.parametrize("rows", [
    [f"R{i}" for i in range(1, 11) if i != 7],                     # R7 missing
    [f"R{i}" for i in range(1, 11)] + ["R10"],                     # R10 twice
    ["R2", "R1"] + [f"R{i}" for i in range(3, 11)],                # out of order
    [f"R{i}" for i in range(1, 10)],                               # only nine
    [f"R{i}" for i in range(1, 12)],                               # an eleventh nobody checks
], ids=["missing", "duplicate", "order", "nine", "eleven"])
def test_contract_with_wrong_rules_fails(tmp_path, rows):
    ctx = contract_repo(tmp_path, rows)
    assert vc.evaluate(ctx, contract_claim()).status == vc.FAIL


def test_contract_file_missing_fails(tmp_path):
    repo = tmp_path / "self"
    repo.mkdir()
    ctx = vc.Context(sources={"self": repo}, self_source="self")
    assert vc.evaluate(ctx, contract_claim()).status == vc.FAIL


def test_contract_source_unavailable_is_unverified(tmp_path):
    ctx = vc.Context(sources={"self": None})
    assert vc.evaluate(ctx, contract_claim()).status == vc.UNVERIFIED


def test_rule_in_prose_is_not_a_rule(tmp_path):
    repo = tmp_path / "self"
    (repo / "docs").mkdir(parents=True)
    (repo / "docs" / "AVE-CONSUMPTION.md").write_text("R1 is mentioned here\n| R1 text\n")
    ctx = vc.Context(sources={"self": repo}, self_source="self")
    assert vc.evaluate(ctx, contract_claim()).status == vc.FAIL


def test_the_contract_in_this_repository():
    """docs/AVE-CONSUMPTION.md has R1 to R10 in order and no em dash."""
    ctx = vc.Context(sources={"self": ROOT}, self_source="self")
    assert vc.evaluate(ctx, contract_claim()).status == vc.PASS
    assert "\u2014" not in (ROOT / "docs" / "AVE-CONSUMPTION.md").read_text(encoding="utf-8")
