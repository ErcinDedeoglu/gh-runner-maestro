import os
import json
import logging
import re
from typing import List, Dict, Any

logger = logging.getLogger(__name__)


def validate_github_url(url: str) -> bool:
    """Validate GitHub repository or organization URL format"""
    if not url:
        return False

    # Match GitHub URLs
    github_patterns = [
        r"^https://github\.com/[a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+$",
        r"^https://github\.com/[a-zA-Z0-9_.-]+$",
    ]

    return any(re.match(pattern, url) for pattern in github_patterns)


def validate_token(token: str) -> bool:
    """Validate GitHub token format (basic check)"""
    if not token:
        return False

    # GitHub tokens typically start with 'ghp_', 'gho_', 'ghu_', 'ghs_', or 'ghr_'
    return token.startswith(("ghp_", "gho_", "ghu_", "ghs_", "ghr_"))


def validate_runner_config(config: Dict[str, Any]) -> Dict[str, Any]:
    """Validate and normalize a single runner configuration"""
    errors = []

    # Normalize keys for backward compatibility
    if "repo_url" in config:
        config["url"] = config.pop("repo_url")
    if "runner_count" in config:
        config["count"] = config.pop("runner_count")

    # Validate URL
    url = config.get("url", "").strip()
    if not url:
        errors.append("URL is required")
    elif not validate_github_url(url):
        errors.append(f"Invalid GitHub URL format: {url}")

    # Validate count
    try:
        count = int(config.get("count", 1))
        if count < 1 or count > 50:  # Reasonable limit
            errors.append("Count must be between 1 and 50")
        config["count"] = count
    except (ValueError, TypeError):
        errors.append("Count must be a positive integer")

    # Validate labels
    labels = config.get("labels", [])
    if isinstance(labels, str):
        labels = [label.strip() for label in labels.split(",") if label.strip()]
    elif not isinstance(labels, list):
        labels = []
    config["labels"] = labels

    # Validate image
    image = config.get("image", os.getenv("RUNNER_IMAGE", "dublok/gh-runner:latest"))
    if not image or not isinstance(image, str):
        errors.append("Invalid runner image specified")
    config["image"] = image

    ephemeral = config.get("ephemeral", True)
    if isinstance(ephemeral, str):
        ephemeral = ephemeral.lower() in ("true", "1", "yes")
    config["ephemeral"] = bool(ephemeral)

    disable_update = config.get("disable_update", True)
    if isinstance(disable_update, str):
        disable_update = disable_update.lower() in ("true", "1", "yes")
    config["disable_update"] = bool(disable_update)

    # Validate token (will be checked later against environment)
    token = config.get("token")
    if token and not validate_token(token):
        logger.warning(f"Token format may be invalid for {url}")

    if errors:
        raise ValueError(f"Configuration validation failed: {'; '.join(errors)}")

    return config


def load_runner_configs() -> List[Dict[str, Any]]:
    """
    Load and validate runner configuration from RUNNERS_MATRIX JSON or legacy environment variables.

    Returns:
        List of validated runner configurations with keys: url, count, labels, token, image
    """
    runners_matrix = os.getenv("RUNNERS_MATRIX")

    try:
        if runners_matrix:
            logger.info("Loading configuration from RUNNERS_MATRIX")
            runners = json.loads(runners_matrix)

            if not isinstance(runners, list):
                raise ValueError("RUNNERS_MATRIX must be a JSON array")

            validated_configs = []
            for i, entry in enumerate(runners):
                try:
                    # Resolve token with fallback chain
                    token = (
                        entry.get("token")
                        or os.getenv("DEFAULT_RUNNER_TOKEN")
                        or os.getenv("GITHUB_PAT")
                    )

                    if not token:
                        raise ValueError(f"No token available for entry {i + 1}")

                    entry["token"] = token
                    validated_config = validate_runner_config(entry)
                    validated_configs.append(validated_config)

                except ValueError as e:
                    logger.error(f"Invalid runner config entry {i + 1}: {e}")
                    raise

            logger.info(f"Loaded {len(validated_configs)} runner configurations")
            return validated_configs

        else:
            # Legacy single runner setup
            logger.info("Loading legacy single runner configuration")

            url = os.getenv("RUNNER_URL")
            if not url:
                raise ValueError("RUNNER_URL is required for legacy configuration")

            token = os.getenv("GITHUB_PAT")
            if not token:
                raise ValueError("GITHUB_PAT is required for legacy configuration")

            legacy_config = {
                "url": url,
                "count": int(os.getenv("RUNNER_COUNT", 1)),
                "labels": os.getenv("RUNNER_LABELS", "").split(",")
                if os.getenv("RUNNER_LABELS")
                else [],
                "token": token,
                "image": os.getenv("RUNNER_IMAGE", "dublok/gh-runner:latest"),
            }

            validated_config = validate_runner_config(legacy_config)
            logger.info("Loaded legacy single runner configuration")
            return [validated_config]

    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in RUNNERS_MATRIX: {e}")
        raise ValueError(f"Invalid JSON in RUNNERS_MATRIX: {e}")
    except Exception as e:
        logger.error(f"Failed to load runner configurations: {e}")
        raise
