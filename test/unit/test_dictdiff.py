from copy import deepcopy

import pytest
from hypothesis import given
from hypothesis import strategies as st

from awsiotclient.dictdiff import dictdiff, dictmerge

from .fakes import merge_state

BASE = {
    "a": 1.2,
    "b": "hoge",
    "c": False,
    "e": [1, 2, 3],
    "f": {"fa": 2.5, "fe": [4, 5, 6]},
}


def _with(**changes):
    d = deepcopy(BASE)
    d.update(changes)
    return d


@pytest.mark.parametrize(
    "s1, s2, expected",
    [
        pytest.param(BASE, deepcopy(BASE), None, id="no-difference"),
        pytest.param(None, BASE, BASE, id="from-none"),
        pytest.param({}, BASE, BASE, id="from-empty"),
        # An empty or missing target means "nothing to update", not "delete all".
        pytest.param(BASE, {}, None, id="to-empty"),
        pytest.param(BASE, None, None, id="to-none"),
        pytest.param(BASE, _with(added=20), {"added": 20}, id="add-top-level"),
        pytest.param(
            BASE,
            _with(f={"fa": 2.5, "fe": [4, 5, 6], "added": [20]}),
            {"f": {"added": [20]}},
            id="add-nested",
        ),
        pytest.param(
            BASE,
            {k: v for k, v in BASE.items() if k != "b"},
            {"b": None},
            id="remove-top-level",
        ),
        pytest.param(
            BASE, _with(f={"fe": [4, 5, 6]}), {"f": {"fa": None}}, id="remove-nested"
        ),
        pytest.param(BASE, _with(a="hoge"), {"a": "hoge"}, id="update-scalar"),
        pytest.param(BASE, _with(a=0), {"a": 0}, id="update-to-falsy"),
        pytest.param(
            BASE, _with(e=[1, 2]), {"e": [1, 2]}, id="lists-are-replaced-whole"
        ),
        pytest.param(BASE, _with(f="hoge"), {"f": "hoge"}, id="dict-to-scalar"),
        pytest.param(BASE, _with(a={"x": 1}), {"a": {"x": 1}}, id="scalar-to-dict"),
    ],
)
def test_dictdiff(s1, s2, expected):
    assert dictdiff(s1, s2) == expected


def test_dictdiff_result_does_not_alias_input():
    s2 = _with(f={"fa": 1, "new": {"deep": [1]}})
    out = dictdiff({}, s2)
    out["f"]["new"]["deep"].append(2)
    assert s2["f"]["new"]["deep"] == [1]


@pytest.mark.parametrize(
    "base, patch, expected",
    [
        pytest.param(None, {"a": 1}, {"a": 1}, id="onto-none"),
        pytest.param({"a": 1}, None, {"a": 1}, id="none-patch"),
        pytest.param({"a": 1, "b": 2}, {"b": None}, {"a": 1}, id="null-deletes"),
        pytest.param(
            {"a": {"x": 1, "y": 2}},
            {"a": {"y": 3}},
            {"a": {"x": 1, "y": 3}},
            id="nested-merge",
        ),
        pytest.param({"a": [1, 2]}, {"a": [3]}, {"a": [3]}, id="list-replaced"),
        pytest.param({"a": 1}, {"a": {"x": 1}}, {"a": {"x": 1}}, id="scalar-to-dict"),
    ],
)
def test_dictmerge(base, patch, expected):
    before = deepcopy(base)
    assert dictmerge(base, patch) == expected
    assert base == before, "dictmerge must not mutate its input"


# Documents as a device would report them: nested objects are never empty and
# values are never null, because the shadow service gives both a meaning
# ("nothing to update" and "delete").
leaves = (
    st.booleans()
    | st.integers()
    | st.text(max_size=3)
    | st.lists(st.integers(), max_size=2)
)
keys = st.sampled_from(["a", "b", "c", "d"])
values = st.recursive(
    leaves,
    lambda children: st.dictionaries(keys, children, min_size=1, max_size=3),
    max_leaves=6,
)
documents = st.dictionaries(keys, values, min_size=1, max_size=4)


@given(documents, documents)
def test_patch_from_dictdiff_turns_the_old_document_into_the_new_one(s1, s2):
    patch = dictdiff(s1, s2)
    shadow = deepcopy(s1)
    if patch is not None:
        merge_state(shadow, patch)
    assert shadow == s2


@given(documents, documents)
def test_dictmerge_agrees_with_the_shadow_service(s1, s2):
    patch = dictdiff(s1, s2) or {}
    expected = deepcopy(s1)
    merge_state(expected, patch)
    assert dictmerge(s1, patch) == expected
