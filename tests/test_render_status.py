"""Tests for scripts/render_status.py. No network: every input is a temp file."""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location("render_status", ROOT / "scripts/render_status.py")
rs = importlib.util.module_from_spec(SPEC)
sys.modules["render_status"] = rs
SPEC.loader.exec_module(rs)

COMPONENTS = [
    {"id": "ave", "label": "AVE, separate org", "state": "live", "evidence": "C-01",
     "boundary": "outside"},
    {"id": "scanner", "label": "Scanner and surfaces", "state": "live", "evidence": "C-03"},
    {"id": "piranhadb", "label": "PiranhaDB", "state": "offline", "evidence": "C-17"},
    {"id": "gate", "label": "Gate", "state": "pre-release", "evidence": "C-10"},
    {"id": "registry", "label": "Registry", "state": "designed", "evidence": "C-14"},
    {"id": "identity", "label": "Identity beyond pins", "state": "not-built", "evidence": "C-15"},
]
EDGES = [["ave", "scanner"], ["ave", "piranhadb"], ["scanner", "registry"], ["registry", "gate"]]
CLAIM_IDS = {"C-01", "C-03", "C-10", "C-14", "C-15", "C-17"}


def status(**changes) -> dict:
    data = {"schema": "bawbel/ecosystem-status/v1",
            "components": [dict(c) for c in COMPONENTS], "edges": [list(e) for e in EDGES]}
    data.update(changes)
    return data


def checked(data: dict) -> dict:
    return rs.validate(data, CLAIM_IDS)


def table(**results: str) -> str:
    rows = [f"| {cid} | some claim | **{res}** | 1 | 1 | evidence |" for cid, res in results.items()]
    return "# Claims status\n\n| Id | Claim | Result | Measured | Expected | Evidence |\n" \
           "|---|---|---|---|---|---|\n" + "\n".join(rows) + "\n"


# ---------------------------------------------------------------- rendering


def test_output_is_deterministic_and_ends_with_a_newline():
    first, second = rs.render(checked(status())), rs.render(checked(status()))
    assert first == second
    assert first.endswith("\n") and not first.endswith("\n\n")
    assert first.startswith("flowchart TD\n")


def test_every_component_is_drawn_with_its_label_and_state_in_text():
    out = rs.render(checked(status()))
    for c in COMPONENTS:
        line = next(l for l in out.splitlines() if l.strip().startswith(c["id"] + "["))
        assert c["label"] in line
        assert f"<small>{c['state']}</small>" in line, "state must be text, not only colour"


def test_ave_sits_outside_the_boundary_dashed_and_labelled_separate_org():
    out = rs.render(checked(status()))
    lines = out.splitlines()
    start = next(i for i, l in enumerate(lines) if l.strip().startswith("subgraph"))
    end = next(i for i, l in enumerate(lines) if l.strip() == "end")
    ave = next(i for i, l in enumerate(lines) if l.strip().startswith("ave["))
    assert not start < ave < end
    assert "separate org" in lines[ave]
    assert re.search(r"class ave [^\n]*\boutside\b", out)
    outside = next(l for l in lines if l.strip().startswith("classDef outside"))
    assert "stroke-dasharray" in outside


def test_inside_components_are_in_the_bawbel_subgraph():
    lines = rs.render(checked(status())).splitlines()
    start = next(i for i, l in enumerate(lines) if l.strip().startswith("subgraph"))
    end = next(i for i, l in enumerate(lines) if l.strip() == "end")
    inside = {l.strip().split("[")[0] for l in lines[start + 1:end] if "[" in l}
    assert inside == {"scanner", "piranhadb", "gate", "registry", "identity"}


def state_class(state: str) -> str:
    return rs.STATE_CLASS[state]


@pytest.mark.parametrize("state, dashed", [
    ("live", False), ("pre-release", False), ("designed", True), ("offline", True),
    ("not-built", True),
])
def test_each_state_has_a_class_and_only_unshipped_ones_are_dashed(state, dashed):
    out = rs.render(checked(status()))
    definition = next(l for l in out.splitlines() if l.strip().startswith(f"classDef {state_class(state)} "))
    assert ("stroke-dasharray" in definition) is dashed


def test_the_dash_patterns_differ_so_colour_is_never_the_only_cue():
    patterns = [rs.STATE_STYLE[s]["stroke-dasharray"] for s in rs.STATES
                if "stroke-dasharray" in rs.STATE_STYLE[s]]
    assert len(patterns) == 3 and len(set(patterns)) == len(patterns)


def test_legend_names_every_state_and_the_status_file():
    out = rs.render(checked(status()))
    legend = next(l for l in out.splitlines() if l.strip().startswith("legend["))
    for state in rs.STATES:
        assert state in legend
    assert "claims/STATUS.md" in legend


def test_edges_are_drawn_in_file_order():
    out = rs.render(checked(status()))
    arrows = [l.strip() for l in out.splitlines() if "-->" in l]
    assert arrows == ["ave --> scanner", "ave --> piranhadb", "scanner --> registry",
                      "registry --> gate"]


def test_labels_are_escaped():
    data = status()
    data["components"][1]["label"] = 'Scan "x" <b>&</b>'
    out = rs.render(checked(data))
    assert "<b>" not in out and '"x"' not in out
    assert "#quot;x#quot;" in out and "#lt;b#gt;" in out and "#amp;" in out


# ---------------------------------------------------------------- validation


@pytest.mark.parametrize("mutate, message", [
    (lambda d: d["components"][0].update(state="shipped"), "unknown state"),
    (lambda d: d["components"][1].update(id="ave"), "duplicate"),
    (lambda d: d["components"][1].update(id="Bad Id"), "invalid id"),
    (lambda d: d["components"][1].update(id="end"), "reserved"),
    (lambda d: d["components"][1].update(evidence="claim-3"), "evidence"),
    (lambda d: d["components"][1].update(evidence="C-99"), "not in the register"),
    (lambda d: d["components"][0].update(boundary="inside"), "boundary"),
    (lambda d: d["components"][1].pop("label"), "label"),
    (lambda d: d["edges"].append(["ave", "nowhere"]), "unknown component"),
    (lambda d: d["edges"].append(["ave"]), "edge"),
    (lambda d: d.update(components=[]), "no components"),
    (lambda d: d.update(schema="other/v1"), "schema"),
])
def test_invalid_status_files_are_rejected(mutate, message):
    data = status()
    mutate(data)
    with pytest.raises(rs.StatusError, match=message):
        checked(data)


# ---------------------------------------------------------------- evidence


def test_parse_results_reads_the_status_table():
    text = table(**{"C-01": "PASS", "C-02": "FAIL", "C-03": "UNVERIFIED"})
    assert rs.parse_results(text) == {"C-01": "PASS", "C-02": "FAIL", "C-03": "UNVERIFIED"}


def test_live_with_a_passing_claim_is_accepted():
    data = checked(status())
    assert rs.evidence_errors(data, {"C-01": "PASS", "C-03": "PASS"}) == []


@pytest.mark.parametrize("result", ["FAIL", "UNVERIFIED"])
def test_live_with_a_claim_that_is_not_passing_is_an_error(result):
    errors = rs.evidence_errors(checked(status()), {"C-01": result, "C-03": "PASS"})
    assert len(errors) == 1
    assert "ave" in errors[0] and "C-01" in errors[0] and result in errors[0]


def test_live_with_a_claim_missing_from_the_results_is_an_error():
    errors = rs.evidence_errors(checked(status()), {"C-01": "PASS"})
    assert len(errors) == 1 and "C-03" in errors[0] and "no result" in errors[0]


def test_a_component_that_is_not_live_needs_no_passing_claim():
    results = {"C-01": "PASS", "C-03": "PASS", "C-10": "FAIL", "C-14": "FAIL", "C-17": "UNVERIFIED"}
    assert rs.evidence_errors(checked(status()), results) == []


# ---------------------------------------------------------------- the command


def workspace(tmp_path: Path, data: dict | None = None, results: str | None = None) -> list[str]:
    (tmp_path / "claims").mkdir()
    (tmp_path / "diagrams").mkdir()
    (tmp_path / "profile").mkdir()
    (tmp_path / "ecosystem-status.yaml").write_text(yaml.safe_dump(data or status()))
    (tmp_path / "claims" / "STATUS.md").write_text(
        results or table(**{"C-01": "PASS", "C-03": "PASS"}))
    (tmp_path / "claims" / "register.yaml").write_text(
        yaml.safe_dump({"claims": [{"id": c} for c in sorted(CLAIM_IDS)]}))
    (tmp_path / "profile" / "README.md").write_text(
        f"intro\n\n{rs.BEGIN}\nold\n{rs.END}\n\noutro\n")
    return ["--root", str(tmp_path)]


def test_write_then_check_is_clean_and_idempotent(tmp_path):
    root = workspace(tmp_path)
    assert rs.main(root + ["--write"]) == 0
    first = (tmp_path / "diagrams" / "status.mmd").read_text()
    readme = (tmp_path / "profile" / "README.md").read_text()
    assert rs.main(root + ["--write"]) == 0
    assert (tmp_path / "diagrams" / "status.mmd").read_text() == first
    assert (tmp_path / "profile" / "README.md").read_text() == readme
    assert rs.main(root + ["--check"]) == 0
    assert readme.startswith("intro\n") and readme.endswith("outro\n")
    assert "```mermaid" in readme and "[claims/STATUS.md](" in readme


def test_check_fails_when_the_committed_diagram_is_stale(tmp_path, capsys):
    root = workspace(tmp_path)
    assert rs.main(root + ["--write"]) == 0
    (tmp_path / "diagrams" / "status.mmd").write_text("flowchart TD\n    old\n")
    assert rs.main(root + ["--check"]) == 1
    assert "diagrams/status.mmd" in capsys.readouterr().err


def test_check_fails_when_the_readme_block_is_stale(tmp_path, capsys):
    root = workspace(tmp_path)
    assert rs.main(root + ["--write"]) == 0
    readme = tmp_path / "profile" / "README.md"
    readme.write_text(readme.read_text().replace("Registry", "Registre"))
    assert rs.main(root + ["--check"]) == 1
    assert "profile/README.md" in capsys.readouterr().err


def test_check_fails_when_the_status_file_changed_but_nothing_was_regenerated(tmp_path):
    root = workspace(tmp_path)
    assert rs.main(root + ["--write"]) == 0
    data = status()
    data["components"][3]["state"] = "live"
    (tmp_path / "ecosystem-status.yaml").write_text(yaml.safe_dump(data))
    assert rs.main(root + ["--check"]) == 1


def test_readme_without_markers_is_an_error(tmp_path):
    root = workspace(tmp_path)
    (tmp_path / "profile" / "README.md").write_text("no markers here\n")
    assert rs.main(root + ["--write"]) == 2


def test_verify_evidence_passes_and_fails_through_the_command(tmp_path, capsys):
    root = workspace(tmp_path)
    assert rs.main(root + ["--verify-evidence"]) == 0
    (tmp_path / "claims" / "STATUS.md").write_text(table(**{"C-01": "FAIL", "C-03": "PASS"}))
    assert rs.main(root + ["--verify-evidence"]) == 1
    assert "ave" in capsys.readouterr().err


def test_setting_a_component_live_with_a_failing_claim_fails(tmp_path, capsys):
    """The acceptance case: gate is set to live while its evidence claim C-10 fails."""
    data = status()
    data["components"][3]["state"] = "live"
    root = workspace(tmp_path, data, table(**{"C-01": "PASS", "C-03": "PASS", "C-10": "FAIL"}))
    assert rs.main(root + ["--verify-evidence"]) == 1
    err = capsys.readouterr().err
    assert "gate" in err and "C-10" in err


def test_unreadable_inputs_exit_2(tmp_path):
    root = workspace(tmp_path)
    (tmp_path / "ecosystem-status.yaml").write_text("components: [unclosed")
    assert rs.main(root + ["--check"]) == 2
    assert rs.main(["--root", str(tmp_path / "missing"), "--check"]) == 2


def test_the_generator_has_no_network_code():
    source = (ROOT / "scripts/render_status.py").read_text()
    assert not re.search(r"^\s*(import|from)\s+(socket|urllib|http|requests|ssl)\b", source, re.M)
    assert not re.search(r"shell\s*=\s*True", source)


# ---------------------------------------------------------------- this repository


def test_the_committed_files_in_this_repository_are_current():
    assert rs.main(["--root", str(ROOT), "--check"]) == 0


def test_this_repository_names_only_registered_claims_and_known_states():
    data = yaml.safe_load((ROOT / "ecosystem-status.yaml").read_text())
    register = yaml.safe_load((ROOT / "claims/register.yaml").read_text())
    ids = {c["id"] for c in register["claims"]}
    rs.validate(data, ids)
    states = {c["state"] for c in data["components"]}
    assert states <= set(rs.STATES)
    piranha = next(c for c in data["components"] if c["id"] == "piranhadb")
    assert piranha["state"] == "offline"
    ave = next(c for c in data["components"] if c["id"] == "ave")
    assert ave["boundary"] == "outside"
