from awsiotclient.shadow import DocumentTracker, ShadowData


class TestDocumentTracker:
    def test_get_set(self):
        t = DocumentTracker()
        assert t.get() is None
        t.set({"key": "value"})
        assert t.get() == {"key": "value"}

    def test_update_same_value_returns_none(self):
        t = DocumentTracker()
        t.set({"a": 1})
        result = t.update({"a": 1}, diff_only=False)
        assert result is None

    def test_update_diff_only(self):
        t = DocumentTracker()
        t.set({"a": 1, "b": 2})
        result = t.update({"a": 1, "b": 3, "c": 4}, diff_only=True)
        # dictdiff should return only changed/added keys
        assert result == {"b": 3, "c": 4}
        assert t.get() == {"a": 1, "b": 3, "c": 4}

    def test_update_full_doc(self):
        t = DocumentTracker()
        t.set({"a": 1})
        result = t.update({"a": 2, "b": 3}, diff_only=False)
        assert result == {"a": 2, "b": 3}
        assert t.get() == {"a": 2, "b": 3}


class TestShadowData:
    def test_update_reported(self):
        sd = ShadowData()
        result = sd.update_reported_value({"temp": 25}, publish_full_doc=True)
        assert result == {"temp": 25}
        assert sd.get_reported_value() == {"temp": 25}

    def test_update_desired(self):
        sd = ShadowData()
        result = sd.update_desired_value({"mode": "on"}, publish_full_doc=True)
        assert result == {"mode": "on"}
        assert sd.get_desired_value() == {"mode": "on"}

    def test_update_both(self):
        sd = ShadowData()
        desired, reported = sd.update_both_values(
            {"mode": "on"}, {"temp": 25}, publish_full_doc=True
        )
        assert desired == {"mode": "on"}
        assert reported == {"temp": 25}
