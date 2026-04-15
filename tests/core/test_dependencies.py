from __future__ import annotations

import importlib.util
import unittest
from unittest.mock import patch

from rikugan.core.dependencies import get_missing_dependency_warnings, get_optional_dependency_statuses


class TestDependencies(unittest.TestCase):
    def test_statuses_include_known_optional_packages(self):
        statuses = get_optional_dependency_statuses()
        keys = {status.key for status in statuses}
        self.assertIn("anthropic", keys)
        self.assertIn("openai", keys)
        self.assertIn("gemini", keys)
        self.assertIn("mcp", keys)

    def test_missing_dependency_warnings_are_human_readable(self):
        def fake_find_spec(name: str):
            if name == "openai":
                return None
            return object()

        with patch.object(importlib.util, "find_spec", side_effect=fake_find_spec):
            warnings = get_missing_dependency_warnings()

        self.assertTrue(any("openai" in warning.lower() for warning in warnings))


if __name__ == "__main__":
    unittest.main()
