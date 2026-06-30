import importlib
import logging
import pkgutil

logger = logging.getLogger(__name__)


def discover_plugins() -> None:
    """Import all plugin packages so they register with the core registry."""
    import plugins as plugins_pkg

    for _, name, _ in pkgutil.iter_modules(plugins_pkg.__path__):
        module_name = f"plugins.{name}"
        logger.debug("Loading plugin package: %s", module_name)
        importlib.import_module(module_name)
        logger.debug("Loaded plugin: %s", name)
