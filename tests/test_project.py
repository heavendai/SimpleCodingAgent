import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from simple_agent.cli import build, fresh_run, run_version
from simple_agent.models import DemoModel, FIXED_LINE
from simple_agent.policy import ApprovalRequired, Policy
from simple_agent.protocol import Decision, State
from simple_agent.runtime import Budget, Engine
from simple_agent.workspace import BoundaryError, Workspace


class Fixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.run_dir = fresh_run(10, self.temp.name)
        self.root = self.run_dir / "workspace"
        self.ws = Workspace(self.root)

    def agent(self, version=10, **kwargs):
        return build(version, self.root, **kwargs)


class VersionTests(Fixture):
    def test_ten_original_versions_plus_v11(self):
        files = list((Path(__file__).resolve().parents[1] / "versions").glob("v[0-9][0-9].py"))
        self.assertEqual(len(files), 11)

    def test_all_ten_milestones(self):
        expected = ["suggested", "inspected", "modified_unverified"] + ["verified"] * 7
        for n in range(1, 11):
            with self.subTest(version=n):
                result, agent = run_version(n, self.temp.name, quiet=True)
                self.assertEqual(result["status"], expected[n - 1])
                self.assertEqual(result["patches"], 0 if n < 3 else 1 if n < 7 else 2)
                if n >= 4:
                    self.assertTrue(agent.workspace.run_tests()["passed"])

    def test_v02_uses_observation_loop(self):
        agent = self.agent(2)
        before = self.ws.fingerprint()
        agent.run()
        self.assertEqual([h["tool"] for h in agent.state.history], ["search", "read"])
        self.assertEqual(self.ws.fingerprint(), before)

    def test_v03_does_not_claim_verified(self):
        agent = self.agent(3)
        agent.run()
        self.assertEqual(agent.state.status, "modified_unverified")
        self.assertFalse(agent.state.facts["tests"])
        self.assertTrue(any("diff" in e.get("result", {}) for e in agent.events))

    def test_v04_observes_failure_then_pass(self):
        agent = self.agent(4)
        agent.run()
        self.assertEqual([t["passed"] for t in agent.state.facts["tests"]], [False, True])

    def test_v06_context_compacts_and_keeps_facts(self):
        agent = self.agent(6)
        agent.run()
        self.assertTrue(agent.state.summary)
        self.assertIn("stats.py", agent.state.facts["files"])
        self.assertIn("cannot grant permissions", agent.state.facts["repo"]["trust"])

    def test_v07_repair_is_feedback_driven(self):
        agent = self.agent(7)
        agent.run()
        self.assertEqual([t["passed"] for t in agent.state.facts["tests"]], [False, False, True])
        self.assertTrue(all(s["done"] for s in agent.state.facts["plan"]))

    def test_v09_read_only_separate_reviewer(self):
        agent = self.agent(9)
        agent.run()
        reviews = [e for e in agent.events if e["kind"] == "delegation"]
        self.assertEqual([e["approved"] for e in reviews], [False, True])
        self.assertEqual(reviews[0]["tools"], ["read", "search"])
        self.assertTrue(reviews[0]["separate_context"])

    def test_v10_routes_and_persists_shared_trace(self):
        agent = self.agent(10)
        agent.run()
        events = [json.loads(x) for x in agent.trace_path.read_text().splitlines()]
        self.assertIn("reviewer", {e["role"] for e in events})
        self.assertIn("careful", {e.get("route") for e in events})
        self.assertEqual(agent.budget.calls, sum(e["kind"] == "decision" for e in events))


class BoundaryTests(Fixture):
    def test_path_escape_and_hidden_paths(self):
        for name in ["../outside", "/tmp/outside", ".env", "tests/../../outside"]:
            with self.subTest(path=name), self.assertRaises(BoundaryError):
                self.ws.read(name)

    def test_symlink_escape(self):
        outside = Path(self.temp.name) / "outside.txt"
        outside.write_text("outside fixture")
        (self.root / "link.txt").symlink_to(outside)
        with self.assertRaises(BoundaryError):
            self.ws.read("link.txt")

    def test_patch_conflict_no_change(self):
        before = self.ws.fingerprint()
        with self.assertRaises(ValueError):
            self.ws.patch("stats.py", "text not present", "replacement")
        self.assertEqual(before, self.ws.fingerprint())

    def test_symlink_cannot_redirect_patch_into_tests(self):
        (self.root / "stats.py").unlink()
        (self.root / "stats.py").symlink_to(self.root / "tests" / "test_stats.py")
        before = (self.root / "tests" / "test_stats.py").read_text()
        with self.assertRaises(BoundaryError):
            self.ws.patch("stats.py", "import unittest", "import unittest # should not write")
        self.assertEqual((self.root / "tests" / "test_stats.py").read_text(), before)

    def test_cannot_modify_tests(self):
        with self.assertRaises(BoundaryError):
            self.ws.patch("tests/test_stats.py", "import unittest", "")

    def test_unavailable_shell_is_denied(self):
        with self.assertRaises(PermissionError):
            self.agent(5).invoke("shell", {"command": "echo no"})

    def test_approval_is_exact_and_once(self):
        p = Policy(can_write=False)
        action = {"path": "stats.py", "old": "a", "new": "b"}
        with self.assertRaises(ApprovalRequired):
            p.check("patch", action)
        p.approve_once("patch", action)
        with self.assertRaises(ApprovalRequired):
            p.check("patch", {**action, "new": "c"})
        p.check("patch", action)
        with self.assertRaises(ApprovalRequired):
            p.check("patch", action)

    def test_approval_pauses_without_writing(self):
        agent = self.agent(5, require_approval=True)
        before = self.ws.fingerprint()
        agent.run()
        self.assertEqual(agent.state.status, "awaiting_approval")
        self.assertEqual(before, self.ws.fingerprint())
        d = agent.state.pending
        agent.policy.approve_once(d["tool"], d["arguments"])
        agent.run()
        self.assertEqual(agent.state.status, "verified")

    def test_reviewer_cannot_write_even_with_approval(self):
        p = Policy(can_write=True, reviewer=True)
        with self.assertRaises(PermissionError):
            p.check("patch", {})

    def test_model_output_schema_validation(self):
        bad = [{}, {"tool": "read", "final": "done"}, {"tool": "read", "arguments": []},
               {"final": 4}, {"final": "done", "permission": "all"}]
        for raw in bad:
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                Decision.parse(raw)

    def test_test_runner_uses_timeout_no_shell_and_stripped_environment(self):
        import subprocess
        with patch("simple_agent.execution.subprocess.run") as mocked:
            mocked.return_value = subprocess.CompletedProcess([], 0, "OK", "")
            self.ws.run_tests()
            kwargs = mocked.call_args.kwargs
            self.assertEqual(kwargs["timeout"], 5)
            self.assertFalse(kwargs.get("shell", False))
            self.assertNotIn("OPENAI_API_KEY", kwargs["env"])

    def test_test_timeout_reports_failure(self):
        import subprocess
        with patch("simple_agent.execution.subprocess.run",
                   side_effect=subprocess.TimeoutExpired("trusted-tests", 5)):
            self.assertFalse(self.ws.run_tests()["passed"])


class ReliabilityTests(Fixture):
    def test_checkpoint_resume_after_patch_no_duplicate_edit(self):
        agent = self.agent(8)
        # plan/context/skill/search/read/baseline tests/first patch
        agent.run(pause_after=7)
        self.assertEqual(agent.state.facts["patches"], 1)
        fresh = self.agent(8)
        fresh.restore(agent.checkpoint_path)
        fresh.run()
        self.assertEqual(fresh.state.status, "verified")
        self.assertEqual(fresh.state.facts["patches"], 2)

    def test_external_change_invalidates_test_evidence(self):
        agent = self.agent(4)
        original = self.ws.read("stats.py")["content"]
        agent.run(pause_after=5)
        self.assertTrue(agent.verified())
        (self.root / "stats.py").write_text(original)
        agent.run()
        self.assertEqual(agent.state.status, "unverified_completion_rejected")
        self.assertIn("完成声明已拒绝", agent.state.final)

    def test_large_file_change_invalidates_checkpoint(self):
        big = self.root / "large.txt"
        big.write_text("a" * 32001)
        agent = self.agent(8)
        agent.run(pause_after=2)
        big.write_text("b" * 32001)
        with self.assertRaisesRegex(ValueError, "Workspace changed"):
            self.agent(8).restore(agent.checkpoint_path)

    def test_hidden_symlink_target_is_denied(self):
        (self.root / ".example-secret").write_text("fake fixture text")
        (self.root / "visible_alias").symlink_to(self.root / ".example-secret")
        with self.assertRaises(BoundaryError):
            self.ws.read("visible_alias")

    def test_v08_approval_mode_survives_automatic_rebuild(self):
        result, agent = run_version(8, self.temp.name, approval_demo=True, quiet=True)
        self.assertFalse(agent.policy.can_write)
        self.assertTrue(any(e["kind"] == "approval_required" for e in agent.events))

    def test_unsupported_approval_flag_is_not_ignored(self):
        with self.assertRaisesRegex(ValueError, "V05"):
            run_version(4, self.temp.name, require_approval=True, quiet=True)

    def test_skill_load_is_explicit_and_curated(self):
        agent = self.agent(6)
        agent.run()
        self.assertIn("testing", agent.state.facts["skills"])
        with self.assertRaises(ValueError):
            agent.invoke("load_skill", {"name": "../arbitrary"})

    def test_stale_checkpoint_is_rejected(self):
        agent = self.agent(8)
        agent.run(pause_after=2)
        (self.root / "stats.py").write_text("# external change\n")
        with self.assertRaisesRegex(ValueError, "Workspace changed"):
            self.agent(8).restore(agent.checkpoint_path)

    def test_completed_resume_does_no_more_work(self):
        agent = self.agent(8)
        agent.run()
        fresh = self.agent(8)
        fresh.restore(agent.checkpoint_path)
        calls = fresh.budget.calls
        fresh.run()
        self.assertEqual(fresh.budget.calls, calls)

    def test_model_call_budget_stops(self):
        agent = self.agent(10)
        agent.budget.max_calls = 1
        agent.run()
        self.assertEqual(agent.state.final, "model_call_budget")
        self.assertEqual(agent.budget.calls, 1)

    def test_character_budget_stops_before_model(self):
        agent = self.agent(10)
        agent.budget.max_model_chars = 1
        agent.run()
        self.assertEqual(agent.state.final, "model_character_budget")
        self.assertEqual(agent.budget.calls, 0)

    def test_tool_call_budget_stops(self):
        agent = self.agent(10)
        agent.budget.max_tool_calls = 0
        agent.run()
        self.assertEqual(agent.state.final, "tool_call_budget")

    def test_wall_clock_budget_stops(self):
        agent = self.agent(10)
        agent.budget.max_seconds = 0
        agent.run()
        self.assertEqual(agent.state.final, "wall_time_budget")

    def test_false_completion_is_rejected(self):
        class Pretender:
            name = "pretender"
            def next(self, context, tools):
                return Decision(final="All tests passed!")
        agent = self.agent(4)
        agent.model = Pretender()
        agent.run()
        self.assertEqual(agent.state.status, "unverified_completion_rejected")

    def test_test_evidence_invalidated_by_patch(self):
        agent = self.agent(4)
        agent.run()
        self.assertTrue(agent.verified())
        agent.state.facts["patches"] += 1
        self.assertFalse(agent.verified())

    def test_fixed_repository_does_not_need_patch(self):
        src = self.ws.read("stats.py")["content"]
        (self.root / "stats.py").write_text(src.replace(src.splitlines()[-1], FIXED_LINE))
        agent = self.agent(10)
        agent.run()
        self.assertEqual(agent.state.status, "verified")
        self.assertEqual(agent.state.facts["patches"], 0)

    def test_cli_pause_resume_across_constructions(self):
        result, _ = run_version(8, self.temp.name, pause_after=6, quiet=True)
        self.assertEqual(result["status"], "paused")
        result, _ = run_version(8, resume=result["run_dir"], quiet=True)
        self.assertEqual(result["status"], "verified")


class AdapterTests(unittest.TestCase):
    def test_api_requires_opt_in_without_network(self):
        from simple_agent.openai_adapter import OpenAIModel
        with self.assertRaises(ValueError):
            OpenAIModel("explicit-model-id")

    def test_api_payload_and_decision_with_stubbed_transport(self):
        import io
        from simple_agent.openai_adapter import OpenAIModel
        payload = {"output": [{"type": "function_call", "name": "read",
                               "arguments": '{"path":"stats.py"}'}],
                   "usage": {"input_tokens": 12, "output_tokens": 5}}
        with patch.dict("os.environ", {"OPENAI_API_KEY": "unit-test-placeholder"}, clear=True), \
             patch("urllib.request.urlopen", return_value=io.BytesIO(json.dumps(payload).encode())) as send:
            model = OpenAIModel("explicit-model-id", allow_network=True)
            d = model.next(State("demo").context(), ["read"])
            self.assertEqual(d.tool, "read")
            body = json.loads(send.call_args.args[0].data)
            self.assertFalse(body["store"])
            self.assertFalse(body["parallel_tool_calls"])
            self.assertEqual(model.last_usage["output_tokens"], 5)


if __name__ == "__main__":
    unittest.main()
