"""Config-driven resolution of ammeter names to AmmeterDriver classes.

Each ammeter's config.yaml entry carries a "driver" key holding a dotted
import path ("package.module.ClassName"). Resolving drivers this way keeps
adding a new ammeter to exactly one new driver file plus one config entry —
no per-vendor branching or import list lives in this file.
"""

import importlib
import logging
from typing import Any, Dict

from src.drivers.base import AmmeterDriver

logger = logging.getLogger(__name__)


class DriverResolutionError(Exception):
    """Raised when a config's driver/module path can't be resolved to an AmmeterDriver subclass."""


def _resolve_driver_class(dotted_path: str) -> type:
    """Resolve a dotted "module.path.ClassName" string to a class.

    Args:
        dotted_path: e.g. "src.drivers.greenlee.GreenleeDriver".

    Returns:
        The resolved AmmeterDriver subclass.

    Raises:
        DriverResolutionError: If the path is malformed, the module can't
            be imported, the class doesn't exist on it, or the resolved
            object isn't an AmmeterDriver subclass.
    """
    if "." not in dotted_path:
        raise DriverResolutionError(
            f"driver path '{dotted_path}' must be a dotted 'module.ClassName' path"
        )

    module_path, class_name = dotted_path.rsplit(".", 1)

    try:
        module = importlib.import_module(module_path)
    except ImportError as e:
        raise DriverResolutionError(
            f"could not import module '{module_path}' for driver '{dotted_path}'"
        ) from e

    try:
        driver_class = getattr(module, class_name)
    except AttributeError as e:
        raise DriverResolutionError(
            f"module '{module_path}' has no class '{class_name}'"
        ) from e

    if not isinstance(driver_class, type) or not issubclass(driver_class, AmmeterDriver):
        raise DriverResolutionError(
            f"'{dotted_path}' does not resolve to an AmmeterDriver subclass"
        )

    return driver_class


def build_driver(name: str, ammeter_config: Dict[str, Any]) -> AmmeterDriver:
    """Build a single AmmeterDriver from its config.yaml entry.

    Args:
        name: The ammeter's config key, e.g. "greenlee".
        ammeter_config: That ammeter's config sub-dict; must contain
            "driver" (dotted class path).

    Returns:
        A constructed, not-yet-connected driver instance.

    Raises:
        DriverResolutionError: If "driver" is missing or unresolvable.
        KeyError: If required connection fields are missing from config.
        ValueError: If no command is available for this driver.
    """
    try:
        dotted_path = ammeter_config["driver"]
    except KeyError as e:
        raise DriverResolutionError(f"ammeter '{name}' config is missing 'driver' key") from e

    driver_class = _resolve_driver_class(dotted_path)
    return driver_class.from_config(name, ammeter_config)


def build_all_drivers(config: Dict[str, Any]) -> Dict[str, AmmeterDriver]:
    """Build every driver listed under config["ammeters"].

    Args:
        config: The full parsed config.yaml, containing an "ammeters" map
            of name -> ammeter config sub-dict.

    Returns:
        A dict mapping each ammeter name to its constructed driver.

    Raises:
        DriverResolutionError: If any entry's "driver" is missing or
            unresolvable.
        KeyError: If "ammeters" is missing, or an entry lacks required
            connection fields.
        ValueError: If an entry has no available command.
    """
    ammeters = config["ammeters"]
    return {name: build_driver(name, cfg) for name, cfg in ammeters.items()}
