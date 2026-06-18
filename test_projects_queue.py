"""Project queue tests live in test_projects_registry.py.

This module exists so targeted queue verification commands can name
test_projects_queue.py without duplicating the project registry fixture suite.
"""

import unittest


def load_tests(_loader, _tests, _pattern):
    return unittest.TestSuite()
