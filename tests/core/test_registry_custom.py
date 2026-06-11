"""Tests for the built-in ``custom`` factory registration in core/registry.py."""

import pytest


@pytest.fixture(autouse=True)
def _clean_registry():
    """Reset the factory registry and default registry before each test.

    Clears _pack_factories directly so the test exercises the built-in
    registration path, not any factory registered by another module's autouse
    fixture (e.g. test_generic_pack.py's ``register_pack_factory`` call).
    """
    from resolvekit.core import registry as reg

    saved = dict(reg._pack_factories)
    reg._pack_factories.clear()
    reg.reset_default_registry()
    yield
    reg._pack_factories.clear()
    reg._pack_factories.update(saved)
    reg.reset_default_registry()


class TestCustomFactoryRegistration:
    """_ensure_builtin_factories registers ``custom`` → GenericPack."""

    def test_get_pack_factory_returns_generic_pack_after_ensure(self):
        from resolvekit.core.registry import _ensure_builtin_factories, get_pack_factory
        from resolvekit.packs.custom import GenericPack

        _ensure_builtin_factories()

        assert get_pack_factory("custom") is GenericPack

    def test_pre_registered_custom_factory_not_overwritten(self):
        """A manually registered custom factory survives _ensure_builtin_factories."""
        from resolvekit.core.registry import (
            _ensure_builtin_factories,
            get_pack_factory,
            register_pack_factory,
        )

        class MyCustomPack:
            pass

        register_pack_factory("custom", MyCustomPack)
        _ensure_builtin_factories()

        assert get_pack_factory("custom") is MyCustomPack

    def test_geo_and_org_also_registered(self):
        """_ensure_builtin_factories registers all three built-in packs."""
        from resolvekit.core.registry import _ensure_builtin_factories, get_pack_factory
        from resolvekit.packs.custom import GenericPack

        _ensure_builtin_factories()

        assert get_pack_factory("geo") is not None
        assert get_pack_factory("org") is not None
        assert get_pack_factory("custom") is GenericPack

    def test_default_registry_includes_custom_pack(self):
        """default_registry() includes a custom pack after lazy initialisation."""
        from resolvekit.core.registry import default_registry

        registry = default_registry()

        assert "custom" in registry.available_packs
        pack = registry.get("custom")
        assert pack is not None
        assert pack.pack_id == "custom"
