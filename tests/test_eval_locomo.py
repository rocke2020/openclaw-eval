import unittest

from eval_locomo import select_qas


class EvalLocomoTests(unittest.TestCase):
    def test_select_qas_defaults_to_all_categories(self):
        sample = {"qa": [{"category": 1}, {"category": 5}]}
        self.assertEqual(len(select_qas(sample)), 2)

    def test_select_qas_can_exclude_category_5_explicitly(self):
        sample = {"qa": [{"category": 1}, {"category": 5}]}
        self.assertEqual(select_qas(sample, exclude_categories={"5"}), [{"category": 1}])

    def test_select_qas_include_categories_wins_before_count(self):
        sample = {"qa": [{"category": 1}, {"category": 5}, {"category": 5}]}
        self.assertEqual(select_qas(sample, include_categories={"5"}, count=1), [{"category": 5}])


if __name__ == "__main__":
    unittest.main()
