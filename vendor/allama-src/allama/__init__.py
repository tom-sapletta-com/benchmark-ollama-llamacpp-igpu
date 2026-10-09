"""
Allama - A Python package for interacting with AI models.

This package provides tools and utilities for working with various AI models,
including model management, inference, and testing.
"""

__version__ = '0.1.0'

# Import key components to make them available at the package level
from .config_loader import *  # noqa
from .main import *    # noqa

__all__ = [
    # Add any important classes/functions to be exposed at package level
    'get_config',
    'load_config_file',
    'ensure_config_files_exist'
]
