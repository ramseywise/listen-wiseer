"""Unit tests for Registry (swappable component registry)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[2] / "src"))

from registry import Registry


@pytest.fixture(autouse=True)
def clear_registry():
    """Reset registry state between tests."""
    Registry.clear()
    yield
    Registry.clear()


# ---------------------------------------------------------------------------
# register + create
# ---------------------------------------------------------------------------


def test_register_and_create():
    class MyComponent:
        def __init__(self, x: int) -> None:
            self.x = x

    Registry.register("component", "mine")(MyComponent)
    obj = Registry.create("component", "mine", x=42)
    assert isinstance(obj, MyComponent)
    assert obj.x == 42


def test_register_as_decorator():
    @Registry.register("handler", "default")
    class DefaultHandler:
        pass

    obj = Registry.create("handler", "default")
    assert isinstance(obj, DefaultHandler)


def test_create_unknown_type_raises():
    with pytest.raises(ValueError, match="No module named"):
        Registry.create("unknown_type", "foo")


def test_create_unknown_name_raises():
    @Registry.register("component", "registered")
    class A:
        pass

    with pytest.raises(ValueError, match="No module named 'unregistered'"):
        Registry.create("component", "unregistered")


def test_duplicate_registration_raises():
    @Registry.register("component", "dup")
    class A:
        pass

    with pytest.raises(ValueError, match="Duplicate registration"):

        @Registry.register("component", "dup")
        class B:
            pass


# ---------------------------------------------------------------------------
# list_modules
# ---------------------------------------------------------------------------


def test_list_modules_by_type():
    @Registry.register("retriever", "dense")
    class Dense:
        pass

    @Registry.register("retriever", "sparse")
    class Sparse:
        pass

    names = Registry.list_modules("retriever")
    assert set(names) == {"dense", "sparse"}


def test_list_modules_all():
    @Registry.register("retriever", "dense")
    class Dense:
        pass

    @Registry.register("generator", "claude")
    class Claude:
        pass

    result = Registry.list_modules()
    assert "retriever" in result
    assert "generator" in result


def test_list_modules_unknown_type_returns_empty():
    assert Registry.list_modules("nonexistent") == []


# ---------------------------------------------------------------------------
# validate
# ---------------------------------------------------------------------------


def test_validate_passes_for_callable():
    @Registry.register("component", "valid")
    class ValidClass:
        pass

    Registry.validate()  # should not raise


def test_validate_fails_for_non_callable():
    Registry._modules.setdefault("component", {})
    Registry._modules["component"]["bad"] = "not_a_class"  # type: ignore[assignment]

    with pytest.raises(TypeError, match="not callable"):
        Registry.validate()
