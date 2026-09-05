from tracecite.runtime.jsonl_physical import FixedCapacityTopK, topk_sort_key


def test_fixed_capacity_topk_never_retains_more_than_k() -> None:
    topk = FixedCapacityTopK(7, descending=True)
    for value in range(10_000):
        topk.add(topk_sort_key(value, numeric=True), value)
        assert topk.retained <= 7
    assert topk.values() == list(range(9_999, 9_992, -1))


def test_fixed_capacity_topk_preserves_source_order_for_equal_keys() -> None:
    descending = FixedCapacityTopK(3, descending=True)
    ascending = FixedCapacityTopK(3, descending=False)
    for label in ("first", "second", "third", "fourth"):
        key = topk_sort_key(10, numeric=True)
        descending.add(key, label)
        ascending.add(key, label)
    assert descending.values() == ["first", "second", "third"]
    assert ascending.values() == ["first", "second", "third"]
