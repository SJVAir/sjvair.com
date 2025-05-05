from django.test import TestCase
from camp.apps.calibrations import processors, trainers
from camp.apps.calibrations.registry import Registry, LazyClassProxy


# === Shared utility ===

def create_test_registry():
    """
    Returns a test-friendly Registry with lazy loading disabled.
    You can manually populate ._registry and toggle ._loaded to simulate lazy behavior.
    """
    reg = Registry('dummy.module')
    reg._load_all = lambda: None  # Prevent real imports
    return reg


# === Tests for real loaded registries ===

class RegistryTests(TestCase):
    def test_lazy_lookup_resolves(self):
        proxy = processors['PM25_UnivariateLinearRegression']
        # May be proxy or already resolved
        cls = proxy._resolve() if isinstance(proxy, LazyClassProxy) else proxy
        assert cls.__name__ == 'PM25_UnivariateLinearRegression'

    def test_dot_access_and_dict_access_match(self):
        from_name = processors['PM25_UnivariateLinearRegression']
        from_attr = processors.PM25_UnivariateLinearRegression
        assert from_name == from_attr

    def test_iteration_returns_classes(self):
        names = [cls.__name__ for cls in processors]
        assert 'PM25_UnivariateLinearRegression' in names

    def test_dir_lists_registered_names(self):
        names = dir(processors)
        assert 'PM25_UnivariateLinearRegression' in names

    def test_repr_displays_registered_classes(self):
        rep = repr(processors)
        assert 'PM25_UnivariateLinearRegression' in rep

    def test_contains_works(self):
        assert 'PM25_UnivariateLinearRegression' in processors
        assert 'NonExistentProcessor' not in processors

    def test_get_for_entry_model_filters_correctly(self):
        reg = create_test_registry()

        class FakeEntryModel:
            entry_type = 'fake'

        class MatchOne:
            entry_model = FakeEntryModel

        class MatchTwo:
            entry_model = FakeEntryModel

        class NoMatch:
            class NotFakeEntry:
                entry_type = 'other'

            entry_model = NotFakeEntry

        reg._registry = {
            'MatchOne': MatchOne,
            'MatchTwo': MatchTwo,
            'NoMatch': NoMatch,
        }
        reg._loaded = True

        results = reg.get_for_entry_model(FakeEntryModel)
        assert set(results) == {MatchOne, MatchTwo}


    def test_get_for_entry_type_filters_correctly(self):
        reg = create_test_registry()

        class EntryTypeA:
            entry_type = 'type_a'

        class EntryTypeB:
            entry_type = 'type_b'

        class One:
            entry_model = EntryTypeA

        class Two:
            entry_model = EntryTypeA

        class Three:
            entry_model = EntryTypeB

        reg._registry = {
            'One': One,
            'Two': Two,
            'Three': Three,
        }
        reg._loaded = True

        results = reg.get_for_entry_type('type_a')
        assert set(results) == {One, Two}


# === Tests for fresh, controlled registries ===

class RegistryLazyBehaviorTests(TestCase):
    def test_returns_lazy_proxy_when_unloaded(self):
        reg = create_test_registry()

        class Dummy:
            pass

        reg._registry['Dummy'] = Dummy
        reg._loaded = False

        proxy = reg['Dummy']
        assert isinstance(proxy, LazyClassProxy)

    def test_proxy_resolves_to_real_class(self):
        reg = create_test_registry()

        class DummyResolved:
            pass

        reg._registry['DummyResolved'] = DummyResolved
        reg._loaded = False

        proxy = reg['DummyResolved']
        cls = proxy._resolve()
        assert cls is DummyResolved

    def test_repr_of_unresolved_and_resolved_proxy(self):
        reg = create_test_registry()

        class DummyRepr:
            pass

        reg._registry['DummyRepr'] = DummyRepr
        reg._loaded = False

        proxy = reg['DummyRepr']
        raw = repr(proxy)
        assert 'Lazy[DummyRepr]' in raw

        _ = proxy._resolve()
        resolved = repr(proxy)
        assert 'DummyRepr' in resolved
