#!/usr/bin/env python3
"""Measured scorecard for a time window and a list of repositories. Read only.

Every request is an HTTP GET to the GitHub REST API. Nothing is written anywhere.
A token is optional and only needs read access: Pull requests: read, Actions: read,
Contents: read, Metadata: read. Without a token the API allows 60 requests an hour.

    python3 weekly_scorecard.py --days 14 --repos bawbel/gate bawbel/scanner
    python3 weekly_scorecard.py --since 2026-11-16 --until 2026-11-23 --repos bawbel/gate

Every number is computed from a query that is printed at the end of the output.
No targets are set here. A number that cannot be computed is printed as
"unavailable" with the HTTP status, never as zero.

Internal use. The scorecard sets no targets and supports no public claims.

The median "ready to merge" time measures how fast pull requests are merged, which is the
maintainer's merge speed. It does not measure review depth: a merge with no review counts
the same as one with a long review.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, OrderedDict
from datetime import datetime, timedelta, timezone

API = "https://api.github.com"
MAX_PAGES = 30
DEFAULT_REPOS = [
    "bawbel/gate", "bawbel/scanner", "bawbel/integrations", "bawbel/bawbel-mcp",
    "bawbel/piranha-api", "bawbel/bawbel.github.io", "bawbel/.github",
]
BAD = {"failure", "timed_out", "cancelled", "action_required", "startup_failure", "stale"}
GOOD = {"success", "skipped", "neutral"}


# ------------------------------------------------------------------ transport


class Api:
    """GET only. Keeps a log of every request so the output can print its queries."""

    def __init__(self, token: str | None = None) -> None:
        self.token = token
        self.calls: Counter[str] = Counter()
        self.first_url: "OrderedDict[str, str]" = OrderedDict()
        self.remaining: str | None = None

    def get(self, path: str, params: dict | None = None, label: str = "") -> tuple[int, object]:
        url = API + path + ("?" + urllib.parse.urlencode(params) if params else "")
        self.calls[label or path] += 1
        self.first_url.setdefault(label or path, url)
        req = urllib.request.Request(url, method="GET", headers={
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "bawbel-weekly-scorecard",
        })
        if self.token:
            req.add_header("Authorization", f"Bearer {self.token}")
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                self.remaining = resp.headers.get("X-RateLimit-Remaining", self.remaining)
                return resp.status, json.loads(resp.read().decode("utf-8") or "null")
        except urllib.error.HTTPError as exc:
            return exc.code, None
        except (urllib.error.URLError, TimeoutError, ValueError):
            return 0, None


def paged(api: Api, path: str, params: dict, label: str, stop=None):
    """Return (items, problem). `problem` is None, an HTTP status, or a truncation note. `stop(last_item)` ends the paging."""
    out: list = []
    for page in range(1, MAX_PAGES + 1):
        code, data = api.get(path, dict(params, per_page=100, page=page), label)
        if code != 200 or not isinstance(data, list):
            return out, f"HTTP {code}"
        out.extend(data)
        if len(data) < 100 or (stop and data and stop(data[-1])):
            return out, None
    return out, f"truncated at {MAX_PAGES} pages"


# ------------------------------------------------------------------ pure helpers


def ts(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def within(value: str | None, start: datetime, end: datetime) -> bool:
    t = ts(value)
    return t is not None and start <= t < end


def ready_at(created_at: str, events: list[dict], merged_at: str) -> datetime:
    """Latest ready_for_review event before the merge, else the creation time."""
    merged = ts(merged_at)
    marks = [ts(e["created_at"]) for e in events if e.get("event") == "ready_for_review"]
    marks = [m for m in marks if m is not None and (merged is None or m <= merged)]
    return max(marks) if marks else ts(created_at)


def classify_runs(conclusions: list[str | None]) -> str:
    if not conclusions:
        return "none"
    if any(c is None for c in conclusions):
        return "pending"
    if any(c in BAD for c in conclusions):
        return "fail"
    return "pass" if all(c in GOOD for c in conclusions) else "other"


def median_hours(values: list[float]) -> str:
    return f"{statistics.median(values):.1f}" if values else "n/a"


# ------------------------------------------------------------------ measurements


def first_run_ci(api: Api, repo: str, pr: dict) -> tuple[str, str]:
    code, data = api.get(f"/repos/{repo}/actions/runs",
                         {"event": "pull_request", "branch": pr["head"]["ref"], "per_page": 100}, "ci-runs-by-branch")
    if code != 200 or not isinstance(data, dict):
        return "unavailable", f"HTTP {code}"
    runs = [r for r in data.get("workflow_runs", [])
            if any(p.get("number") == pr["number"] for p in (r.get("pull_requests") or []))]
    if not runs:
        code, commits = api.get(f"/repos/{repo}/pulls/{pr['number']}/commits", {"per_page": 100}, "ci-pr-commits")
        shas = {c["sha"] for c in commits} if code == 200 and isinstance(commits, list) else set()
        runs = [r for r in data.get("workflow_runs", []) if r.get("head_sha") in shas]
    if not runs:
        return "none", ""
    first_sha = min(runs, key=lambda r: r["created_at"])["head_sha"]
    concl: list[str | None] = []
    for r in (x for x in runs if x["head_sha"] == first_sha):
        if r.get("run_attempt", 1) > 1:
            c2, att = api.get(f"/repos/{repo}/actions/runs/{r['id']}/attempts/1", None, "ci-first-attempt")
            if c2 != 200 or not isinstance(att, dict):
                return "unavailable", f"HTTP {c2}"
            r = att
        concl.append(r.get("conclusion") if r.get("status") == "completed" else None)
    return classify_runs(concl), first_sha[:7]


def measure_repo(api: Api, repo: str, start: datetime, end: datetime) -> dict:
    res: dict = {"repo": repo, "errors": []}
    pulls, err = paged(api, f"/repos/{repo}/pulls", {"state": "all", "sort": "updated", "direction": "desc"},
                       "pulls-list", stop=lambda p: (ts(p["updated_at"]) or start) < start)
    if err and not pulls:
        res["errors"].append(f"pull request list: {err}")
        return res
    if err:
        res["errors"].append(f"pull request list: {err}")
    opened = [p for p in pulls if within(p["created_at"], start, end)]
    merged = [p for p in pulls if within(p.get("merged_at"), start, end)]
    closed = [p for p in pulls if p.get("closed_at") and not p.get("merged_at") and within(p["closed_at"], start, end)]
    res.update(opened=[p["number"] for p in opened], merged=[p["number"] for p in merged],
               closed_unmerged=[p["number"] for p in closed],
               still_open=[p["number"] for p in opened if p["state"] == "open"],
               bot_opened=[p["number"] for p in opened if (p.get("user") or {}).get("type") == "Bot"])
    ci: dict[str, list[int]] = {"pass": [], "fail": [], "pending": [], "none": [], "other": [], "unavailable": []}
    for p in opened:
        verdict, _ = first_run_ci(api, repo, p)
        ci[verdict].append(p["number"])
    res["ci"] = ci
    hours: list[float] = []
    for p in merged:
        code, events = api.get(f"/repos/{repo}/issues/{p['number']}/events", {"per_page": 100}, "pr-events")
        if code != 200 or not isinstance(events, list):
            res["errors"].append(f"events for #{p['number']}: HTTP {code}")
            continue
        r = ready_at(p["created_at"], events, p["merged_at"])
        hours.append((ts(p["merged_at"]) - r).total_seconds() / 3600)
    res["hours"] = hours
    reverts_pr = [p["number"] for p in opened if re.match(r"(?i)^revert\b", p.get("title") or "")]
    seen: dict[str, str] = {}
    for branch in ("develop", "main"):
        commits, cerr = paged(api, f"/repos/{repo}/commits",
                              {"sha": branch, "since": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
                               "until": end.strftime("%Y-%m-%dT%H:%M:%SZ")}, "commits-by-branch")
        if cerr and not commits:
            if cerr != "HTTP 404" and cerr != "HTTP 422":
                res["errors"].append(f"commits on {branch}: {cerr}")
            continue
        for c in commits:
            subject = (c["commit"]["message"] or "").splitlines()[0]
            if re.match(r"(?i)^revert\b", subject):
                seen[c["sha"]] = subject
    res["reverts_pr"] = reverts_pr
    res["reverts_commit"] = sorted(s[:7] for s in seen)
    return res


# ------------------------------------------------------------------ output


def fmt_ci(ci: dict[str, list[int]]) -> str:
    done = len(ci["pass"]) + len(ci["fail"]) + len(ci["other"])
    extra = [f"{len(ci[k])} {k}" for k in ("none", "pending", "unavailable") if ci[k]]
    return f"{len(ci['pass'])} of {done}" + (f" ({', '.join(extra)})" if extra else "")


def render(results: list[dict], start: datetime, end: datetime, api: Api, now: datetime) -> str:
    L: list[str] = []
    L.append("# Scorecard")
    L.append("")
    L.append(f"Window: {start:%Y-%m-%d %H:%M}Z to {end:%Y-%m-%d %H:%M}Z (UTC, end exclusive). Generated {now:%Y-%m-%d %H:%M}Z.")
    L.append("Repositories: " + ", ".join(r["repo"] for r in results) + ".")
    L.append("No targets are set. Every number is computed from the queries listed under Queries.")
    L.append("Internal use: these numbers support no public claims. The ready-to-merge median is merge speed, not review depth.")
    L.append("")
    L.append("| Repository | Opened | Merged | Closed unmerged | Still open | Bot-opened | First-run CI pass | Median hours, ready to merge (n) | Reverts (PR / commit) |")
    L.append("|---|---|---|---|---|---|---|---|---|")
    tot = Counter()
    pooled: list[float] = []
    pooled_ci = {"pass": 0, "fail": 0, "other": 0}
    for r in results:
        if "opened" not in r:
            L.append("| " + " | ".join([r["repo"], "unavailable"] + [""] * 7) + " |")
            continue
        for key in ("opened", "merged", "closed_unmerged", "still_open", "bot_opened"):
            tot[key] += len(r[key])
        pooled += r["hours"]
        for k in pooled_ci:
            pooled_ci[k] += len(r["ci"][k])
        tot["rev_pr"] += len(r["reverts_pr"])
        tot["rev_c"] += len(r["reverts_commit"])
        L.append(f"| {r['repo']} | {len(r['opened'])} | {len(r['merged'])} | {len(r['closed_unmerged'])} | {len(r['still_open'])} "
                 f"| {len(r['bot_opened'])} | {fmt_ci(r['ci'])} | {median_hours(r['hours'])} ({len(r['hours'])}) "
                 f"| {len(r['reverts_pr'])} / {len(r['reverts_commit'])} |")
    done = sum(pooled_ci.values())
    L.append(f"| **All** | {tot['opened']} | {tot['merged']} | {tot['closed_unmerged']} | {tot['still_open']} | {tot['bot_opened']} "
             f"| {pooled_ci['pass']} of {done} | {median_hours(pooled)} ({len(pooled)}) "
             f"| {tot['rev_pr']} / {tot['rev_c']} |")
    L.append("")
    L.append("## Detail")
    for r in results:
        if "opened" not in r:
            continue
        L.append(f"- {r['repo']}: opened {r['opened'] or '-'}; merged {r['merged'] or '-'}; closed unmerged {r['closed_unmerged'] or '-'}")
        L.append(f"  - first-run CI: pass {r['ci']['pass'] or '-'}, fail {r['ci']['fail'] or '-'}, no run {r['ci']['none'] or '-'}, "
                 f"pending {r['ci']['pending'] or '-'}, unavailable {r['ci']['unavailable'] or '-'}")
        if r["reverts_pr"] or r["reverts_commit"]:
            L.append(f"  - reverts: PRs {r['reverts_pr'] or '-'}, commits {r['reverts_commit'] or '-'}")
    errs = [f"{r['repo']}: {e}" for r in results for e in r["errors"]]
    L.append("")
    L.append("## Unavailable or partial")
    L.extend([f"- {e}" for e in errs] or ["- none"])
    L.append("")
    L.append("## Definitions")
    L.extend([
        "- Opened: `created_at` inside the window. Merged: `merged_at` inside the window. Closed unmerged: `closed_at` inside the window and no `merged_at`. Still open: opened in the window and open now.",
        "- First-run CI pass: for each PR opened in the window, the earliest `pull_request` workflow runs on the first head SHA that has runs, at attempt 1. Pass means every such run is success, skipped or neutral. Counts are out of PRs that had a finished first run. PRs with no run, pending, or unavailable are listed beside it, not counted as pass or fail. Only GitHub Actions runs are seen, not checks posted by apps.",
        "- Median hours, ready to merge: for PRs merged in the window, `merged_at` minus the latest `ready_for_review` event, else `created_at`. The All row is the median of all PRs pooled, not a median of medians. It measures how fast PRs are merged, not how deeply they are reviewed: a merge with no review counts the same as one with a long review.",
        "- Reverts: PRs opened in the window whose title starts with Revert, and commits on develop or main with a committer date in the window whose subject starts with Revert, de-duplicated by SHA.",
    ])
    L.append("")
    L.append("## Queries")
    L.append("All requests are GET. Repository and numbers vary; the first URL of each kind is shown with the number of requests made.")
    for label, url in api.first_url.items():
        L.append(f"- `{label}` x{api.calls[label]}: `{url}`")
    L.append(f"- Total requests: {sum(api.calls.values())}. Rate limit remaining at the end: {api.remaining or 'unknown (no header seen)'}.")
    return "\n".join(L) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repos", nargs="+", default=DEFAULT_REPOS, help="owner/name, one or more")
    ap.add_argument("--days", type=int, help="window of N days ending now")
    ap.add_argument("--since", help="UTC date YYYY-MM-DD, inclusive")
    ap.add_argument("--until", help="UTC date YYYY-MM-DD, exclusive (default: now)")
    args = ap.parse_args(argv)
    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    if args.days:
        start, end = now - timedelta(days=args.days), now
    elif args.since:
        start = datetime.strptime(args.since, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        end = datetime.strptime(args.until, "%Y-%m-%d").replace(tzinfo=timezone.utc) if args.until else now
    else:
        ap.error("give --days N or --since DATE")
    api = Api(os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN"))
    results = [measure_repo(api, repo, start, end) for repo in args.repos]
    sys.stdout.write(render(results, start, end, api, now))
    return 0


if __name__ == "__main__":
    sys.exit(main())
