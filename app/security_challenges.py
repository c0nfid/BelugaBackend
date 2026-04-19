import time
from typing import Dict, Any

password_recovery_challenges: Dict[str, dict[str, Any]] = {}


def cleanup_recovery_challenges() -> None:
    now = time.time()
    expired = [
        key for key, value in password_recovery_challenges.items()
        if now > value.get("expires_at", 0)
    ]
    for key in expired:
        del password_recovery_challenges[key]