import json
import os
import logging
from typing import Dict, Any

# Define the path to the default config file relative to this file's location
DEFAULT_CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'config.json')
DEFAULT_PROMPTS_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'prompts.json')

# Konfiguracja logowania
logger = logging.getLogger(__name__)

# Default configuration content
DEFAULT_CONFIG = {
    "prompts_file": "prompts.json",
    "evaluation_weights": {
        "syntax_valid": 3.0,
        "runs_without_error": 2.5,
        "contains_expected_keywords": 2.0,
        "has_function_def": 1.5,
        "has_error_handling": 1.0,
        "has_docstring": 1.0,
        "has_imports": 0.5,
        "code_length_reasonable": 0.5
    },
    "timeouts": {
        "request_timeout": 60,
        "execution_timeout": 10,
        "delay_between_requests": 1
    },
    "report_config": {
        "title": "Raport Testowania Modeli LLM - Generowanie Kodu",
        "include_raw_responses": True,
        "include_execution_output": True,
        "max_code_display_lines": 50,
        "show_detailed_metrics": True
    },
    "colors": {
        "success": "#28a745",
        "error": "#dc3545",
        "warning": "#ffc107",
        "info": "#17a2b8",
        "primary": "#007bff",
        "light": "#f8f9fa",
        "dark": "#343a40"
    }
}

# Default prompts content
DEFAULT_PROMPTS = [
    {
        "name": "Simple Addition Function",
        "prompt": "Write a Python function called 'add_numbers' that takes two parameters (a, b) and returns their sum. Include a docstring and a simple test call.",
        "expected_keywords": ["def", "add_numbers", "return", "a", "b"],
        "expected_behavior": "function_definition"
    }
]

def ensure_config_files_exist():
    """
    Ensures that the default configuration files exist.
    If they don't, creates them with default content.
    """
    # Check and create config.json if needed
    if not os.path.exists(DEFAULT_CONFIG_PATH):
        try:
            with open(DEFAULT_CONFIG_PATH, 'w', encoding='utf-8') as f:
                json.dump(DEFAULT_CONFIG, f, indent=4)
            logger.info(f"Created default configuration file at {DEFAULT_CONFIG_PATH}")
        except Exception as e:
            logger.error(f"Failed to create default configuration file: {e}")
    
    # Check and create prompts.json if needed
    if not os.path.exists(DEFAULT_PROMPTS_PATH):
        try:
            with open(DEFAULT_PROMPTS_PATH, 'w', encoding='utf-8') as f:
                json.dump(DEFAULT_PROMPTS, f, indent=4)
            logger.info(f"Created default prompts file at {DEFAULT_PROMPTS_PATH}")
        except Exception as e:
            logger.error(f"Failed to create default prompts file: {e}")

def load_config_file(file_path: str) -> Dict[str, Any]:
    """Loads a configuration file (JSON or YAML)."""
    if not os.path.exists(file_path):
        # Try to resolve relative to the project root if it's not an absolute path
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        abs_path = os.path.join(project_root, file_path)
        if not os.path.exists(abs_path):
             raise FileNotFoundError(f"Configuration file not found at {file_path} or {abs_path}")
        file_path = abs_path

    with open(file_path, 'r', encoding='utf-8') as f:
        if file_path.endswith('.json'):
            return json.load(f)
        elif file_path.endswith(('.yaml', '.yml')):
            try:
                import yaml
                return yaml.safe_load(f)
            except ImportError:
                raise ImportError("PyYAML is required to load YAML configuration files. Please install it using 'poetry install' or 'pip install pyyaml'.")
        else:
            raise ValueError(f"Unsupported configuration file format: {file_path}. Please use .json or .yaml/.yml.")

def deep_merge(source: Dict, destination: Dict) -> Dict:
    """
    Deeply merges two dictionaries. The `source` dictionary is merged into the `destination` dictionary.
    """
    for key, value in source.items():
        if isinstance(value, dict) and key in destination and isinstance(destination[key], dict):
            destination[key] = deep_merge(value, destination[key])
        else:
            destination[key] = value
    return destination

def get_config(user_config_path: str = None) -> Dict[str, Any]:
    """
    Loads the default configuration and merges it with a user-provided configuration.
    If the default configuration files don't exist, they are created automatically.
    """
    # Ensure default configuration files exist
    ensure_config_files_exist()
    
    # Load default configuration
    try:
        default_config = load_config_file(DEFAULT_CONFIG_PATH)
    except FileNotFoundError:
        logger.warning(f"Default configuration file not found, using built-in defaults")
        default_config = DEFAULT_CONFIG

    if user_config_path:
        # Load user configuration
        user_config = load_config_file(user_config_path)
        # Merge user config into default config
        # The user's config takes precedence
        return deep_merge(user_config, default_config)

    return default_config
