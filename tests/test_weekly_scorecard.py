"""Tests for scripts/weekly_scorecard.py. No network: a fake Api answers from canned data."""

from __future__ import annotations

import importlib.util
import re
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location("weekly_scorecard", ROOT / "scripts/weekly_scorecard.py")
sc = importlib.util.module_from_spec(SPEC)
sys.modules["weekly_scorecard"] = sc
SPEC.loader.exec_module(sc)

UTC = timezone.utc
START = datetime(2026, 11, 12, tzinfo=UTC)
END = datetime(2026, 11, 26, tzinfo=UTC)


class FakeApi(sc.Api):
    """Answers GET paths from a dict of prefix -> (status, data). Records every request."""

    def __init__(self, routes):
        super().__init__(None)
        self.routes = routes

    def get(self, path, params=None, label=""):
        self.calls[label or path] += 1
        self.first_url.setdefault(label or path, path)
        matches = [p for p in self.routes if path.startswith(p)]
        if not matches:
            return 404, None
        answer = self.routes[max(matches, key=len)]
        return answer(path, params) if callable(answer) else answer


def pr(n, created, merged=None, closed=None, state="closed", title="t", user="u", ref=None):
    return {"number": n, "created_at": created, "merged_at": merged, "closed_at": closed or merged,
            "updated_at": merged or closed or created, "state": state, "title": title,
            "user": {"type": user}, "head": {"ref": ref or f"b{n}"}}


class Helpers(unittest.TestCase):
    def test_window_is_half_open(self):
        self.assertTrue(sc.within("2026-11-12T00:00:00Z", START, END))
        self.assertFalse(sc.within("2026-11-26T00:00:00Z", START, END))
        self.assertFalse(sc.within(None, START, END))

    def test_median(self):
        self.assertEqual(sc.median_hours([1, 2, 10]), "2.0")
        self.assertEqual(sc.median_hours([1, 2]), "1.5")
        self.assertEqual(sc.median_hours([]), "n/a")

    def test_ready_at_uses_latest_event_before_merge(self):
        ev = [{"event": "ready_for_review", "created_at": "2026-11-13T10:00:00Z"},
              {"event": "convert_to_draft", "created_at": "2026-11-13T11:00:00Z"},
              {"event": "ready_for_review", "created_at": "2026-11-14T09:00:00Z"},
              {"event": "ready_for_review", "created_at": "2026-11-20T00:00:00Z"}]
        got = sc.ready_at("2026-11-13T08:00:00Z", ev, "2026-11-14T12:00:00Z")
        self.assertEqual(got, datetime(2026, 11, 14, 9, tzinfo=UTC))
        self.assertEqual(sc.ready_at("2026-11-13T08:00:00Z", [], "2026-11-14T12:00:00Z"), datetime(2026, 11, 13, 8, tzinfo=UTC))

    def test_classify(self):
        self.assertEqual(sc.classify_runs([]), "none")
        self.assertEqual(sc.classify_runs(["success", "skipped"]), "pass")
        self.assertEqual(sc.classify_runs(["success", "failure"]), "fail")
        self.assertEqual(sc.classify_runs(["success", None]), "pending")
        self.assertEqual(sc.classify_runs(["success", "weird"]), "other")


class FirstRun(unittest.TestCase):
    def run_for(self, runs, attempts=None):
        routes = {
            "/repos/o/r/actions/runs/": lambda p, q: (200, (attempts or {}).get(p)),
            "/repos/o/r/actions/runs": (200, {"workflow_runs": runs}),
        }
        return sc.first_run_ci(FakeApi(routes), "o/r", {"number": 7, "head": {"ref": "b7"}})

    def run_obj(self, id_, sha, created, concl, attempt=1, status="completed", prs=(7,)):
        return {"id": id_, "head_sha": sha * 40, "created_at": created, "conclusion": concl,
                "run_attempt": attempt, "status": status, "pull_requests": [{"number": n} for n in prs]}

    def test_uses_first_push_not_latest(self):
        runs = [self.run_obj(1, "a", "2026-11-13T00:00:00Z", "failure"),
                self.run_obj(2, "b", "2026-11-14T00:00:00Z", "success")]
        self.assertEqual(self.run_for(runs)[0], "fail")

    def test_rerun_reads_attempt_one(self):
        runs = [self.run_obj(1, "a", "2026-11-13T00:00:00Z", "success", attempt=2)]
        att = {"/repos/o/r/actions/runs/1/attempts/1": {"status": "completed", "conclusion": "failure"}}
        self.assertEqual(self.run_for(runs, att)[0], "fail")

    def test_other_prs_on_same_branch_name_are_ignored(self):
        runs = [self.run_obj(1, "a", "2026-11-13T00:00:00Z", "failure", prs=(99,))]
        # no run belongs to #7 and the commits route is absent, so there is nothing to attribute
        self.assertEqual(self.run_for(runs)[0], "none")

    def test_pending_and_unavailable(self):
        runs = [self.run_obj(1, "a", "2026-11-13T00:00:00Z", None, status="in_progress")]
        self.assertEqual(self.run_for(runs)[0], "pending")
        api = FakeApi({"/repos/o/r/actions/runs": (403, None)})
        self.assertEqual(sc.first_run_ci(api, "o/r", {"number": 7, "head": {"ref": "b"}})[0], "unavailable")


class MeasureRepo(unittest.TestCase):
    def test_counts_and_cohorts(self):
        pulls = [
            pr(1, "2026-11-13T00:00:00Z", merged="2026-11-14T00:00:00Z", user="User"),
            pr(2, "2026-11-10T00:00:00Z", merged="2026-11-13T00:00:00Z"),           # opened before, merged inside
            pr(3, "2026-11-15T00:00:00Z", closed="2026-11-16T00:00:00Z", title="Revert x"),
            pr(4, "2026-11-20T00:00:00Z", state="open", user="Bot"),
            pr(5, "2026-11-30T00:00:00Z"),                                           # after the window
        ]
        routes = {
            "/repos/o/r/pulls": (200, pulls),
            "/repos/o/r/pulls/": (200, []),
            "/repos/o/r/actions/runs": (200, {"workflow_runs": []}),
            "/repos/o/r/issues/": (200, []),
            "/repos/o/r/commits": lambda p, q: (200, [{"sha": "abcdef1234", "commit": {"message": "Revert \"x\" (#3)\n\nbody"}}])
            if q["sha"] == "main" else (404, None),
        }
        res = sc.measure_repo(FakeApi(routes), "o/r", START, END)
        self.assertEqual(res["opened"], [1, 3, 4])
        self.assertEqual(res["merged"], [1, 2])
        self.assertEqual(res["closed_unmerged"], [3])
        self.assertEqual(res["still_open"], [4])
        self.assertEqual(res["bot_opened"], [4])
        self.assertEqual(res["reverts_pr"], [3])
        self.assertEqual(res["reverts_commit"], ["abcdef1"])
        # PR 1: created 11-13, merged 11-14 = 24 h. PR 2: created 11-10, merged 11-13 = 72 h.
        self.assertEqual(sorted(round(h) for h in res["hours"]), [24, 72])
        self.assertEqual(res["ci"]["none"], [1, 3, 4])
        self.assertEqual(res["errors"], [])

    def test_failed_list_is_unavailable_not_zero(self):
        res = sc.measure_repo(FakeApi({"/repos/o/r/pulls": (403, None)}), "o/r", START, END)
        self.assertNotIn("opened", res)
        self.assertTrue(res["errors"])
        out = sc.render([res], START, END, FakeApi({}), END)
        self.assertIn("| o/r | unavailable", out)


class Output(unittest.TestCase):
    """The printed scorecard: its columns, and the notes that keep it internal."""

    def scorecard(self):
        pulls = [pr(1, "2026-11-13T00:00:00Z", merged="2026-11-14T00:00:00Z"), pr(2, "2026-11-15T00:00:00Z", state="open")]
        routes = {
            "/repos/o/r/pulls": (200, pulls),
            "/repos/o/r/pulls/": (200, []),
            "/repos/o/r/actions/runs": (200, {"workflow_runs": []}),
            "/repos/o/r/issues/": (200, []),
            "/repos/o/r/commits": (404, None),
        }
        ok = sc.measure_repo(FakeApi(routes), "o/r", START, END)
        failed = sc.measure_repo(FakeApi({"/repos/o/bad/pulls": (403, None)}), "o/bad", START, END)
        return sc.render([ok, failed], START, END, FakeApi({}), END)

    def test_no_unverified_column_or_text(self):
        self.assertNotIn("unverified", self.scorecard().lower())

    def test_every_table_row_has_the_same_number_of_cells(self):
        rows = [line for line in self.scorecard().splitlines() if line.startswith("|")]
        self.assertGreaterEqual(len(rows), 5)  # header, rule, one repo, one unavailable repo, All
        cells = {len(re.findall(r"(?<!\\)\|", line)) for line in rows}
        self.assertEqual(len(cells), 1, cells)
        self.assertEqual(cells.pop() - 1, 9)

    def test_output_says_internal_and_merge_speed_not_review_depth(self):
        out = self.scorecard()
        self.assertIn("Internal use", out)
        self.assertIn("merge speed, not review depth", out)
        self.assertIn("not how deeply they are reviewed", out)

    def test_help_text_carries_the_same_notes(self):
        import contextlib
        import io
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), self.assertRaises(SystemExit):
            sc.main(["--help"])
        text = " ".join(buf.getvalue().split())
        self.assertIn("Internal use", text)
        self.assertIn("maintainer's merge speed", text)
        self.assertIn("does not measure review depth", text)
        self.assertIn("sets no targets and supports no public claims", text)


class Safety(unittest.TestCase):
    def test_only_get(self):
        src = Path(sc.__file__).read_text()
        self.assertIn('method="GET"', src)
        for banned in ("method=\"POST\"", "method=\"PUT\"", "method=\"PATCH\"", "method=\"DELETE\"", "data="):
            self.assertNotIn(banned, src)

    def test_no_em_dash(self):
        self.assertNotIn(chr(0x2014), Path(sc.__file__).read_text())


if __name__ == "__main__":
    unittest.main()
