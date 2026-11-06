"""Weather — built-in tool `weather`."""

import os
from typing import Any, Dict, Optional

import httpx

from tools.base import Select, ToolSpec, enum, params

TOOL = ToolSpec(
    id="weather",
    name="Weather",
    icon="🌤️",
    category="Everyday Utilities",
    description="Gets current weather and forecast for any city. Uses Open-Meteo (free, no key) or OpenWeatherMap with an API key.",
    default_config={"api_key": "", "units": "metric"},
    order=20,
    selects={
        "units": Select("Units", (("metric", "Metric (°C)"), ("imperial", "Imperial (°F)"))),
    },
    parameters=params({"city": {"type": "string", "description": "City, e.g. Berlin or Austin, TX"}},
                      {"units": enum(["metric", "imperial"], "°C / km/h or °F / mph")}),
    input_param="city",
)


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    api_key = cfg.get("api_key", "") or os.environ.get("OPENWEATHERMAP_API_KEY", "")
    units = cfg.get("units", "metric")
    city = inp.strip()
    if not city:
        return "[Weather] Please provide a city name as input."

    if api_key:
        # OpenWeatherMap — requires a free API key from openweathermap.org
        unit_param = {"metric": "metric", "imperial": "imperial"}.get(units, "metric")
        unit_label = "°C" if unit_param == "metric" else "°F"
        wind_label = "m/s" if unit_param == "metric" else "mph"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    "https://api.openweathermap.org/data/2.5/weather",
                    params={"q": city, "appid": api_key, "units": unit_param},
                )
                resp.raise_for_status()
                d = resp.json()
                name = d.get("name", city)
                country = d.get("sys", {}).get("country", "")
                desc = d.get("weather", [{}])[0].get("description", "").capitalize()
                temp = d.get("main", {}).get("temp", "?")
                feels = d.get("main", {}).get("feels_like", "?")
                humidity = d.get("main", {}).get("humidity", "?")
                wind = d.get("wind", {}).get("speed", "?")
                visibility = d.get("visibility", "?")
                vis_km = round(int(visibility) / 1000, 1) if str(visibility).isdigit() else visibility
                return (
                    f"[Weather: {name}, {country}]\n"
                    f"  Condition  : {desc}\n"
                    f"  Temperature: {temp}{unit_label} (feels like {feels}{unit_label})\n"
                    f"  Humidity   : {humidity}%\n"
                    f"  Wind       : {wind} {wind_label}\n"
                    f"  Visibility : {vis_km} km"
                )
        except Exception as e:
            return f"[Weather/OpenWeatherMap] Error: {e}"

    # Open-Meteo — completely free, no API key needed
    # Step 1: geocode the city name via the Open-Meteo geocoding API
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            geo_resp = await client.get(
                "https://geocoding-api.open-meteo.com/v1/search",
                params={"name": city, "count": 1, "language": "en", "format": "json"},
            )
            geo_resp.raise_for_status()
            geo = geo_resp.json()
            results = geo.get("results", [])
            if not results:
                return f"[Weather] City not found: '{city}'. Try a different spelling or add a country code (e.g. 'Paris, FR')."
            loc = results[0]
            lat, lon = loc["latitude"], loc["longitude"]
            loc_name = loc.get("name", city)
            loc_country = loc.get("country", "")
            admin = loc.get("admin1", "")
            display = f"{loc_name}, {admin}, {loc_country}".strip(", ")

            # Step 2: fetch current weather
            unit_temp = "fahrenheit" if units == "imperial" else "celsius"
            unit_wind = "mph" if units == "imperial" else "kmh"
            wx_resp = await client.get(
                "https://api.open-meteo.com/v1/forecast",
                params={
                    "latitude": lat,
                    "longitude": lon,
                    "current": "temperature_2m,relative_humidity_2m,apparent_temperature,precipitation,weather_code,wind_speed_10m,wind_direction_10m",
                    "temperature_unit": unit_temp,
                    "wind_speed_unit": unit_wind,
                    "forecast_days": 3,
                    "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_sum",
                    "timezone": "auto",
                },
            )
            wx_resp.raise_for_status()
            wx = wx_resp.json()

        cur = wx.get("current", {})
        temp = cur.get("temperature_2m", "?")
        feels = cur.get("apparent_temperature", "?")
        humidity = cur.get("relative_humidity_2m", "?")
        wind_speed = cur.get("wind_speed_10m", "?")
        wind_dir = cur.get("wind_direction_10m", "?")
        precip = cur.get("precipitation", 0)
        wcode = cur.get("weather_code", 0)

        # WMO weather code → simple description
        _WMO: Dict[int, str] = {
            0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
            45: "Foggy", 48: "Icy fog",
            51: "Light drizzle", 53: "Moderate drizzle", 55: "Dense drizzle",
            61: "Slight rain", 63: "Moderate rain", 65: "Heavy rain",
            71: "Slight snow", 73: "Moderate snow", 75: "Heavy snow",
            80: "Slight showers", 81: "Moderate showers", 82: "Heavy showers",
            95: "Thunderstorm", 96: "Thunderstorm with hail", 99: "Heavy thunderstorm",
        }
        condition = _WMO.get(int(wcode), f"Code {wcode}")
        t_unit = "°F" if units == "imperial" else "°C"
        w_unit = "mph" if units == "imperial" else "km/h"

        lines = [
            f"[Weather: {display}]  (via Open-Meteo, no API key needed)",
            f"  Condition  : {condition}",
            f"  Temperature: {temp}{t_unit} (feels like {feels}{t_unit})",
            f"  Humidity   : {humidity}%",
            f"  Wind       : {wind_speed} {w_unit} at {wind_dir}°",
            f"  Precip.    : {precip} mm",
        ]

        # 3-day forecast
        daily = wx.get("daily", {})
        dates = daily.get("time", [])
        max_temps = daily.get("temperature_2m_max", [])
        min_temps = daily.get("temperature_2m_min", [])
        precip_sums = daily.get("precipitation_sum", [])
        wcodes = daily.get("weather_code", [])
        if dates:
            lines.append("\n  3-Day Forecast:")
            for i in range(min(3, len(dates))):
                fc_cond = _WMO.get(int(wcodes[i]) if i < len(wcodes) else 0, "")
                fc_max = max_temps[i] if i < len(max_temps) else "?"
                fc_min = min_temps[i] if i < len(min_temps) else "?"
                fc_rain = precip_sums[i] if i < len(precip_sums) else 0
                lines.append(f"    {dates[i]}: {fc_cond}, {fc_min}–{fc_max}{t_unit}, rain {fc_rain}mm")

        return "\n".join(lines)
    except Exception as e:
        return f"[Weather/Open-Meteo] Error: {e}"
