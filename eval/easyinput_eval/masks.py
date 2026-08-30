from typing import Any

from .constants import STEPS_PER_BAR, TRACK_IDS


class MaskConversionError(ValueError):
    """Raised when a track cannot be represented as a 16-bit trigger mask."""


def track_to_mask(track: list[int]) -> int:
    if not isinstance(track, list) or len(track) != STEPS_PER_BAR:
        raise MaskConversionError("track must be a list with exactly 16 steps")

    mask = 0
    for index, value in enumerate(track):
        if type(value) is not int or value not in (0, 1):
            raise MaskConversionError(f"step {index + 1} must be integer 0 or 1")
        if value:
            mask |= 1 << index
    return mask


def pattern_to_masks(pattern: dict[str, Any]) -> dict[str, int]:
    tracks = pattern.get("tracks") if isinstance(pattern, dict) else None
    if not isinstance(tracks, dict):
        raise MaskConversionError("pattern.tracks must be an object")
    if set(tracks) != set(TRACK_IDS):
        raise MaskConversionError("pattern.tracks must contain exactly the six track IDs")
    return {track_id: track_to_mask(tracks[track_id]) for track_id in TRACK_IDS}


def masks_as_firmware_order(pattern: dict[str, Any]) -> list[int]:
    masks = pattern_to_masks(pattern)
    return [masks[track_id] for track_id in TRACK_IDS]
