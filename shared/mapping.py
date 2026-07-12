def map_range(x: float, in_min: float, in_max: float, out_min: float, out_max: float) -> float:
    """Linearly remap x from [in_min, in_max] to [out_min, out_max], clamped to the input range."""
    lo, hi = min(in_min, in_max), max(in_min, in_max)
    x = max(lo, min(hi, x))
    return (x - in_min) / (in_max - in_min) * (out_max - out_min) + out_min
