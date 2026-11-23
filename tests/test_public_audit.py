import unittest

from scripts.audit_public_places import changed_positions


class PublicAuditTest(unittest.TestCase):
    def test_added_removed_and_reordered_candidates_are_counted(self):
        def rows(*codes):
            return [{"dong_code": c} for c in codes]
        self.assertEqual(changed_positions(rows("a", "b"), rows("a")), 1)
        self.assertEqual(changed_positions(rows("a"), rows("a", "b")), 1)
        self.assertEqual(changed_positions(rows("a", "b"), rows("b", "a")), 2)
        self.assertEqual(changed_positions(rows("a", "b"), rows("a", "b")), 0)
