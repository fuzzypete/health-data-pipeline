"""
Configuration management for Health Data Pipeline.

Loads and validates configuration from config.yaml (or environment variables as fallback).
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional

import yaml
from dotenv import load_dotenv

log = logging.getLogger(__name__)

# Load .env file if it exists (for local development)
load_dotenv()

# Default configuration
DEFAULT_CONFIG = {
    'timezone': {
        'default': 'America/Los_Angeles',
    },
    'data': {
        'raw_dir': 'Data/Raw',
        'parquet_dir': 'Data/Parquet',
        'archive_dir': 'Data/Archive',
        'error_dir': 'Data/Error',
    },
    'ingestion': {
        'batch_size': 50,
        'max_retries': 3,
        'retry_delay_seconds': 5,
    },
    'api': {
        'concept2': {
            'base_url': 'https://log.concept2.com/api/',
        }
    }
}


class Config:
    """
    Configuration singleton for the pipeline.
    
    Loads configuration from:
    1. config.yaml in project root (if exists)
    2. Environment variables (as override)
    3. Defaults (as fallback)
    
    Example:
        >>> config = Config()
        >>> home_tz = config.get_home_timezone()
        >>> concept2_token = config.get_api_token('concept2')
    """
    
    _instance: Optional['Config'] = None
    _config: Dict[str, Any] = {}
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._load_config()
        return cls._instance
    
    def _load_config(self) -> None:
        """Load configuration from config.yaml and environment."""
        # Start with defaults
        self._config = DEFAULT_CONFIG.copy()
        
        # Try to load config.yaml
        config_path = Path('config.yaml')
        if config_path.exists():
            try:
                with open(config_path, 'r') as f:
                    yaml_config = yaml.safe_load(f)
                    if yaml_config:
                        self._merge_config(yaml_config)
                        log.info(f"Loaded configuration from {config_path}")
            except Exception as e:
                log.warning(f"Failed to load config.yaml: {e}. Using defaults.")
        else:
            log.info("No config.yaml found. Using defaults and environment variables.")
        
        # Override with environment variables
        self._load_env_overrides()
    
    def _merge_config(self, new_config: Dict[str, Any]) -> None:
        """Recursively merge new config into existing config."""
        def merge(base: Dict, update: Dict) -> Dict:
            for key, value in update.items():
                if key in base and isinstance(base[key], dict) and isinstance(value, dict):
                    merge(base[key], value)
                else:
                    base[key] = value
            return base
        
        merge(self._config, new_config)
    
    def _load_env_overrides(self) -> None:
        """Load overrides from environment variables."""
        # Timezone
        if env_tz := os.getenv('HDP_HOME_TIMEZONE'):
            self._config['timezone']['default'] = env_tz
        
        # API tokens
        if c2_token := os.getenv('CONCEPT2_API_TOKEN'):
            self._config['api']['concept2']['token'] = c2_token
        
        # Data directories
        if data_root := os.getenv('HDP_DATA_ROOT'):
            self._config['data']['raw_dir'] = f"{data_root}/Raw"
            self._config['data']['parquet_dir'] = f"{data_root}/Parquet"
            self._config['data']['archive_dir'] = f"{data_root}/Archive"
            self._config['data']['error_dir'] = f"{data_root}/Error"
    
    def get(self, key_path: str, default: Any = None) -> Any:
        """
        Get configuration value by dot-notation path.
        
        Example:
            >>> config.get('timezone.default')
            'America/Los_Angeles'
            >>> config.get('api.concept2.base_url')
            'https://log.concept2.com/api/'
        """
        keys = key_path.split('.')
        value = self._config
        
        for key in keys:
            if isinstance(value, dict) and key in value:
                value = value[key]
            else:
                return default
        
        return value
    
    def get_home_timezone(self) -> str:
        """Get the user's home timezone for Strategy A ingestion."""
        return self.get('timezone.default', 'America/Los_Angeles')
    
    def get_api_token(self, service: str) -> Optional[str]:
        """
        Get API token for a service.
        
        Args:
            service: Service name (e.g., 'concept2')
            
        Returns:
            API token if configured, None otherwise
        """
        return self.get(f'api.{service}.token')
    
    def get_api_base_url(self, service: str) -> Optional[str]:
        """Get API base URL for a service."""
        return self.get(f'api.{service}.base_url')
    
    def get_data_dir(self, dir_type: str) -> Path:
        """
        Get data directory path.
        
        Args:
            dir_type: One of 'raw', 'parquet', 'archive', 'error'
            
        Returns:
            Path object for the directory
        """
        dir_path = self.get(f'data.{dir_type}_dir', f'Data/{dir_type.title()}')
        return Path(dir_path)
    
    def get_batch_size(self) -> int:
        """Get ingestion batch size."""
        return self.get('ingestion.batch_size', 50)
    
    def get_max_retries(self) -> int:
        """Get maximum retry attempts for API calls."""
        return self.get('ingestion.max_retries', 3)
    
    def get_retry_delay(self) -> int:
        """Get retry delay in seconds."""
        return self.get('ingestion.retry_delay_seconds', 5)
    
    def validate(self) -> list[str]:
        """
        Validate configuration.
        
        Returns:
            List of validation errors (empty if valid)
        """
        errors = []
        
        # Check home timezone is valid
        try:
            from zoneinfo import ZoneInfo
            ZoneInfo(self.get_home_timezone())
        except Exception as e:
            errors.append(f"Invalid home timezone: {e}")
        
        # Check required API tokens
        if not self.get_api_token('concept2'):
            errors.append("Concept2 API token not configured (set CONCEPT2_API_TOKEN or add to config.yaml)")
        
        return errors
    
    def __repr__(self) -> str:
        """String representation (hides sensitive data)."""
        safe_config = self._config.copy()
        
        # Mask API tokens
        if 'api' in safe_config:
            for service in safe_config['api']:
                if 'token' in safe_config['api'][service]:
                    safe_config['api'][service]['token'] = '***MASKED***'
        
        return f"Config({safe_config})"


# Convenience functions for common operations
def get_config() -> Config:
    """Get the configuration singleton."""
    return Config()


def get_home_timezone() -> str:
    """Get the user's home timezone."""
    return get_config().get_home_timezone()


def get_concept2_token() -> Optional[str]:
    """Get Concept2 API token."""
    return get_config().get_api_token('concept2')


def get_concept2_base_url() -> str:
    """Get Concept2 API base URL."""
    return get_config().get_api_base_url('concept2') or 'https://log.concept2.com/api/'
