from __future__ import annotations

from utils.logging import get_logger

log = get_logger(__name__)


class Registry:
    """Decorator-based registry for swappable pipeline components.

    Usage:
        @Registry.register("client", "chroma")
        class ChromaRetriever: ...

        client = Registry.create("client", "chroma", **settings)
    """

    _modules: dict[str, dict[str, type]] = {}

    @classmethod
    def register(cls, module_type: str, name: str):
        """Decorator that registers a class under (module_type, name)."""

        def decorator(cls_to_register: type) -> type:
            cls._modules.setdefault(module_type, {})
            if name in cls._modules[module_type]:
                raise ValueError(f"Duplicate registration: {module_type}.{name}")
            cls._modules[module_type][name] = cls_to_register
            log.debug("registry.register", module_type=module_type, name=name)
            return cls_to_register

        return decorator

    @classmethod
    def create(cls, module_type: str, name: str, **kwargs: object) -> object:
        """Instantiate a registered component by (module_type, name)."""
        component_class = cls._modules.get(module_type, {}).get(name)
        if component_class is None:
            raise ValueError(f"No module named '{name}' for type '{module_type}'")
        return component_class(**kwargs)

    @classmethod
    def list_modules(cls, module_type: str | None = None) -> list[str] | dict[str, list[str]]:
        """Return registered names for a type, or all types if module_type is None."""
        if module_type:
            return list(cls._modules.get(module_type, {}).keys())
        return {k: list(v.keys()) for k, v in cls._modules.items()}

    @classmethod
    def validate(cls) -> None:
        """Raise TypeError if any registered entry is not callable."""
        for module_type, entries in cls._modules.items():
            for name, component_class in entries.items():
                if not callable(component_class):
                    raise TypeError(f"Registered entry {module_type}.{name} is not callable")

    @classmethod
    def clear(cls) -> None:
        """Remove all registrations. Intended for test isolation only."""
        cls._modules.clear()


# ---------------------------------------------------------------------------
# Initial registrations
# ---------------------------------------------------------------------------

from generation.generator import call_llm  # noqa: E402
from retrieval.duckdb_client import DuckDBVectorClient  # noqa: E402
from retrieval.embedder import MiniLMEmbedder  # noqa: E402

Registry.register("client", "duckdb")(DuckDBVectorClient)
Registry.register("embedder", "minilm")(MiniLMEmbedder)


class ClaudeGenerator:
    """Claude Sonnet generator, wrapping generation.generator.call_llm.

    Usage:
        gen = Registry.create("generator", "claude")
        system, messages = build_prompt(state, graded_chunks)
        answer = await gen.generate(llm, system, messages)
    """

    async def generate(self, llm: object, system: str, messages: list[dict]) -> str:
        return await call_llm(llm, system, messages)  # type: ignore[arg-type]


Registry.register("generator", "claude")(ClaudeGenerator)
