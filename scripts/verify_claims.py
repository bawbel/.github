#!/usr/bin/env python3
"""Verify the public claims in claims/register.yaml and write claims/STATUS.md.

Every claim names a check function in CHECKS below. A check that cannot run reports
UNVERIFIED, never PASS. No shell is ever invoked: subprocess calls take fixed argument
lists, clones are https://github.com only, and HTTP goes through urllib with a timeout.

    python scripts/verify_claims.py                           # clone sources, use the network
    python scripts/verify_claims.py --offline --workspace DIR # local clones in DIR only

Exit status is 1 when any claim FAILs, 0 otherwise. UNVERIFIED claims are listed in
STATUS.md but do not change the exit status.
"""

from __future__ import annotations

import argparse
import ast
import datetime as dt
import json
import os
import re
# subprocess takes fixed argv lists only, never a shell.
import subprocess  # nosec B404
import sys
import tempfile
import urllib.error
import urllib.request
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from collections.abc import Callable
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent
REGISTER = ROOT / "claims" / "register.yaml"
STATUS = ROOT / "claims" / "STATUS.md"

PASS, FAIL, UNVERIFIED = "PASS", "FAIL", "UNVERIFIED"
_RANK = {PASS: 0, UNVERIFIED: 1, FAIL: 2}

HTTP_TIMEOUT = 20
GIT_TIMEOUT = 300
PIP_TIMEOUT = 600
MAX_LISTED = 30

GITHUB_URL = re.compile(r"^https://github\.com/[\w.-]+/[\w.-]+$")
SKIP_PATH = re.compile(r"(^|/)(dist|node_modules|\.git)/|lock", re.I)
BINARY = re.compile(r"\.(svg|png|gif|jpe?g|ico|webp|woff2?|ttf|eot|pdf|zip|gz|tgz)$", re.I)
DOCS = re.compile(r"\.(md|html?|rst|txt)$|(^|/)(package\.json|pyproject\.toml)$", re.I)
IMAGES = re.compile(r"\.(svg|png|gif|jpe?g|ico|webp)$", re.I)
# Files in this repository that quote claims on purpose. Never scanned as surfaces.
SELF_EXCLUDE = ("claims/", "scripts/verify_claims.py", "tests/", "docs/CLAIMS.md")
ROUTE = re.compile(r"^\s*@\w+\.(get|post|put|patch|delete|api_route)\(", re.M)
AVE_ID = re.compile(r"AVE-\d{4}-\d{5}")

NUMBER_WORDS = {
    w: i for i, w in enumerate(
        "zero one two three four five six seven eight nine ten eleven twelve thirteen "
        "fourteen fifteen sixteen seventeen eighteen nineteen twenty".split()
    )
}


class Unavailable(Exception):
    """An input a check needs is missing. The claim reports UNVERIFIED."""


@dataclass
class Measured:
    """What a check found. `violations` > 0 fails the claim."""

    value: Any
    evidence: str
    details: list[str] = field(default_factory=list)
    violations: int = 0
    incomplete: str | None = None


@dataclass
class Outcome:
    status: str = PASS
    measured: Any = None
    evidence: str = ""
    problems: list[str] = field(default_factory=list)
    details: list[str] = field(default_factory=list)

    def worsen(self, status: str, problem: str) -> None:
        if _RANK[status] > _RANK[self.status]:
            self.status = status
        self.problems.append(f"{status}: {problem}")


@dataclass
class Context:
    sources: dict[str, Path | None]
    reasons: dict[str, str] = field(default_factory=dict)
    shas: dict[str, str] = field(default_factory=dict)
    offline: bool = False
    self_source: str | None = None
    cache: dict[str, Any] = field(default_factory=dict)

    def repo(self, name: str) -> Path:
        path = self.sources.get(name)
        if path is None:
            reason = self.reasons.get(name, "not in the register")
            raise Unavailable(f"source {name} unavailable ({reason})")
        return path

    def files(self, name: str, docs_only: bool) -> list[tuple[str, Path]]:
        key = f"files:{name}:{docs_only}"
        if key not in self.cache:
            root = self.repo(name)
            try:
                listed = _git(["ls-files", "-z"], cwd=root).split("\0")
            except Unavailable:
                listed = [p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()]
            keep = []
            for rel in sorted(r for r in listed if r):
                if SKIP_PATH.search(rel) or BINARY.search(rel):
                    continue
                if name == self.self_source and rel.startswith(SELF_EXCLUDE):
                    continue
                if docs_only and not DOCS.search(rel):
                    continue
                if (root / rel).is_file():
                    keep.append((rel, root / rel))
            self.cache[key] = keep
        return self.cache[key]

    def tracked(self, name: str) -> list[str]:
        root = self.repo(name)
        return [r for r in _git(["ls-files", "-z"], cwd=root).split("\0") if r]


# ---------------------------------------------------------------- process and network


def _git(args: list[str], cwd: Path | None = None) -> str:
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0", GCM_INTERACTIVE="never",
               GIT_ALLOW_PROTOCOL="https")
    try:
        # Fixed argv, git resolved from PATH, no shell.
        proc = subprocess.run(  # nosec B603 B607 # noqa: S603
            ["git", *args], cwd=cwd,  # noqa: S607
            env=env, capture_output=True, text=True,
            timeout=GIT_TIMEOUT, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise Unavailable(f"git {args[0]} failed: {exc}") from exc
    if proc.returncode != 0:
        last = (proc.stderr.strip().splitlines() or ["no output"])[-1]
        raise Unavailable(f"git {args[0]} exited {proc.returncode}: {last}")
    return proc.stdout


def clone(url: str, dest: Path) -> None:
    """Shallow clone of a github.com repository. Nothing writes to it afterwards."""
    if not GITHUB_URL.match(url):
        raise Unavailable(f"refusing to clone {url!r}: only https://github.com/<org>/<repo>")
    _git(["clone", "--depth", "1", "--quiet", "--no-tags", "--", url, str(dest)])


def http_json(url: str) -> tuple[int, Any]:
    if not url.startswith("https://"):
        raise ValueError(f"refusing non-https URL {url!r}")
    headers = {"Accept": "application/json", "User-Agent": "bawbel-claims-verifier"}
    token = os.environ.get("GITHUB_TOKEN")
    if token and url.startswith("https://api.github.com/"):
        headers["Authorization"] = f"Bearer {token}"
    # https only, checked above.
    request = urllib.request.Request(url, headers=headers)  # noqa: S310
    try:
        with urllib.request.urlopen(  # nosec B310 # noqa: S310
            request, timeout=HTTP_TIMEOUT
        ) as resp:
            return resp.status, json.load(resp)
    except urllib.error.HTTPError as exc:
        return exc.code, None
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise Unavailable(f"GET {url} failed: {exc}") from exc


def _run(argv: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
    # Fixed argv built from constants and a temp dir path, no shell.
    return subprocess.run(  # nosec B603 # noqa: S603
        argv, capture_output=True, text=True, timeout=timeout, check=False
    )


# ---------------------------------------------------------------- shared measurements


def _ave_records(ctx: Context) -> dict[str, dict[str, Any]]:
    if "ave" not in ctx.cache:
        root = ctx.repo("ave")
        records = {}
        for path in sorted((root / "records").rglob("AVE-*.json")):
            data = json.loads(path.read_text(encoding="utf-8"))
            records[data["ave_id"]] = data
        if not records:
            raise Unavailable("no AVE-*.json under ave/records")
        ctx.cache["ave"] = records
    return ctx.cache["ave"]


def _dict_literals(path: Path) -> list[dict[str, Any]]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            literal = {}
            for key, value in zip(node.keys, node.values, strict=True):
                if isinstance(key, ast.Constant) and isinstance(key.value, str):
                    literal[key.value] = value.value if isinstance(value, ast.Constant) else None
            found.append(literal)
    return found


def _scanner_rules(ctx: Context) -> dict[str, Any]:
    """Rule counts and AVE ids per engine, read by parsing. No scanner code is run."""
    if "scanner" not in ctx.cache:
        root = ctx.repo("scanner")
        try:
            pattern = [d for d in _dict_literals(root / "scanner/engines/pattern_engine.py")
                       if "rule_id" in d]
            yara_text = (root / "scanner/rules/yara/ave_rules.yar").read_text(encoding="utf-8")
            semgrep = yaml.safe_load(
                (root / "scanner/rules/semgrep/ave_rules.yaml").read_text(encoding="utf-8")
            )["rules"]
            magika = (root / "scanner/engines/magika_engine.py").read_text(encoding="utf-8")
        except (OSError, KeyError, SyntaxError, yaml.YAMLError) as exc:
            raise Unavailable(f"scanner rule files unreadable: {exc}") from exc
        ids = {
            "pattern": {d["ave_id"] for d in pattern if isinstance(d.get("ave_id"), str)},
            "yara": set(re.findall(r'ave_id\s*=\s*"(AVE-\d{4}-\d{5})"', yara_text)),
            "semgrep": {str(r["metadata"]["ave_id"]) for r in semgrep
                        if (r.get("metadata") or {}).get("ave_id")},
            "magika": set(AVE_ID.findall(magika)),
        }
        ctx.cache["scanner"] = {
            "counts": {
                "pattern": len(pattern),
                "yara": len(re.findall(r"(?m)^\s*rule\s+\w+", yara_text)),
                "semgrep": len(semgrep),
            },
            "ids": ids,
            "static": ids["pattern"] | ids["yara"] | ids["semgrep"],
            "detected": ids["pattern"] | ids["yara"] | ids["semgrep"] | ids["magika"],
        }
    return ctx.cache["scanner"]


def _uncovered(ctx: Context) -> Counter[str]:
    records = _ave_records(ctx)
    detected = _scanner_rules(ctx)["detected"]
    return Counter(str(records[i].get("detection_stage")) for i in set(records) - detected)


def _at(ctx: Context, *names: str) -> str:
    return ", ".join(f"{n}@{ctx.shas.get(n, '?')}" for n in names)


def _scan_lines(
    ctx: Context, scope: list[str], docs_only: bool, test: Callable[[str], str | None]
) -> tuple[list[str], list[str]]:
    """Apply test to every line in scope. Returns (violations, unavailable sources)."""
    hits, missing = [], []
    for name in scope:
        try:
            files = ctx.files(name, docs_only)
        except Unavailable as exc:
            missing.append(str(exc))
            continue
        for rel, path in files:
            text = path.read_text(encoding="utf-8", errors="replace")
            for lineno, line in enumerate(text.splitlines(), 1):
                reason = test(line)
                if reason:
                    hits.append(f"{name}:{rel}:{lineno}: {reason}: {line.strip()[:120]}")
    return hits, missing


def _forbidden(ctx: Context, params: dict[str, Any]) -> tuple[list[str], list[str]]:
    forbidden = [re.compile(p) for p in params.get("forbidden", [])]
    qualifiers = [re.compile(p) for p in params.get("qualifiers", [])]

    def test(line: str) -> str | None:
        for rx in forbidden:
            match = rx.search(line)
            if match and not any(q.search(line) for q in qualifiers):
                return f"forbidden {match.group(0)!r}"
        return None

    return _scan_lines(ctx, params.get("scope", []), True, test)


def _measured_scan(value: Any, evidence: str, hits: list[str], missing: list[str]) -> Measured:
    return Measured(
        value=value, evidence=evidence, details=hits, violations=len(hits),
        incomplete="; ".join(missing) or None,
    )


# ---------------------------------------------------------------- checks


def ave_published(ctx: Context, params: dict[str, Any]) -> Measured:
    return Measured(len(_ave_records(ctx)), f"records/AVE-*.json at {_at(ctx, 'ave')}")


def scanner_metadata(ctx: Context, params: dict[str, Any]) -> Measured:
    path = ctx.repo("scanner") / "scanner/ave_meta.py"
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError) as exc:
        raise Unavailable(f"{path.name} unreadable: {exc}") from exc
    for node in ast.walk(tree):
        if isinstance(node, ast.AnnAssign):
            target = node.target
        elif isinstance(node, ast.Assign):
            target = node.targets[0]
        else:
            continue
        if isinstance(target, ast.Name) and target.id == "AVE_META":
            if isinstance(node.value, ast.Dict):
                return Measured(len(node.value.keys),
                                f"AVE_META keys in scanner/ave_meta.py at {_at(ctx, 'scanner')}")
    raise Unavailable("AVE_META not found in scanner/ave_meta.py")


def scanner_detection(ctx: Context, params: dict[str, Any]) -> Measured:
    rules = _scanner_rules(ctx)
    ids = rules["ids"]
    no_engine = sorted(set(_ave_records(ctx)) - rules["detected"])
    return Measured(
        len(rules["detected"]),
        f"ids: pattern {len(ids['pattern'])}, yara {len(ids['yara'])}, "
        f"semgrep {len(ids['semgrep'])}, static union {len(rules['static'])}, "
        f"magika {len(ids['magika'])} at {_at(ctx, 'scanner', 'ave')}",
        details=[f"no non-LLM engine: {len(no_engine)} records"],
    )


def uncovered_static(ctx: Context, params: dict[str, Any]) -> Measured:
    stages = _uncovered(ctx)
    return Measured(stages.get("static_detection", 0),
                    f"uncovered by stage {dict(sorted(stages.items()))}")


def uncovered_runtime(ctx: Context, params: dict[str, Any]) -> Measured:
    stages = _uncovered(ctx)
    runtime = {k: v for k, v in stages.items() if k.startswith("runtime")}
    return Measured(sum(runtime.values()),
                    f"uncovered runtime stages {dict(sorted(runtime.items()))}")


def toxic_flows(ctx: Context, params: dict[str, Any]) -> Measured:
    path = ctx.repo("scanner") / "scanner/core/toxic_flows/flows.py"
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError) as exc:
        raise Unavailable(f"flows.py unreadable: {exc}") from exc
    calls = [n for n in ast.walk(tree)
             if isinstance(n, ast.Call) and getattr(n.func, "id", None) == "FlowDef"]
    return Measured(len(calls), f"FlowDef(...) entries in flows.py at {_at(ctx, 'scanner')}")


def detection_rules(ctx: Context, params: dict[str, Any]) -> Measured:
    counts = _scanner_rules(ctx)["counts"]
    return Measured(sum(counts.values()),
                    f"pattern {counts['pattern']} + yara {counts['yara']} + "
                    f"semgrep {counts['semgrep']} at {_at(ctx, 'scanner')}")


def detection_engines(ctx: Context, params: dict[str, Any]) -> Measured:
    engines = sorted(p.stem for p in (ctx.repo("scanner") / "scanner/engines").glob("*_engine.py"))
    if not engines:
        raise Unavailable("no scanner/engines/*_engine.py")
    return Measured(len(engines), f"{', '.join(engines)} at {_at(ctx, 'scanner')}")


def license_apache(ctx: Context, params: dict[str, Any]) -> Measured:
    if ctx.offline:
        raise Unavailable("offline: needs the GitHub license API")
    bad, notes = [], []
    for repo in params["repos"]:
        code, data = http_json(f"https://api.github.com/repos/{repo}/license")
        if code == 200:
            spdx = ((data or {}).get("license") or {}).get("spdx_id")
            (notes if spdx == "Apache-2.0" else bad).append(f"{repo}: {spdx}")
        elif code == 404:
            code, info = http_json(f"https://api.github.com/repos/{repo}")
            if code == 200 and (info or {}).get("size") == 0:
                notes.append(f"{repo}: empty repository, skipped")
            else:
                bad.append(f"{repo}: no license file")
        else:
            raise Unavailable(f"license API returned {code} for {repo}")
    return Measured(not bad, f"{len(params['repos'])} repos via GitHub API",
                    details=bad + notes, violations=len(bad))


def gate_pip_install(ctx: Context, params: dict[str, Any]) -> Measured:
    if ctx.offline:
        raise Unavailable("offline: needs PyPI")
    code, data = http_json("https://pypi.org/pypi/bawbel-gate/json")
    if code == 404:
        return Measured(False, "bawbel-gate is not on PyPI", violations=1)
    if code != 200:
        raise Unavailable(f"PyPI returned {code}")
    version = data["info"]["version"]
    with tempfile.TemporaryDirectory(prefix="claims-venv-") as tmp:
        bindir = Path(tmp) / ("Scripts" if os.name == "nt" else "bin")
        steps = [
            [sys.executable, "-m", "venv", tmp],
            [str(bindir / "python"), "-m", "pip", "install", "--quiet", "--no-cache-dir",
             "--disable-pip-version-check", f"bawbel-gate=={version}"],
            [str(bindir / "bawbel-gate"), "--version"],
        ]
        for argv in steps:
            try:
                proc = _run(argv, PIP_TIMEOUT)
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise Unavailable(f"{Path(argv[0]).name} failed to run: {exc}") from exc
            if proc.returncode != 0:
                tail = (proc.stderr.strip().splitlines() or ["no output"])[-1]
                return Measured(False, f"bawbel-gate {version}: {' '.join(argv[1:3])} failed",
                                details=[tail[:200]], violations=1)
    return Measured(True, f"bawbel-gate {version} installed in a clean venv, "
                          f"--version: {proc.stdout.strip()}")


def registry_state(ctx: Context, params: dict[str, Any]) -> Measured:
    hits, missing = _forbidden(ctx, params)
    try:
        root = ctx.repo("registry")
    except Unavailable as exc:
        missing.append(str(exc))
        return _measured_scan(None, "registry repository unreadable", hits, missing)
    signed = (root / "index/index.json").is_file() and (
        root / "index/index.json.sigstore.json"
    ).is_file()
    state = "built" if signed else "designed"
    return _measured_scan(state, f"signed index present: {signed} at {_at(ctx, 'registry')}",
                          hits, missing)


def identity_reputation_delegation(ctx: Context, params: dict[str, Any]) -> Measured:
    hits, missing = _forbidden(ctx, params)
    modules = [p for p in ctx.tracked("gate")
               if p.startswith("src/") and re.search(r"identity|reputation|delegat", p, re.I)]
    state = "built" if modules else "not-built"
    out = _measured_scan(state, f"gate src modules matching: {len(modules)} at "
                                f"{_at(ctx, 'gate')}", hits, missing)
    out.details += [f"gate module: {m}" for m in modules]
    return out


def stale_hosts(ctx: Context, params: dict[str, Any]) -> Measured:
    patterns = [re.compile(p) for p in params["patterns"]]
    per_source: Counter[str] = Counter()
    listed, missing = [], []
    for name in params["scope"]:
        try:
            files = ctx.files(name, docs_only=False)
        except Unavailable as exc:
            missing.append(str(exc))
            continue
        for rel, path in files:
            text = path.read_text(encoding="utf-8", errors="replace")
            for lineno, line in enumerate(text.splitlines(), 1):
                count = sum(len(rx.findall(line)) for rx in patterns)
                if count:
                    per_source[name] += count
                    listed.append(f"{name}:{rel}:{lineno}")
    total = sum(per_source.values())
    breakdown = ", ".join(f"{k} {v}" for k, v in sorted(per_source.items())) or "none"
    return Measured(total, f"per repo: {breakdown}", details=listed, violations=total,
                    incomplete="; ".join(missing) or None)


def piranha_endpoints(ctx: Context, params: dict[str, Any]) -> Measured:
    root = ctx.repo("piranha-api")
    total = sum(len(ROUTE.findall((root / rel).read_text(encoding="utf-8", errors="replace")))
                for rel in ctx.tracked("piranha-api") if rel.endswith(".py"))
    return Measured(total, f"{total} route decorators at {_at(ctx, 'piranha-api')}",
                    incomplete="which routes are public is not knowable from the source")


def third_party_logos(ctx: Context, params: dict[str, Any]) -> Measured:
    vendors = re.compile("(?i)(" + "|".join(params["vendors"]) + ")")
    found, missing = [], []
    for name in params["scope"]:
        try:
            found += [f"{name}:{p}" for p in ctx.tracked(name)
                      if IMAGES.search(p) and vendors.search(p)]
        except Unavailable as exc:
            missing.append(str(exc))
    return Measured(len(found), f"image files named after a vendor: {len(found)}",
                    details=found, violations=len(found), incomplete="; ".join(missing) or None)


def forbidden_text(ctx: Context, params: dict[str, Any]) -> Measured:
    hits, missing = _forbidden(ctx, params)
    return _measured_scan(len(hits), f"{len(hits)} unqualified uses", hits, missing)


def mention_rules(ctx: Context, params: dict[str, Any]) -> Measured:
    trigger = re.compile(params["trigger"])
    require = [re.compile(p) for p in params.get("require", [])]
    forbidden = [re.compile(p) for p in params.get("forbidden", [])]

    def test(line: str) -> str | None:
        if not trigger.search(line):
            return None
        if any(not rx.search(line) for rx in require):
            return "missing required context"
        if any(rx.search(line) for rx in forbidden):
            return "forbidden context"
        return None

    hits, missing = _scan_lines(ctx, params.get("scope", []), True, test)
    return _measured_scan(len(hits), f"{len(hits)} mentions break the rule", hits, missing)


def required_text(ctx: Context, params: dict[str, Any]) -> Measured:
    root = ctx.repo(params["source"])
    rx = re.compile(params["pattern"])
    found = []
    for rel in params["paths"]:
        path = root / rel
        if path.is_file():
            for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if rx.search(line):
                    found.append(f"{params['source']}:{rel}:{lineno}")
    missing = 0 if found else 1
    return Measured(missing, f"stated in {len(found)} place(s) at {_at(ctx, params['source'])}",
                    details=found or ["required statement not found"], violations=missing)


CHECKS: dict[str, Callable[[Context, dict[str, Any]], Measured]] = {
    f.__name__: f
    for f in (
        ave_published, scanner_metadata, scanner_detection, uncovered_static,
        uncovered_runtime, toxic_flows, detection_rules, detection_engines, license_apache,
        gate_pip_install, registry_state, identity_reputation_delegation, stale_hosts,
        piranha_endpoints, third_party_logos, forbidden_text, mention_rules, required_text,
    )
}


# ---------------------------------------------------------------- evaluation


def parse_number(text: str) -> int | None:
    text = text.strip().lower()
    if text.isdigit():
        return int(text)
    return NUMBER_WORDS.get(text)


def check_surface(ctx: Context, surface: dict[str, str], expect: Any, out: Outcome) -> None:
    where = f"{surface['source']}:{surface['path']}"
    try:
        path = ctx.repo(surface["source"]) / surface["path"]
    except Unavailable as exc:
        out.worsen(UNVERIFIED, f"{where}: {exc}")
        return
    if not path.is_file():
        out.worsen(FAIL, f"{where}: file not found, update appears_in")
        return
    rx = re.compile(surface["pattern"])
    found = False
    for lineno, line in enumerate(path.read_text(encoding="utf-8", errors="replace")
                                  .splitlines(), 1):
        for match in rx.finditer(line):
            found = True
            stated = parse_number(match.group(1))
            loc = f"{where}:{lineno}"
            if stated is None:
                out.worsen(FAIL, f"{loc}: no number in {match.group(0)!r}")
            elif expect is None:
                out.details.append(f"{loc}: states {stated}")
            elif stated != expect:
                out.worsen(FAIL, f"{loc}: states {stated}, register expects {expect}")
    if not found:
        out.worsen(FAIL, f"{where}: pattern not found, the claim moved or was removed")


def evaluate(ctx: Context, claim: dict[str, Any]) -> Outcome:
    out = Outcome()
    check = CHECKS.get(claim.get("check", ""))
    expect = claim.get("expect")
    if check is None:
        out.worsen(FAIL, f"unknown check {claim.get('check')!r}")
        return out
    try:
        measured = check(ctx, claim.get("params") or {})
    except Unavailable as exc:
        out.worsen(UNVERIFIED, str(exc))
        measured = None
    if measured is not None:
        out.measured, out.evidence = measured.value, measured.evidence
        out.details.extend(measured.details)
        if measured.violations:
            out.worsen(FAIL, f"{measured.violations} violation(s), listed below")
        if measured.incomplete:
            out.worsen(UNVERIFIED, measured.incomplete)
        comparable = measured.incomplete is None and not measured.violations
        if claim.get("kind") in ("number", "state") and comparable:
            if expect is None:
                out.worsen(UNVERIFIED, "the register has no expected value")
            elif measured.value != expect:
                out.worsen(FAIL, f"measured {measured.value!r}, register expects {expect!r}")
    for surface in claim.get("appears_in") or []:
        check_surface(ctx, surface, expect, out)
    return out


def acquire(register: dict[str, Any], workspace: Path, offline: bool) -> Context:
    ctx = Context(sources={}, offline=offline)
    for name, spec in register["sources"].items():
        if spec.get("self"):
            ctx.sources[name], ctx.self_source = ROOT, name
        else:
            dest = workspace / name
            if not dest.is_dir() and not offline:
                try:
                    clone(spec["url"], dest)
                except Unavailable as exc:
                    note = "private, needs read access" if spec.get("private") else str(exc)
                    ctx.reasons[name] = note
            if dest.is_dir():
                ctx.sources[name] = dest
            else:
                ctx.sources[name] = None
                ctx.reasons.setdefault(name, "offline and no clone in the workspace")
        if ctx.sources[name] is not None:
            try:
                ctx.shas[name] = _git(["rev-parse", "--short", "HEAD"],
                                      cwd=ctx.sources[name]).strip()
            except Unavailable:
                ctx.shas[name] = "working-tree"
    return ctx


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def render(register: dict[str, Any], ctx: Context, results: list[tuple[dict, Outcome]],
           offline: bool) -> str:
    tally = Counter(o.status for _, o in results)
    lines = [
        "# Claims status",
        "",
        "Generated by `scripts/verify_claims.py` from `claims/register.yaml`. "
        "Do not edit by hand.",
        "",
        f"- Run: {dt.date.today().isoformat()}, mode: {'offline' if offline else 'online'}",
        "- Sources: " + ", ".join(
            f"{n}@{ctx.shas[n]}" if ctx.sources.get(n) else f"{n} (unavailable)"
            for n in register["sources"]
        ),
        f"- Result: {tally[FAIL]} FAIL, {tally[UNVERIFIED]} UNVERIFIED, {tally[PASS]} PASS",
        "",
        "| ID | Claim | Result | Measured | Expected | Evidence |",
        "|---|---|---|---|---|---|",
    ]
    for claim, out in results:
        expect = claim.get("expect", "0 violations" if claim.get("kind") == "wording" else None)
        evidence = out.evidence
        if out.problems:
            evidence += f" ({len(out.problems)} problem(s), see Details)"
        lines.append(
            f"| {claim['id']} | {_cell(claim['claim'])} | **{out.status}** | "
            f"{_cell(str(out.measured))} | {_cell(str(expect))} | {_cell(evidence)} |"
        )
    lines += ["", "## Unverified", ""]
    unverified = [(c, o) for c, o in results if o.status == UNVERIFIED]
    lines += [f"- {c['id']}: " + "; ".join(p.split(": ", 1)[1] for p in o.problems
                                         if p.startswith(UNVERIFIED))
              for c, o in unverified] or ["None."]
    lines += ["", "## Details", ""]
    for claim, out in results:
        if out.status == PASS and not out.details:
            continue
        lines += [f"### {claim['id']} {claim['claim']}: {out.status}", ""]
        shown = out.problems + out.details
        lines += [f"- {_cell(item)}" for item in shown[:MAX_LISTED]]
        if len(shown) > MAX_LISTED:
            lines.append(f"- ... and {len(shown) - MAX_LISTED} more")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--offline", action="store_true",
                        help="no network: use clones already in --workspace only")
    parser.add_argument("--workspace", type=Path,
                        help="directory of clones, one per source name; reused across runs")
    parser.add_argument("--register", type=Path, default=REGISTER)
    parser.add_argument("--output", type=Path, default=STATUS)
    args = parser.parse_args(argv)

    register = yaml.safe_load(args.register.read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory(prefix="claims-ws-") as tmp:
        workspace = args.workspace or Path(tmp)
        workspace.mkdir(parents=True, exist_ok=True)
        ctx = acquire(register, workspace, args.offline)
        results = [(claim, evaluate(ctx, claim)) for claim in register["claims"]]
    args.output.write_text(render(register, ctx, results, args.offline), encoding="utf-8")
    tally = Counter(o.status for _, o in results)
    print(f"{tally[FAIL]} FAIL, {tally[UNVERIFIED]} UNVERIFIED, {tally[PASS]} PASS "
          f"-> {args.output}")
    return 1 if tally[FAIL] else 0


if __name__ == "__main__":
    sys.exit(main())
