"""Self-test of fork/ci/run_unit_tests.py. Run: python3 fork/ci/test_run_unit_tests.py"""
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import run_unit_tests as rut  # noqa: E402


class DebtArgs(unittest.TestCase):
    LINES = [
        "# comment",
        "",
        "multi-agent tests/unit/orchestrator/test_simple.py",
        "multi-agent tests/unit/x/test_a.py::TestA::test_b[http://10.0.0.5/]",
        "shared-resources/identity tests/unit/test_auth_routes.py",
        "  rag tests/unit/test_c.py::test_d  ",
    ]

    def test_paths_are_ignored_and_node_ids_deselected(self):
        self.assertEqual(rut.debt_args("multi-agent", self.LINES), [
            "--ignore=tests/unit/orchestrator/test_simple.py",
            "--deselect=tests/unit/x/test_a.py::TestA::test_b[http://10.0.0.5/]",
        ])

    def test_only_the_suite_entries(self):
        self.assertEqual(rut.debt_args("shared-resources/identity", self.LINES),
                         ["--ignore=tests/unit/test_auth_routes.py"])
        self.assertEqual(rut.debt_args("rag", self.LINES), ["--deselect=tests/unit/test_c.py::test_d"])

    def test_an_entry_without_a_test_is_refused(self):
        with self.assertRaises(ValueError):
            rut.debt_args("rag", ["rag"])

    def test_unknown_suite_is_a_usage_error(self):
        self.assertEqual(rut.main(["ui"]), 2)
        self.assertEqual(rut.main([]), 2)


class DebtFile(unittest.TestCase):
    def test_every_entry_names_a_known_suite_and_a_test(self):
        for raw in rut.DEBT.read_text().splitlines():
            line = raw.strip()
            if line and not line.startswith("#"):
                suite, _, entry = line.partition(" ")
                self.assertIn(suite, rut.SUITES, raw)
                self.assertTrue(entry.strip().startswith("tests/unit/"), raw)

    def test_debt_paths_exist(self):
        """A module upstream deleted or renamed must leave the list (its entries no longer skip anything)."""
        for raw in rut.DEBT.read_text().splitlines():
            line = raw.strip()
            if line and not line.startswith("#"):
                suite, _, entry = line.partition(" ")
                path = rut.ROOT / suite / entry.strip().split("::")[0]
                self.assertTrue(path.is_file(), raw)


if __name__ == "__main__":
    unittest.main()
