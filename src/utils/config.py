import logging
from pathlib import Path
from typing import Dict

import yaml

logger = logging.getLogger(__name__)


def load_config(config_path: str) -> Dict:
    """
    Load and parse a YAML configuration file.

    Args:
        config_path: Path to the YAML configuration file.

    Returns:
        The parsed configuration as a dictionary.

    Raises:
        FileNotFoundError: If no file exists at config_path.
        yaml.YAMLError: If the file's contents are not valid YAML.
    """
    path = Path(config_path)
    try:
        with path.open('r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    except FileNotFoundError:
        logger.error("Config file not found: %s", path)
        raise
    except yaml.YAMLError as e:
        logger.error("Invalid YAML in config file %s: %s", path, e)
        raise
