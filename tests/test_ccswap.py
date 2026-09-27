"""Tests for ccswap's scheduling, bookkeeping and install logic (stdlib only).

Run: python3 -m unittest discover -s tests -v
"""
import importlib.machinery
import importlib.util
import io
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path

HERE = Path(__file__).resolve().parent
TMP = Path(tempfile.mkdtemp(prefix="ccswap-test-"))
os.environ["CCSWAP_HOME"] = str(TMP / "home")
os.environ["CCSWAP_CLAUDE_DIR"] = str(TMP / "claude")
os.environ.pop("CCSWAP_SLOT", None)
os.environ.pop("CLAUDE_CONFIG_DIR", None)

loader = importlib.machinery.SourceFileLoader("ccswap", str(HERE.parent / "bin" / "ccswap"))
spec = importlib.util.spec_from_loader("ccswap", loader)
ccswap = importlib.util.module_from_spec(spec)
loader.exec_module(ccswap)

H = 3600


class Base(unittest.TestCase):
    def setUp(self):
        shutil.rmtree(TMP, ignore_errors=True)
        (TMP / "claude").mkdir(parents=True)
        ccswap.ROOT.mkdir(parents=True)
        self.now = time.time()

    def accounts(self, spec, default=None, caps=None, others=None):
        """spec: name -> (5h used %, hours to 5h reset or None if idle, 7d used %, hours to 7d reset)."""
        for name, (f5, h5, f7, h7) in spec.items():
            cfg = ccswap.config_dir(name)
            cfg.mkdir(parents=True)
            (cfg / ".credentials.json").write_text(json.dumps({"claudeAiOauth": {"refreshToken": "x"}}))
            (cfg / ".claude.json").write_text(json.dumps({"oauthAccount": {"emailAddress": f"{name}@x"}}))
            st = {}
            if h5 is not None:
                st["five_hour"] = {"used_percentage": f5, "resets_at": self.now + h5 * H}
            if h7 is not None:
                st["seven_day"] = {"used_percentage": f7, "resets_at": self.now + h7 * H}
            ccswap.write_json(ccswap.STATE / f"{name}.json", st)
        ccswap.save_settings({"default": default, "weekly_cap": caps or {}, "others_cap": others})


class Picking(Base):
    def test_weekly_about_to_reset_wins(self):
        self.accounts({"a": (10, 4, 30, 100), "b": (0, None, 40, 6)})
        self.assertEqual(ccswap.pick(), "b")

    def test_running_window_beats_idle_account(self):
        self.accounts({"a": (50, 1, 20, 100), "b": (0, None, 0, 160)})
        self.assertEqual(ccswap.pick(), "a")

    def test_weekly_nearly_gone_is_deprioritised(self):
        self.accounts({"a": (0, 4.9, 97, 120), "b": (30, 3, 40, 120)})
        self.assertEqual(ccswap.pick(), "b")

    def test_spent_account_skipped(self):
        self.accounts({"a": (99.5, 2, 50, 50), "b": (10, 4, 50, 150)})
        self.assertEqual(ccswap.pick(), "b")

    def test_tie_at_pace_cap_prefers_sooner_loss(self):
        self.accounts({"a": (0, 0.5, 10, 100), "b": (0, 4.8, 10, 100)})
        self.assertEqual(ccswap.pick(), "a")

    def test_all_spent(self):
        self.accounts({"a": (99.5, 2, 50, 50), "b": (10, 4, 99.9, 100)})
        self.assertIsNone(ccswap.pick())

    def test_reset_window_counts_as_fresh(self):
        self.accounts({"a": (100, -1, 50, 50)})  # 5h window already reset
        self.assertEqual(ccswap.pick(), "a")


class Rebalancing(Base):
    def test_no_switch_for_marginal_gain(self):
        self.accounts({"a": (30, 3, 40, 100), "b": (35, 2.8, 40, 100)})
        self.assertIsNone(ccswap.better_account("a", self.now))

    def test_no_switch_before_spent_even_if_other_expires_sooner(self):
        self.accounts({"a": (30, 4, 20, 150), "b": (10, 4, 30, 8)})
        self.assertIsNone(ccswap.better_account("a", self.now))

    def test_no_switch_to_account_without_session_room(self):
        self.accounts({"a": (30, 4, 20, 150), "b": (98.5, 4, 30, 8)})
        self.assertIsNone(ccswap.better_account("a", self.now))


class DefaultAndCaps(Base):
    def test_default_first_even_if_others_more_urgent(self):
        self.accounts({"me": (0, None, 10, 150), "b": (50, 0.5, 20, 5)}, default="me")
        self.assertEqual(ccswap.pick(), "me")

    def test_default_spent_falls_back(self):
        self.accounts({"me": (0, None, 99.2, 50), "b": (10, 4, 20, 100)}, default="me")
        self.assertEqual(ccswap.pick(), "b")

    def test_others_cap(self):
        self.accounts({"me": (0, None, 99.5, 50), "b": (10, 4, 90.5, 100), "c": (20, 3, 50, 100)},
                      default="me", others=90)
        self.assertEqual(ccswap.pick(), "c")

    def test_under_others_cap_still_usable(self):
        self.accounts({"me": (0, None, 99.5, 50), "b": (10, 4, 89, 20)}, default="me", others=90)
        self.assertEqual(ccswap.pick(), "b")

    def test_default_not_limited_by_others_cap(self):
        self.accounts({"me": (0, None, 98, 50), "b": (10, 4, 20, 100)}, default="me", others=90)
        self.assertEqual(ccswap.pick(), "me")

    def test_per_account_cap_override(self):
        self.accounts({"me": (0, None, 99.5, 50), "c": (10, 4, 72, 100), "b": (10, 4, 30, 100)},
                      default="me", caps={"c": 70})
        self.assertEqual(ccswap.pick(), "b")

    def test_return_to_default_when_it_frees_up(self):
        self.accounts({"me": (0, None, 0, 168), "b": (10, 4, 20, 100)}, default="me")
        self.assertEqual(ccswap.better_account("b", self.now), "me")

    def test_never_leave_default_with_room(self):
        self.accounts({"me": (30, 4, 50, 100), "b": (0, 0.3, 10, 3)}, default="me")
        self.assertIsNone(ccswap.better_account("me", self.now))

    def test_scoped_model_limit_blocks_only_that_model(self):
        self.accounts({"a": (10, 4, 20, 100), "b": (10, 4, 20, 100)})
        st = ccswap.state("a")
        st["scoped"] = [{"model": "Fable", "percent": 100, "resets_at": self.now + 50 * H}]
        ccswap.write_json(ccswap.STATE / "a.json", st)
        ccswap.write_json(ccswap.STATE / "_model.json", {"model": "Opus 5.5"})
        self.assertFalse(ccswap.blocked_until("a", self.now))
        ccswap.write_json(ccswap.STATE / "_model.json", {"model": "Fable 5.1"})
        self.assertTrue(ccswap.blocked_until("a", self.now))


class Bookkeeping(Base):
    def test_merge_never_goes_down_within_a_window(self):
        old = {"used_percentage": 40, "resets_at": self.now + H}
        new = {"used_percentage": 35, "resets_at": self.now + H + 5}
        self.assertEqual(ccswap.merge_window(old, new, self.now)["used_percentage"], 40)

    def test_merge_ignores_older_window(self):
        old = {"used_percentage": 5, "resets_at": self.now + 5 * H}
        new = {"used_percentage": 90, "resets_at": self.now + H}
        self.assertEqual(ccswap.merge_window(old, new, self.now), old)

    def test_merge_accepts_new_window(self):
        old = {"used_percentage": 90, "resets_at": self.now - 10}
        new = {"used_percentage": 2, "resets_at": self.now + 5 * H}
        self.assertEqual(ccswap.merge_window(old, new, self.now), new)

    def test_numbers_from_previous_account_are_not_recorded(self):
        self.accounts({"a": (60, 2, 70, 50), "b": (0, None, 10, 100)})
        stale = {w: ccswap.state("a")[w] for w in ("five_hour", "seven_day")}
        ccswap.record_rate_limits("b", stale, self.now)
        self.assertNotIn("five_hour", ccswap.state("b"))

    def test_numbers_for_this_account_are_recorded(self):
        self.accounts({"a": (60, 2, 70, 50), "b": (10, 3, 10, 100)})
        mine = {"five_hour": {"used_percentage": 15, "resets_at": ccswap.state("b")["five_hour"]["resets_at"]},
                "seven_day": {"used_percentage": 11, "resets_at": ccswap.state("b")["seven_day"]["resets_at"]}}
        ccswap.record_rate_limits("b", mine, self.now)
        self.assertEqual(ccswap.state("b")["five_hour"]["used_percentage"], 15)

    def test_ratio_is_learned(self):
        s = {"five_hour": {"used_percentage": 10, "resets_at": 1}, "seven_day": {"used_percentage": 50, "resets_at": 2}}
        for f5, f7 in [(20, 52), (40, 56), (60, 60)]:
            rl = {"five_hour": {"used_percentage": f5, "resets_at": 1},
                  "seven_day": {"used_percentage": f7, "resets_at": 2}}
            ccswap.learn_ratio(s, rl, learn_pace=False)
            s.update(rl)
        self.assertGreater(ccswap.ratio(s), ccswap.K_PRIOR)


class Install(Base):
    def test_install_keeps_existing_statusline_and_hooks(self):
        sp = ccswap.settings_path()
        sp.write_text(json.dumps({"statusLine": {"type": "command", "command": "my-line"},
                                  "hooks": {"StopFailure": [{"hooks": [{"type": "command", "command": "other"}]}]}}))
        with redirect_stdout(io.StringIO()):
            ccswap.cmd_install()
            ccswap.cmd_install()  # idempotent
        data = json.loads(sp.read_text())
        self.assertIn("_statusline", data["statusLine"]["command"])
        self.assertEqual(data["statusLine"]["refreshInterval"], ccswap.STATUS_REFRESH)
        self.assertEqual(ccswap.settings()["chained_statusline"], "my-line")
        cmds = [h["command"] for e in data["hooks"]["StopFailure"] for h in e["hooks"]]
        self.assertEqual(sum("_hook" in c for c in cmds), 1)
        self.assertIn("other", cmds)
        with redirect_stdout(io.StringIO()):
            ccswap.cmd_uninstall(purge=False)
        data = json.loads(sp.read_text())
        self.assertEqual(data["statusLine"]["command"], "my-line")
        self.assertEqual([h["command"] for e in data["hooks"]["StopFailure"] for h in e["hooks"]], ["other"])

    def test_install_refuses_broken_settings(self):
        ccswap.settings_path().write_text("{not json")
        with self.assertRaises(SystemExit):
            ccswap.cmd_install()


class Slots(Base):
    def test_slot_points_at_account_and_links_shared_files(self):
        (TMP / "claude" / "settings.json").write_text("{}")
        (TMP / "claude" / "projects").mkdir()
        self.accounts({"a": (0, None, 0, 100), "b": (0, None, 0, 100)})
        slot = ccswap.acquire_slot()
        ccswap.prepare_slot(slot, "a")
        link = slot / "config" / ".credentials.json"
        self.assertEqual(Path(os.readlink(link)), ccswap.creds("a"))
        self.assertTrue((slot / "config" / "projects").is_symlink())
        ccswap.point_slot(slot, "b")
        self.assertEqual(Path(os.readlink(link)), ccswap.creds("b"))
        self.assertEqual(ccswap.current_account.__name__, "current_account")

    def test_emptied_credentials_are_dropped_not_saved(self):
        self.accounts({"a": (0, None, 0, 100)})
        slot = ccswap.acquire_slot()
        ccswap.prepare_slot(slot, "a")
        link = slot / "config" / ".credentials.json"
        link.unlink()
        link.write_text(json.dumps({"claudeAiOauth": {"accessToken": "", "refreshToken": "", "expiresAt": 0}}))
        before = ccswap.creds("a").read_text()
        ccswap.sync_creds(slot)
        self.assertTrue(link.is_symlink())
        self.assertEqual(ccswap.creds("a").read_text(), before)


def tearDownModule():
    shutil.rmtree(TMP, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
