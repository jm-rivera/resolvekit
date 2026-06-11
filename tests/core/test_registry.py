"""Tests for DomainRegistry."""

import pytest


class TestDomainRegistry:
    """Tests for domain pack registry."""

    def test_register_and_get_pack(self):
        from resolvekit.core import DomainRegistry

        class MockPack:
            @property
            def pack_id(self) -> str:
                return "test"

        registry = DomainRegistry()
        pack = MockPack()

        registry.register(pack)

        assert registry.get("test") is pack
        assert "test" in registry.available_packs

    def test_get_unknown_pack_returns_none(self):
        from resolvekit.core import DomainRegistry

        registry = DomainRegistry()

        assert registry.get("unknown") is None

    def test_register_duplicate_raises(self):
        from resolvekit.core import DomainRegistry

        class MockPack:
            @property
            def pack_id(self) -> str:
                return "test"

        registry = DomainRegistry()
        registry.register(MockPack())

        with pytest.raises(ValueError, match="already registered"):
            registry.register(MockPack())

    def test_register_duplicate_with_allow_replace(self):
        from resolvekit.core import DomainRegistry

        class MockPack:
            def __init__(self, name: str):
                self._name = name

            @property
            def pack_id(self) -> str:
                return "test"

        registry = DomainRegistry()
        pack1 = MockPack("first")
        pack2 = MockPack("second")

        registry.register(pack1)
        registry.register(pack2, allow_replace=True)

        assert registry.get("test")._name == "second"

    def test_unregister_pack(self):
        from resolvekit.core import DomainRegistry

        class MockPack:
            @property
            def pack_id(self) -> str:
                return "test"

        registry = DomainRegistry()
        registry.register(MockPack())
        registry.unregister("test")

        assert registry.get("test") is None

    def test_unregister_nonexistent_pack_is_noop(self):
        from resolvekit.core import DomainRegistry

        registry = DomainRegistry()
        registry.unregister("nonexistent")  # Should not raise

    def test_all_packs_returns_copy(self):
        from resolvekit.core import DomainRegistry

        class MockPack:
            @property
            def pack_id(self) -> str:
                return "test"

        registry = DomainRegistry()
        pack = MockPack()
        registry.register(pack)

        all_packs = registry.all_packs()
        assert "test" in all_packs
        assert all_packs["test"] is pack

        # Modifying returned dict shouldn't affect registry
        all_packs["test"] = None
        assert registry.get("test") is pack

    def test_default_registry_exists(self):
        from resolvekit.core import default_registry

        registry = default_registry()
        assert registry is not None
        assert isinstance(registry.available_packs, list)

    def test_default_registry_is_singleton(self):
        from resolvekit.core import default_registry

        registry1 = default_registry()
        registry2 = default_registry()
        assert registry1 is registry2

    def test_default_registry_contains_builtin_packs(self):
        from resolvekit.core import default_registry
        from resolvekit.core.registry import reset_default_registry

        # Reset to test fresh initialization
        reset_default_registry()

        registry = default_registry()

        # Should have geo and org packs registered
        assert "geo" in registry.available_packs
        assert "org" in registry.available_packs

        # Packs should be retrievable
        geo_pack = registry.get("geo")
        org_pack = registry.get("org")
        assert geo_pack is not None
        assert org_pack is not None
        assert geo_pack.pack_id == "geo"
        assert org_pack.pack_id == "org"
