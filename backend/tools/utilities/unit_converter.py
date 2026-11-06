"""Unit converter — built-in tool `unit_converter`."""

from typing import Any, Dict, Optional

from tools.base import ToolSpec, params

TOOL = ToolSpec(
    id="unit_converter",
    name="Unit Converter",
    icon="📏",
    category="Everyday Utilities",
    description="Converts length, mass, volume, speed, area, data, time and temperature. Input like '10 km to miles'.",
    default_config={},
    order=40,
    parameters=params({"value": {"type": "number"}, "from_unit": {"type": "string", "description": "e.g. km, lb, °F"},
                       "to_unit": {"type": "string", "description": "e.g. miles, kg, °C"}}),
    to_input=lambda a: f"{a['value']} {a['from_unit']} to {a['to_unit']}",
)


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    import re
    m = re.match(r"\s*(-?[\d.,]+)\s*([a-zA-Z°/² ]+?)\s+(?:to|in|->)\s+([a-zA-Z°/² ]+?)\s*$", inp)
    if not m:
        return "[Units] Input must look like '10 km to miles' or '72 F to C'."
    value = float(m.group(1).replace(",", ""))
    src, dst = m.group(2).strip().lower(), m.group(3).strip().lower()
    temps = {"c": "c", "celsius": "c", "°c": "c", "f": "f", "fahrenheit": "f", "°f": "f", "k": "k", "kelvin": "k"}
    if src in temps and dst in temps:
        to_c = {"c": lambda v: v, "f": lambda v: (v - 32) * 5 / 9, "k": lambda v: v - 273.15}[temps[src]](value)
        out = {"c": to_c, "f": to_c * 9 / 5 + 32, "k": to_c + 273.15}[temps[dst]]
        return f"[Units] {value:g} {src} = {out:.4g} {dst}"
    # Factor to the base unit of each dimension
    units = {
        "length": {"mm": 0.001, "cm": 0.01, "m": 1, "meter": 1, "meters": 1, "km": 1000, "kilometer": 1000, "kilometers": 1000,
                   "in": 0.0254, "inch": 0.0254, "inches": 0.0254, "ft": 0.3048, "foot": 0.3048, "feet": 0.3048,
                   "yd": 0.9144, "yard": 0.9144, "yards": 0.9144, "mi": 1609.344, "mile": 1609.344, "miles": 1609.344,
                   "nmi": 1852, "nautical mile": 1852, "nautical miles": 1852},
        "mass": {"mg": 1e-6, "g": 0.001, "gram": 0.001, "grams": 0.001, "kg": 1, "kilogram": 1, "kilograms": 1,
                 "t": 1000, "tonne": 1000, "tonnes": 1000, "oz": 0.028349523125, "ounce": 0.028349523125, "ounces": 0.028349523125,
                 "lb": 0.45359237, "lbs": 0.45359237, "pound": 0.45359237, "pounds": 0.45359237, "st": 6.35029318, "stone": 6.35029318},
        "volume": {"ml": 0.001, "l": 1, "liter": 1, "liters": 1, "litre": 1, "litres": 1, "m3": 1000,
                   "tsp": 0.00492892, "tbsp": 0.0147868, "cup": 0.236588, "cups": 0.236588, "pt": 0.473176, "pint": 0.473176, "pints": 0.473176,
                   "qt": 0.946353, "quart": 0.946353, "quarts": 0.946353, "gal": 3.785411784, "gallon": 3.785411784, "gallons": 3.785411784,
                   "fl oz": 0.0295735, "floz": 0.0295735},
        "speed": {"m/s": 1, "km/h": 1 / 3.6, "kmh": 1 / 3.6, "kph": 1 / 3.6, "mph": 0.44704, "knot": 0.514444, "knots": 0.514444, "kn": 0.514444},
        "area": {"m2": 1, "m²": 1, "km2": 1e6, "km²": 1e6, "ft2": 0.09290304, "ft²": 0.09290304, "sq ft": 0.09290304,
                 "acre": 4046.8564224, "acres": 4046.8564224, "ha": 10000, "hectare": 10000, "hectares": 10000},
        "data": {"b": 1, "byte": 1, "bytes": 1, "kb": 1e3, "mb": 1e6, "gb": 1e9, "tb": 1e12,
                 "kib": 1024, "mib": 1024 ** 2, "gib": 1024 ** 3, "tib": 1024 ** 4},
        "time": {"ms": 0.001, "s": 1, "sec": 1, "second": 1, "seconds": 1, "min": 60, "minute": 60, "minutes": 60,
                 "h": 3600, "hr": 3600, "hour": 3600, "hours": 3600, "day": 86400, "days": 86400,
                 "week": 604800, "weeks": 604800, "year": 31557600, "years": 31557600},
    }
    for dim, table in units.items():
        if src in table and dst in table:
            out = value * table[src] / table[dst]
            return f"[Units] {value:g} {src} = {out:.6g} {dst}"
    return f"[Units] Can't convert '{src}' to '{dst}'. Supported: length, mass, volume, speed, area, data, time, temperature."
