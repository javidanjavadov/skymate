import requests

def search_city(city_name: str):
    url = f"https://www.metaweather.com/api/location/search/?query={city_name}"
    try:
        res = requests.get(url, timeout=10)
        res.raise_for_status()
        data = res.json()
        if data:
            return data[0]['woeid']
        return None
    except requests.RequestException as e:
        print(f"Error during city search: {e}")
        return None

def get_weather_by_city(city_name: str):
    woeid = search_city(city_name)
    if not woeid:
        return None
    try:
        weather_url = f"https://www.metaweather.com/api/location/{woeid}/"
        res = requests.get(weather_url, timeout=10)
        res.raise_for_status()
        weather_data = res.json()
        # sadə nümunə üçün temperature və status çıxarırıq
        today_weather = weather_data['consolidated_weather'][0]
        temp = today_weather['the_temp']
        state = today_weather['weather_state_name']
        return f"Weather in {city_name}: {state}, Temperature: {temp:.1f}°C"
    except requests.RequestException as e:
        print(f"Error during weather fetch: {e}")
        return None
