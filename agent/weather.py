import os
import requests
from langchain_core.tools import tool


@tool
def get_weather(city: str, days: int = 1) -> str:
    """查询指定城市的天气。
    city: 城市名，比如 'Shenzhen' 或 '深圳'。
    days: 查询未来几天的预报，1 表示只查今天，最多 3 天。
    当用户有出行计划或询问天气、气温、下雨、出行建议时使用此工具。
    """
    api_key = os.getenv("WEATHERSTACK_API_KEY")
    if not api_key:
        return "天气 API 密钥未配置。"

    url = "http://api.weatherstack.com/current"
    params = {
        "access_key": api_key,
        "query": city,
        "forecast_days": days,
    }

    try:
        resp = requests.get(url, params=params, timeout=10)
        data = resp.json()
    except Exception as e:
        return f"调用天气 API 失败：{e}"

    if "error" in data:
        return f"天气 API 返回错误：{data['error'].get('info', '未知错误')}"

    location = data.get("location", {}).get("name", city)
    current = data.get("current", {})
    desc = current.get("weather_descriptions", ["未知"])[0]
    temp = current.get("temperature", "None")
    feels = current.get("feelslike", "None")
    humidity = current.get("humidity", "None")
    wind = current.get("wind_speed", "None")

    lines = [
        f"{location}当前天气：{desc}，气温 {temp}°C，体感 {feels}°C，"
        f"湿度 {humidity}%，风速 {wind} km/h"
    ]

    forecast = data.get("forecast", {})
    for date, info in list(forecast.items())[:days]:
        day = info.get("date", date)
        min_t = info.get("mintemp", "None")
        max_t = info.get("maxtemp", "None")
        rain = info.get("totalprecip", "None")
        sun = info.get("sunhour", "None")
        lines.append(
            f"{day}：{min_t}~{max_t}°C，降水量 {rain} mm，日照 {sun} 小时"
        )

    return "\n".join(lines)