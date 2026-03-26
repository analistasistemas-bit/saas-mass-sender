from __future__ import annotations

from typing import Any


SPEED_PROFILE_PRESETS = {
    'conservative': {
        'send_delay_min_seconds': 15,
        'send_delay_max_seconds': 45,
        'batch_pause_min_seconds': 25,
        'batch_pause_max_seconds': 40,
        'batch_size_initial': 5,
        'batch_size_max': 15,
        'batch_growth_step': 2,
        'batch_growth_streak_required': 3,
        'batch_shrink_step': 2,
        'batch_shrink_error_streak_required': 2,
        'batch_size_floor': 5,
    },
    'aggressive': {
        'send_delay_min_seconds': 8,
        'send_delay_max_seconds': 20,
        'batch_pause_min_seconds': 15,
        'batch_pause_max_seconds': 30,
        'batch_size_initial': 10,
        'batch_size_max': 25,
        'batch_growth_step': 5,
        'batch_growth_streak_required': 2,
        'batch_shrink_step': 3,
        'batch_shrink_error_streak_required': 1,
        'batch_size_floor': 8,
    },
}

DEFAULT_SPEED_PROFILE = 'conservative'
CONTROLLED_PROFILE_FIELDS = tuple(SPEED_PROFILE_PRESETS[DEFAULT_SPEED_PROFILE].keys())


def normalize_speed_profile(value: str | None) -> str:
    normalized = str(value or '').strip().lower()
    if normalized in SPEED_PROFILE_PRESETS or normalized == 'custom':
        return normalized
    return DEFAULT_SPEED_PROFILE


def preset_values(profile: str) -> dict[str, int]:
    normalized = normalize_speed_profile(profile)
    preset_name = normalized if normalized in SPEED_PROFILE_PRESETS else DEFAULT_SPEED_PROFILE
    return dict(SPEED_PROFILE_PRESETS[preset_name])


def campaign_profile_settings(campaign: Any) -> dict[str, int]:
    return {field: int(getattr(campaign, field)) for field in CONTROLLED_PROFILE_FIELDS}


def resolve_speed_profile(values: dict[str, int]) -> str:
    for profile_name, preset in SPEED_PROFILE_PRESETS.items():
        if all(int(values[field]) == int(preset[field]) for field in CONTROLLED_PROFILE_FIELDS):
            return profile_name
    return 'custom'


def apply_speed_profile(campaign: Any, profile: str) -> dict[str, int]:
    values = preset_values(profile)
    for field, value in values.items():
        setattr(campaign, field, int(value))
    campaign.speed_profile = normalize_speed_profile(profile)
    return values


def runtime_profile_payload(campaign: Any, batch_size_current: int | None = None) -> dict[str, Any]:
    values = campaign_profile_settings(campaign)
    effective_profile = resolve_speed_profile(values)
    selected_profile = normalize_speed_profile(getattr(campaign, 'speed_profile', DEFAULT_SPEED_PROFILE))
    profile_source = 'preset' if selected_profile != 'custom' and selected_profile == effective_profile else 'manual_override'
    return {
        'selected_profile': selected_profile,
        'effective_profile': effective_profile,
        'batch_size_current': int(batch_size_current if batch_size_current is not None else campaign.batch_size_initial),
        'batch_pause_min_seconds': int(campaign.batch_pause_min_seconds),
        'batch_pause_max_seconds': int(campaign.batch_pause_max_seconds),
        'profile_source': profile_source,
    }
