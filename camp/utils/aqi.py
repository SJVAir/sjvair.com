def aqi_label(aqi):
    aqi = float(aqi)
    if aqi <= 50:
        return 'Good'
    elif aqi > 50 and aqi <= 100:
        return 'Moderate'
    elif aqi > 100 and aqi <= 150:
        return 'Unhealthy for Sensitive Groups'
    elif aqi > 150 and aqi <= 200:
        return 'Unhealthy'
    elif aqi > 200 and aqi <= 300:
        return 'Very Unhealthy'
    elif aqi > 300 and aqi <= 400:
        return 'Hazardous'
    elif aqi > 400 and aqi <= 500:
        return 'Hazardous'
    return 'Out of Range'
