import re


def input_to_meters(distance: str) -> float:
    """
    Converts a distance string to meters based on the units provided.

    Args:
        distance (str): A string containing a numerical value and a unit (e.g., "10 meters", "32ft.").

    Returns:
        float: The distance converted to meters.

    Raises:
        ValueError: If the unit of measurement is not specified or is invalid.
    """
    # Dictionary to map units to conversion factors (to meters)
    unit_conversions = {
        "meters": 1.0,
        "meter": 1.0,
        "m": 1.0,
        "feet": 0.3048,
        "foot": 0.3048,
        "ft": 0.3048,
        "kilometers": 1000.0,
        "kilometer": 1000.0,
        "km": 1000.0,
        "inches": 0.0254,
        "inch": 0.0254,
        "in": 0.0254
    }

    # Normalize the input: remove trailing dots and extra spaces, and lowercase
    distance = distance.strip().rstrip('.').lower()

    # Regular expression to handle both spaced and unspaced inputs
    match = re.match(r"^([\d\.]+)\s*([a-z]+)$", distance)

    if not match:
        raise ValueError(
            "Please specify a numerical value followed by a valid unit of measure (e.g., '10 meters', '32ft').")

    # Extract the numerical part and the unit part
    value_str, unit = match.groups()

    try:
        value = float(value_str)  # Convert the numerical part to a float
    except ValueError:
        raise ValueError("The distance value must be a valid number.")

    # Check if the unit is valid
    if unit not in unit_conversions:
        raise ValueError(
            f"Invalid unit of measure '{unit}'. Valid units are: {', '.join(unit_conversions.keys())}.")

    # Convert the value to meters
    return value * unit_conversions[unit]


