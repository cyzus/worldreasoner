"""Unit tests for ResultCollector."""

from src.core.collectors import ResultCollector


class TestResultCollector:
    """Tests for the ResultCollector class."""

    def test_initialization(self):
        """Test that ResultCollector initializes empty."""
        collector = ResultCollector[str]()

        assert collector.count() == 0
        assert collector.is_empty()
        assert len(collector) == 0
        assert not collector  # __bool__ returns False for empty

    def test_add_single_item(self):
        """Test adding a single item."""
        collector = ResultCollector[str]()
        collector.add("test")

        assert collector.count() == 1
        assert not collector.is_empty()
        assert len(collector) == 1
        assert collector  # __bool__ returns True

    def test_add_multiple_items(self):
        """Test adding multiple items one at a time."""
        collector = ResultCollector[int]()
        collector.add(1)
        collector.add(2)
        collector.add(3)

        assert collector.count() == 3
        assert collector.get_all() == [1, 2, 3]

    def test_add_many_items(self):
        """Test adding multiple items at once."""
        collector = ResultCollector[str]()
        collector.add_many(["a", "b", "c"])

        assert collector.count() == 3
        assert collector.get_all() == ["a", "b", "c"]

    def test_get_all_returns_copy(self):
        """Test that get_all returns a copy, not the internal list."""
        collector = ResultCollector[str]()
        collector.add("test")

        items = collector.get_all()
        items.append("modified")

        # Original collector should be unchanged
        assert collector.count() == 1
        assert collector.get_all() == ["test"]

    def test_clear(self):
        """Test clearing the collector."""
        collector = ResultCollector[int]()
        collector.add_many([1, 2, 3])

        assert collector.count() == 3

        collector.clear()

        assert collector.count() == 0
        assert collector.is_empty()
        assert collector.get_all() == []

    def test_get_last_with_items(self):
        """Test getting the last item when collector has items."""
        collector = ResultCollector[str]()
        collector.add("first")
        collector.add("second")
        collector.add("third")

        assert collector.get_last() == "third"

    def test_get_last_empty(self):
        """Test getting the last item when collector is empty."""
        collector = ResultCollector[str]()

        assert collector.get_last() is None

    def test_iteration(self):
        """Test iterating over collected items."""
        collector = ResultCollector[int]()
        collector.add_many([1, 2, 3, 4, 5])

        result = []
        for item in collector:
            result.append(item)

        assert result == [1, 2, 3, 4, 5]

    def test_len_builtin(self):
        """Test len() builtin function."""
        collector = ResultCollector[str]()

        assert len(collector) == 0

        collector.add("test")
        assert len(collector) == 1

        collector.add_many(["a", "b"])
        assert len(collector) == 3

    def test_bool_builtin(self):
        """Test bool() builtin function."""
        collector = ResultCollector[str]()

        assert not collector  # Empty is False

        collector.add("test")
        assert collector  # Non-empty is True

        collector.clear()
        assert not collector  # Cleared is False again

    def test_repr(self):
        """Test string representation."""
        collector = ResultCollector[str]()
        repr_str = repr(collector)

        assert "ResultCollector" in repr_str
        assert "count=0" in repr_str

        collector.add("test")
        repr_str = repr(collector)
        assert "count=1" in repr_str

    def test_reuse_after_clear(self):
        """Test that collector can be reused after clearing."""
        collector = ResultCollector[str]()

        # First run
        collector.add_many(["a", "b", "c"])
        assert collector.count() == 3

        # Clear and reuse
        collector.clear()
        collector.add_many(["x", "y"])
        assert collector.count() == 2
        assert collector.get_all() == ["x", "y"]

    def test_type_consistency(self):
        """Test that collector maintains type consistency (via usage)."""
        # This is more about documentation - Python doesn't enforce generic types at runtime
        # But we can verify the pattern works as expected
        collector = ResultCollector[int]()
        collector.add(1)
        collector.add(2)

        # All items should be the expected type
        assert all(isinstance(item, int) for item in collector.get_all())
