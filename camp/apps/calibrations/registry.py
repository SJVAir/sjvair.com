import importlib
import pkgutil


class LazyClassProxy:
    def __init__(self, registry, name):
        self._registry = registry
        self._name = name
        self._resolved = None

    def __call__(self, *args, **kwargs):
        return self._resolve()(*args, **kwargs)

    def __getattr__(self, attr):
        return getattr(self._resolve(), attr)

    def __repr__(self):
        try:
            real_cls = self._resolve()
            return f"<Lazy[{self._name}] => {real_cls.__module__}.{real_cls.__name__}>"
        except Exception:
            return f"<Lazy[{self._name}] (unresolved)>"

    def _resolve(self):
        if self._resolved is not None:
            return self._resolved

        self._registry._load_all()
        cls = self._registry.get(self._name)
        if not cls:
            raise ImportError(f"Class '{self._name}' not found in registry.")
        self._resolved = cls
        return cls


class Registry:
    def __init__(self, base_module):
        self._registry = {}
        self._base_module = base_module
        self._loaded = False

    def __contains__(self, key):
        self._load_all()
        return key in self._registry

    def __dir__(self):
        self._load_all()
        return list(self._registry.keys())

    def __getattr__(self, name):
        # Enables processors.PM25_UnivariateLinearRegression
        try:
            return self[name]
        except KeyError:
            raise AttributeError(f"{self.__class__.__name__!r} has no attribute {name!r}")

    def __getitem__(self, key):
        if not self._loaded:
            return LazyClassProxy(self, key)
        return self._registry[key]

    def __iter__(self):
        self._load_all()
        return iter(self._registry.values())

    def __repr__(self):
        self._load_all()
        return f"<Registry ({self._base_module}): {list(self._registry.keys())}>"

    def _load_all(self):
        if self._loaded:
            return

        base = importlib.import_module(self._base_module)
        if not hasattr(base, '__path__'):
            return

        for _, name, _ in pkgutil.walk_packages(base.__path__, prefix=base.__name__ + '.'):
            importlib.import_module(name)

        self._loaded = True

    def all(self):
        self._load_all()
        return list(self._registry.values())

    def get(self, key, default=None):
        self._load_all()
        return self._registry.get(key, default)

    def get_for_entry_model(self, entry_model):
        return [cls for cls in self if cls.entry_model == entry_model]

    def get_for_entry_type(self, entry_type):
        return [cls for cls in self if cls.entry_model.entry_type == entry_type]

    def register(self):
        def decorator(cls):
            name = cls.__name__
            self._registry[name] = cls
            # setattr(self, name, cls)  # Optional: dot-access
            return cls
        return decorator
