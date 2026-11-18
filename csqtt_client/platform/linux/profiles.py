"""Linux per-user profile storage with owner-only filesystem permissions."""
from dataclasses import asdict
import json
import os

from csqtt_client.config import PROFILE, LEGACY_PROFILE
from csqtt_client.models.profile import Profile


def save_profile(profile):
    PROFILE.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        PROFILE.parent.chmod(0o700)
    except OSError:
        pass
    temp = PROFILE.with_suffix('.tmp')
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(asdict(profile), stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temp, 0o600)
        os.replace(temp, PROFILE)
    finally:
        try:
            temp.unlink(missing_ok=True)
        except OSError:
            pass


def load_profile():
    source = PROFILE if PROFILE.exists() else LEGACY_PROFILE
    if not source.exists():
        return Profile()
    data = json.loads(source.read_text(encoding='utf-8'))
    return Profile(**{key: value for key, value in data.items() if key in Profile.__dataclass_fields__})


def profile_exists():
    return PROFILE.exists() or LEGACY_PROFILE.exists()


def delete_profile():
    PROFILE.unlink(missing_ok=True)
    LEGACY_PROFILE.unlink(missing_ok=True)
