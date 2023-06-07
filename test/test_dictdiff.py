from copy import deepcopy
from dataclasses import dataclass
import unittest

from awsiotclient.dictdiff import dictdiff


@dataclass
class Data:
    value: int


class DictdiffTestCase(unittest.TestCase):
    COMMON_DICT = {
        "a": 1.2,
        "b": "hoge",
        "c": False,
        "d": Data(20),
        "e": [1, 2, 3],
        "f": {
            "fa": 2.5,
            "fe": [4, 5, 6],
        },
    }

    def test_dictdiff_no_difference(self):
        from_dict = deepcopy(self.COMMON_DICT)
        to_dict = deepcopy(self.COMMON_DICT)

        out = dictdiff(from_dict, to_dict)

        self.assertEqual(out, None)

    def test_dictdiff_from_empty(self):
        from_dict = {}
        to_dict = deepcopy(self.COMMON_DICT)

        out = dictdiff(from_dict, to_dict)

        self.assertEqual(out, self.COMMON_DICT)

    def test_dictdiff_to_empty(self):
        from_dict = deepcopy(self.COMMON_DICT)
        to_dict = {}

        out = dictdiff(from_dict, to_dict)

        self.assertEqual(out, None)

    def test_dictdiff_add_items(self):
        from_dict = deepcopy(self.COMMON_DICT)
        to_dict = deepcopy(self.COMMON_DICT)
        to_dict["added"] = 20
        to_dict["f"]["added"] = [20]

        out = dictdiff(from_dict, to_dict)

        self.assertEqual(
            out,
            {"added": 20, "f": {"added": [20]}},
        )

    def test_dictdiff_remove_items(self):
        from_dict = deepcopy(self.COMMON_DICT)
        to_dict = deepcopy(self.COMMON_DICT)
        del to_dict["d"]
        del to_dict["f"]["fa"]

        out = dictdiff(from_dict, to_dict)

        self.assertEqual(out, {"d": None, "f": {"fa": None}})

    def test_dictdiff_update_items(self):
        from_dict = deepcopy(self.COMMON_DICT)
        to_dict = deepcopy(self.COMMON_DICT)
        to_dict["a"] = "hoge"
        to_dict["f"]["fa"] = "piyo"

        out = dictdiff(from_dict, to_dict)

        self.assertEqual(out, {"a": "hoge", "f": {"fa": "piyo"}})

    def test_dictdiff_update_dict(self):
        from_dict = deepcopy(self.COMMON_DICT)
        to_dict = deepcopy(self.COMMON_DICT)
        to_dict["f"] = "hoge"

        out = dictdiff(from_dict, to_dict)

        self.assertEqual(out, {"f": "hoge"})


if __name__ == "__main__":
    unittest.main()
