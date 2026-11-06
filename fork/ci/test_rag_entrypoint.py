"""Self-test of rag/entrypoint.sh (R-537): the Celery worker gets a node name unique per pod.

Run: python3 fork/ci/test_rag_entrypoint.py
"""
import pathlib
import re
import unittest

ENTRYPOINT = pathlib.Path(__file__).resolve().parents[2] / "rag" / "entrypoint.sh"


class RagEntrypoint(unittest.TestCase):
    def test_celery_node_name_is_unique_per_pod(self):
        lines = [l for l in ENTRYPOINT.read_text().splitlines() if "celery -A" in l and not l.lstrip().startswith("#")]
        self.assertEqual(len(lines), 1, lines)
        name = re.search(r"(?:^|\s)-n\s+(\S+)", lines[0])
        self.assertIsNotNone(name, "the worker must be given a node name")
        # A name without "@" is the host part: every pod would share celery@<name> and its exclusive pidbox queue.
        self.assertRegex(name[1], r"^[\w.-]+@%h$")


if __name__ == "__main__":
    unittest.main()
