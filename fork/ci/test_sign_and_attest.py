"""Self-test of fork/ci/sign_and_attest.sh with stub cosign and skopeo. Run: python3 fork/ci/test_sign_and_attest.py"""
import os
import pathlib
import subprocess
import tempfile
import unittest

SCRIPT = pathlib.Path(__file__).resolve().parent / "sign_and_attest.sh"
D = "sha256:" + "a" * 64
SBOM_D = "sha256:" + "b" * 64
REF = f"quay.io/zuno/unifai-operator@{D}"
ENV = {
    "GITHUB_SERVER_URL": "https://github.com", "GITHUB_REPOSITORY": "startxfr/UnifAI",
    "GITHUB_REF": "refs/tags/operator-v0.1.39", "GITHUB_SHA": "1" * 40,
    "GITHUB_WORKFLOW_REF": "startxfr/UnifAI/.github/workflows/unifai-operator-release.yml@refs/tags/operator-v0.1.39",
    "GITHUB_RUN_ID": "9", "GITHUB_EVENT_NAME": "push",
}
COSIGN = f"""#!/usr/bin/env bash
echo "cosign $*" >> "$LOG"
if [[ "$1" == upload ]]; then echo "Uploaded image to:"; echo "quay.io/zuno/unifai-operator-bundle@{SBOM_D}"; fi
[[ -n "${{FAIL_SIGN:-}}" && "$1" == sign ]] && exit 1
exit 0
"""
SKOPEO = f"""#!/usr/bin/env bash
echo "skopeo $*" >> "$LOG"
[[ -n "${{NO_SBOM:-}}" ]] && exit 1
echo "{SBOM_D}"
"""


class SignAndAttest(unittest.TestCase):
    def run_script(self, *args, **extra):
        tmp = pathlib.Path(tempfile.mkdtemp())
        for name, body in (("cosign", COSIGN), ("skopeo", SKOPEO), ("sleep", "#!/usr/bin/env bash\nexit 0\n")):
            (tmp / name).write_text(body)
            (tmp / name).chmod(0o755)
        log = tmp / "log"
        env = dict(os.environ, **ENV, PATH=f"{tmp}:{os.environ['PATH']}", LOG=str(log), **extra)
        done = subprocess.run(["bash", str(SCRIPT), *args], env=env, capture_output=True, text=True)
        return done, (log.read_text().splitlines() if log.exists() else [])

    def test_a_release_re_signs_the_existing_sbom_artifact_of_the_operator(self):
        done, log = self.run_script(REF, "operator")
        self.assertEqual(done.returncode, 0, done.stderr)
        subs = [line.split()[1] for line in log if line.startswith("cosign")]
        self.assertEqual(subs, ["sign", "attest", "sign"])
        self.assertTrue(any(f"quay.io/zuno/unifai-operator@{SBOM_D}" in line and "sign" in line for line in log))
        self.assertFalse(any(line.startswith("cosign upload") for line in log))

    def test_a_given_sbom_is_published_by_digest_tag_and_signed(self):
        sbom = pathlib.Path(tempfile.mkdtemp()) / "sbom.json"
        sbom.write_text("{}")
        done, log = self.run_script("quay.io/zuno/unifai-operator-bundle@" + D, "operator-bundle", str(sbom))
        self.assertEqual(done.returncode, 0, done.stderr)
        upload = [line for line in log if line.startswith("cosign upload")][0]
        self.assertIn("quay.io/zuno/unifai-operator-bundle:sha256-" + "a" * 64 + ".sbom", upload)
        self.assertIn("application/spdx+json", upload)
        self.assertTrue(log[-1].endswith(f"quay.io/zuno/unifai-operator-bundle@{SBOM_D}"))
        self.assertFalse(any(line.startswith("skopeo") for line in log))

    def test_a_tag_is_refused_and_a_missing_sbom_artifact_fails(self):
        done, log = self.run_script("quay.io/zuno/unifai-operator:v0.1.39", "operator")
        self.assertEqual(done.returncode, 2)
        self.assertEqual(log, [])
        done, _ = self.run_script(REF, "operator", NO_SBOM="1")
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("no SBOM artifact", done.stderr)

    def test_a_signature_that_keeps_failing_fails_the_script(self):
        done, log = self.run_script(REF, "operator", FAIL_SIGN="1")
        self.assertNotEqual(done.returncode, 0)
        self.assertEqual(len([line for line in log if line.startswith("cosign sign")]), 5)


if __name__ == "__main__":
    unittest.main()
