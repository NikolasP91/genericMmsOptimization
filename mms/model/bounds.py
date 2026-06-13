def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def value_at(value, index, default=0.0):
    if isinstance(value, list):
        if 0 <= index < len(value) and _is_number(value[index]):
            return float(value[index])
        return default
    if _is_number(value):
        return float(value)
    return default


def reserve_activation_bound(unit, reserve_field, direction_index, period_index, operating_state=None):
    reserve_limits = unit.get(reserve_field, [0.0, 0.0])
    reserve_cap = value_at(reserve_limits, direction_index, 0.0)
    availability = max(0.0, value_at(unit.get("availability", []), period_index, reserve_cap))

    if direction_index == 0:
        if operating_state is not None:
            state_max = value_at(operating_state.get("max-power"), period_index, availability)
            state_max = min(state_max, value_at(operating_state.get("user_max_power"), period_index, state_max))
            availability = min(availability, max(0.0, state_max))
        return max(0.0, min(reserve_cap, availability))

    if operating_state is not None:
        state_min = value_at(operating_state.get("min-power"), period_index, 0.0)
        state_min = max(state_min, value_at(operating_state.get("user_min_power"), period_index, state_min))
        availability = max(0.0, availability - max(0.0, state_min))
    return max(0.0, min(reserve_cap, availability))


def forbidden_zone_big_m(unit, zone, period_index, fallback_m):
    availability = max(0.0, value_at(unit.get("availability", []), period_index, fallback_m))
    lower = float(zone[0])
    upper = float(zone[1])
    bound = max(
        abs(availability - lower),
        abs(availability - upper),
        abs(lower),
        abs(upper),
        1.0,
    )
    return min(float(fallback_m), 1.25 * bound)
