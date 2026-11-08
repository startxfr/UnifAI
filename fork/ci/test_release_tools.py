"""Self-test of fork/ci/release_images.py and release_notes.py. Run: python3 fork/ci/test_release_tools.py"""
import pathlib
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import release_images as ri  # noqa: E402
import release_notes as rn  # noqa: E402


class FindTag(unittest.TestCase):
    HISTORY = ["c3" * 20, "c2" * 20, "c1" * 20, "c0" * 20]

    def same_until(self, changed_at):
        """Code identical to HEAD for every commit newer than `changed_at` (its index in HISTORY)."""
        return lambda commit, head, paths: self.HISTORY.index(commit) < changed_at

    def test_newest_image_with_the_same_code(self):
        tags = {f"devel-{self.HISTORY[2][:9]}", f"devel-{self.HISTORY[3][:9]}"}
        got = ri.find_tag(self.HISTORY[0], ["x"], tags, self.HISTORY, self.same_until(4))
        self.assertEqual(got, f"devel-{self.HISTORY[2][:9]}")

    def test_an_image_of_older_code_is_not_taken(self):
        tags = {f"devel-{self.HISTORY[3][:9]}"}
        self.assertIsNone(ri.find_tag(self.HISTORY[0], ["x"], tags, self.HISTORY, self.same_until(2)))

    def test_a_change_then_its_revert_keeps_the_older_image(self):
        # R-549 (2026-11-08): a workflow edit then its revert left two commits of other code between the head and the
        # commit that has the images; the walk stopped there and every component looked unbuilt.
        tags = {f"devel-{self.HISTORY[3][:9]}"}
        same = lambda c, h, p: c != self.HISTORY[2]  # one commit of other code between the head and the images
        self.assertEqual(ri.find_tag(self.HISTORY[0], ["x"], tags, self.HISTORY, same), f"devel-{self.HISTORY[3][:9]}")

    def test_no_image_at_all(self):
        self.assertIsNone(ri.find_tag(self.HISTORY[0], ["x"], set(), self.HISTORY, self.same_until(4)))

    def test_a_release_branch_prefers_its_own_images_then_devel(self):
        h = self.HISTORY
        tags = {f"devel-{h[1][:9]}", f"release-0.1-{h[1][:9]}", f"devel-{h[2][:9]}"}
        same = self.same_until(4)
        self.assertEqual(ri.find_tag(h[0], ["x"], tags, h, same, "release-0.1"), f"release-0.1-{h[1][:9]}")
        self.assertEqual(ri.find_tag(h[0], ["x"], {f"devel-{h[2][:9]}"}, h, same, "release-0.1"),
                         f"devel-{h[2][:9]}")
        self.assertIsNone(ri.find_tag(h[0], ["x"], {f"release-0.1-{h[1][:9]}"}, h, same))  # devel never takes them

    def test_the_signer_follows_the_tag_branch(self):
        self.assertEqual(ri.signer_of("devel-abc"), ri.DEVEL_SIGNER)
        self.assertTrue(ri.signer_of("release-0.1-abc").endswith("publish-images.yml@refs/heads/release-0.1"))

    def test_components_follow_publish_images(self):
        self.assertEqual(sorted(ri.COMPONENTS), ["backend", "identity", "multiagent", "operator", "rag", "ui"])
        self.assertNotIn("fork/ci", ri.COMPONENTS["operator"])  # signing scripts are not image content
        self.assertIn(ri.WORKFLOW, ri.COMPONENTS["ui"])
        self.assertNotIn("fork/ci", ri.COMPONENTS["rag"])


class Expected(unittest.TestCase):
    IMAGES = {"operator": {"ref": "quay.io/zuno/unifai-operator@sha256:aa", "tag": "devel-1"}}

    def test_the_tested_digest_passes(self):
        self.assertEqual(ri.check_expected(self.IMAGES, ["operator=sha256:aa"]), [])

    def test_another_digest_or_component_fails(self):
        self.assertEqual(len(ri.check_expected(self.IMAGES, ["operator=sha256:bb", "rag=sha256:aa", "bad"])), 3)


class Notes(unittest.TestCase):
    def test_grouped_by_type_without_release_and_chore(self):
        text = rn.render("0.1.52", [
            "feat(fork): one product version",
            "fix(ui): mermaid error graphic",
            "release(fork): unifai-operator 0.1.51",
            "chore(fork): bump VERSION",
            "Merge something odd",
        ], "operator-v0.1.51", {"ui": {"ref": "quay.io/zuno/unifai-ui@sha256:" + "a" * 64}})
        self.assertIn("# UnifAI 0.1.52", text)
        self.assertIn("Changes since operator-v0.1.51.", text)
        self.assertIn("## Features\n\n- one product version (fork)", text)
        self.assertIn("## Fixes\n\n- mermaid error graphic (ui)", text)
        self.assertNotIn("0.1.51\n", text.split("Changes since")[1].split("## Images")[0].replace("v0.1.51.", ""))
        self.assertNotIn("bump VERSION", text)
        self.assertIn("## Other\n\n- Merge something odd", text)
        self.assertIn("| ui | `quay.io/zuno/unifai-ui@sha256:", text)

    def test_previous_release_prefers_v_tags_then_operator_tags(self):
        with tempfile.TemporaryDirectory() as d:
            def g(*a):
                subprocess.run(["git", "-C", d, *a], check=True, capture_output=True)
            g("init", "-q", "-b", "devel")
            for i, tag in enumerate(["operator-v0.1.50", "v0.1.51-rc.1", "operator-v0.1.51", None]):
                g("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", f"feat: c{i}")
                if tag:
                    g("tag", tag)
            cwd = pathlib.Path.cwd()
            try:
                import os
                os.chdir(d)
                self.assertEqual(rn.previous_release("HEAD"), "operator-v0.1.51")  # the rc is not a release
                g("-c", "user.email=t@t", "-c", "user.name=t", "tag", "-a", "v0.1.52", "-m", "kind: weekly")
                self.assertEqual(rn.previous_release("HEAD"), "operator-v0.1.51")  # not the release itself
                g("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "fix: next")
                self.assertEqual(rn.previous_release("HEAD"), "v0.1.52")
            finally:
                os.chdir(cwd)


if __name__ == "__main__":
    unittest.main()
