from typing import Optional
from django.contrib.gis.db import models
from django.contrib.postgres.fields import DateTimeRangeField
from django.db.models import Avg, F, Q
from django.utils import timezone
from datetime import datetime, timedelta, time
import requests


MIN_INVERSION_STRENGTH_F = 2.7
MAX_BOUNDARY_LAYER_HEIGHT_M = 400.0
MAX_WIND_SPEED_MPH = 4.5
PM25_THRESHOLD = 35.0
MIN_PERSISTENCE_HOURS_WATCH = 6
MIN_PERSISTENCE_HOURS_ADVISORY = 12
MIN_PERSISTENCE_HOURS_PERSISTENT = 48


class InversionType(models.TextChoices):
    RADIATION = 'radiation', 'Radiation Inversion'
    SUBSIDENCE = 'subsidence', 'Subsidence Inversion'
    FRONTAL = 'frontal', 'Frontal Inversion'


class InversionSeverity(models.TextChoices):
    WATCH = 'watch', 'Inversion Watch (6-12 hours)'
    ADVISORY = 'advisory', 'Inversion Advisory (12-48 hours)'
    PERSISTENT = 'persistent', 'Persistent Inversion Event (48+ hours)'


class Inversion(models.Model):
    """
    Base model for atmospheric inversion events that trap pollution.
    """

    location = models.PointField()
    inversion_type = models.CharField(
        max_length=20,
        choices=InversionType.choices,
        help_text='Type of atmospheric inversion',
    )
    severity = models.CharField(
        max_length=20,
        choices=InversionSeverity.choices,
        null=True,
        blank=True,
        help_text='Severity classification based on duration and PM2.5 confirmation',
    )
    detected_at = models.DateTimeField(auto_now_add=True)
    period = DateTimeRangeField(
        help_text='Time range during which the inversion was detected'
    )

    # Meteorological data from OpenMeteo
    temperature_gradient = models.FloatField(
        help_text='Temperature difference between surface and upper air (°F)'
    )
    surface_temperature = models.FloatField(help_text='Surface temperature (°F)')
    upper_air_temperature = models.FloatField(help_text='Upper air temperature (°F)')
    wind_speed = models.FloatField(help_text='Wind speed (mph)')
    pressure = models.FloatField(help_text='Atmospheric pressure (hPa)')
    boundary_layer_height = models.FloatField(
        null=True, blank=True, help_text='Planetary boundary layer height (meters)'
    )

    # Inversion characteristics
    strength = models.FloatField(
        help_text='Strength of inversion (temperature gradient magnitude)'
    )
    confidence = models.FloatField(
        default=0.0, help_text='Confidence level of detection (0-1)'
    )

    # PM2.5 confirmation metrics
    pm25_confirmed = models.BooleanField(
        default=False,
        help_text='Whether pollution trapping was confirmed by PM2.5 behavior',
    )
    pm25_night_mean = models.FloatField(
        null=True, blank=True, help_text='Mean PM2.5 during nighttime hours (μg/m³)'
    )
    pm25_day_mean = models.FloatField(
        null=True, blank=True, help_text='Mean PM2.5 during daytime hours (μg/m³)'
    )
    pm25_previous_day_mean = models.FloatField(
        null=True,
        blank=True,
        help_text='Mean PM2.5 from previous day for trend analysis (μg/m³)',
    )
    pm25_night_day_ratio = models.FloatField(
        null=True, blank=True, help_text='Ratio of nighttime to daytime PM2.5'
    )

    # Duration tracking
    persistence_hours = models.IntegerField(
        default=0, help_text='Number of consecutive hours with inversion conditions'
    )

    # Additional metadata
    notes = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['-detected_at']
        indexes = [
            models.Index(fields=['inversion_type', '-detected_at']),
            models.Index(fields=['is_active', '-detected_at']),
            models.Index(fields=['pm25_confirmed', '-detected_at']),
            models.Index(fields=['severity', '-detected_at']),
        ]

    def __str__(self):
        return f'{self.get_inversion_type_display()} at {self.location} ({self.detected_at})'

    @property
    def duration(self):
        """Calculate duration of the inversion event."""
        if self.period:
            return self.period.upper - self.period.lower
        return timedelta(hours=self.persistence_hours)

    def confirm_with_pm25(
        self, min_night_day_ratio: float = 1.2, min_day_over_day_increase: float = 1.1
    ) -> bool:
        """
        Confirm inversion impact using PM2.5 behavior.

        Args:
            min_night_day_ratio: Minimum ratio of night/day PM2.5 to confirm trapping
            min_day_over_day_increase: Minimum day-over-day increase ratio

        Returns:
            True if pollution trapping is confirmed
        """
        if self.pm25_night_mean is None or self.pm25_day_mean is None:
            return False

        # Calculate night/day ratio if not already set
        if self.pm25_night_day_ratio is None:
            self.pm25_night_day_ratio = self.pm25_night_mean / max(
                self.pm25_day_mean, 1.0
            )

        # Check night/day ratio (elevated PM2.5 at night suggests trapping)
        night_day_confirmed = self.pm25_night_day_ratio >= min_night_day_ratio

        # Check day-over-day trend (increasing PM2.5 suggests accumulation)
        trend_confirmed = (
            self.pm25_previous_day_mean is not None
            and self.pm25_day_mean
            >= self.pm25_previous_day_mean * min_day_over_day_increase
        )

        self.pm25_confirmed = night_day_confirmed or trend_confirmed
        return self.pm25_confirmed

    def update_severity(self):
        """
        Update severity classification based on duration and PM2.5 confirmation.
        """
        if (
            self.persistence_hours >= MIN_PERSISTENCE_HOURS_PERSISTENT
            and self.pm25_confirmed
        ):
            self.severity = InversionSeverity.PERSISTENT
        elif self.persistence_hours >= MIN_PERSISTENCE_HOURS_ADVISORY:
            self.severity = InversionSeverity.ADVISORY
        elif self.persistence_hours >= MIN_PERSISTENCE_HOURS_WATCH:
            self.severity = InversionSeverity.WATCH
        else:
            self.severity = None


class RadiationInversion(models.Model):
    """
    Radiation inversions occur on clear, calm nights when the ground cools rapidly.
    Most common in valleys and basins.
    """

    inversion = models.OneToOneField(
        Inversion, on_delete=models.CASCADE, related_name='radiation_details'
    )

    # Specific characteristics
    cloud_cover = models.FloatField(help_text='Cloud cover percentage (0-100)')
    solar_radiation = models.FloatField(help_text='Solar radiation (W/m²)')
    time_of_day = models.CharField(
        max_length=10,
        choices=[('night', 'Night'), ('dawn', 'Dawn'), ('day', 'Day')],
        help_text='Time period when detected',
    )
    ground_cooling_rate = models.FloatField(
        null=True, blank=True, help_text='Rate of ground cooling (°F/hour)'
    )

    class Meta:
        ordering = ['-inversion__detected_at']

    def __str__(self):
        return f'Radiation Inversion: {self.inversion}'


class SubsidenceInversion(models.Model):
    """
    Subsidence inversions form when air descends and warms in high-pressure systems.
    Can persist for days and cover large areas.
    """

    inversion = models.OneToOneField(
        Inversion, on_delete=models.CASCADE, related_name='subsidence_details'
    )

    # Specific characteristics
    pressure_system = models.CharField(
        max_length=20,
        choices=[('high', 'High Pressure'), ('low', 'Low Pressure')],
        default='high',
    )
    subsidence_rate = models.FloatField(
        null=True, blank=True, help_text='Rate of air descent (Pa/s or hPa/hour)'
    )
    inversion_height = models.FloatField(
        help_text='Height of inversion layer (meters above ground)'
    )
    layer_thickness = models.FloatField(
        null=True, blank=True, help_text='Thickness of inversion layer (meters)'
    )

    class Meta:
        ordering = ['-inversion__detected_at']

    def __str__(self):
        return f'Subsidence Inversion: {self.inversion}'


class FrontalInversion(models.Model):
    """
    Frontal inversions occur when warm air overrides cooler air at weather fronts.
    Associated with frontal systems and can move geographically.
    """

    inversion = models.OneToOneField(
        Inversion, on_delete=models.CASCADE, related_name='frontal_details'
    )

    # Specific characteristics
    front_type = models.CharField(
        max_length=20,
        choices=[
            ('warm', 'Warm Front'),
            ('cold', 'Cold Front'),
            ('stationary', 'Stationary Front'),
            ('occluded', 'Occluded Front'),
        ],
        help_text='Type of weather front',
    )
    front_direction = models.FloatField(
        null=True, blank=True, help_text='Direction of front movement (degrees, 0-360)'
    )
    front_speed = models.FloatField(
        null=True, blank=True, help_text='Speed of front movement (m/s)'
    )
    warm_air_temperature = models.FloatField(help_text='Warm air mass temperature (°F)')
    cold_air_temperature = models.FloatField(help_text='Cold air mass temperature (°F)')

    class Meta:
        ordering = ['-inversion__detected_at']

    def __str__(self):
        return f'Frontal Inversion ({self.get_front_type_display()}): {self.inversion}'


def get_pm25_metrics(monitor, start_time, end_time):
    """
    Calculate PM2.5 metrics for inversion confirmation.

    Args:
        monitor: Monitor object or ID to query PM2.5 data
        start_time: Start of analysis period
        end_time: End of analysis period

    Returns:
        Dictionary with PM2.5 metrics
    """
    from camp.apps.entries.models import PM25

    # Define night hours (typically 8 PM to 8 AM)
    night_start = time(20, 0)  # 8 PM
    night_end = time(8, 0)  # 8 AM

    # Query PM2.5 data for the period
    queryset = PM25.objects.filter(
        monitor=monitor,
        timestamp__gte=start_time,
        timestamp__lt=end_time,
        value__isnull=False,
    )

    # Calculate nighttime mean (8 PM to 8 AM)
    night_queryset = queryset.filter(
        Q(timestamp__time__gte=night_start) | Q(timestamp__time__lt=night_end)
    )
    pm25_night_mean = night_queryset.aggregate(avg=Avg('value'))['avg']

    # Calculate daytime mean (8 AM to 8 PM)
    day_queryset = queryset.filter(
        timestamp__time__gte=night_end, timestamp__time__lt=night_start
    )
    pm25_day_mean = day_queryset.aggregate(avg=Avg('value'))['avg']

    # Calculate previous day mean for trend analysis
    previous_day_start = start_time - timedelta(days=1)
    previous_day_end = start_time
    pm25_previous_day = PM25.objects.filter(
        monitor=monitor,
        timestamp__gte=previous_day_start,
        timestamp__lt=previous_day_end,
        value__isnull=False,
    ).aggregate(avg=Avg('value'))['avg']

    return {
        'pm25_night_mean': pm25_night_mean,
        'pm25_day_mean': pm25_day_mean,
        'pm25_previous_day_mean': pm25_previous_day,
    }


def get_pm25_hourly_values(monitor, start_time, end_time):
    """
    Get hourly PM2.5 values for detailed analysis.

    Args:
        monitor: Monitor object or ID
        start_time: Start of period
        end_time: End of period

    Returns:
        List of dictionaries with timestamp and PM2.5 value
    """
    from camp.apps.entries.models import PM25
    from django.db.models.functions import TruncHour

    # Get hourly averages
    hourly_data = (
        PM25.objects.filter(
            monitor=monitor,
            timestamp__gte=start_time,
            timestamp__lt=end_time,
            value__isnull=False,
        )
        .annotate(hour=TruncHour('timestamp'))
        .values('hour')
        .annotate(avg_pm25=Avg('value'))
        .order_by('hour')
    )

    return [
        {'timestamp': item['hour'], 'pm25': item['avg_pm25']} for item in hourly_data
    ]


def analyze_pm25_persistence(monitor, start_time, end_time, threshold=PM25_THRESHOLD):
    """
    Analyze PM2.5 persistence patterns during potential inversion period.

    Args:
        monitor: Monitor object or ID
        start_time: Start of analysis period
        end_time: End of analysis period
        threshold: PM2.5 threshold in μg/m³ (default 35.0 for unhealthy for sensitive groups)

    Returns:
        Dictionary with persistence metrics
    """
    from camp.apps.entries.models import PM25

    # Get hourly PM2.5 values
    hourly_values = get_pm25_hourly_values(monitor, start_time, end_time)

    if not hourly_values:
        return {
            'hours_above_threshold': 0,
            'max_consecutive_hours': 0,
            'persistence_ratio': 0.0,
            'mean_value': None,
            'max_value': None,
        }

    # Calculate persistence metrics
    hours_above_threshold = sum(1 for h in hourly_values if h['pm25'] >= threshold)
    total_hours = len(hourly_values)
    persistence_ratio = hours_above_threshold / total_hours if total_hours > 0 else 0.0

    # Calculate max consecutive hours above threshold
    max_consecutive = 0
    current_consecutive = 0
    for h in hourly_values:
        if h['pm25'] >= threshold:
            current_consecutive += 1
            max_consecutive = max(max_consecutive, current_consecutive)
        else:
            current_consecutive = 0

    # Calculate statistics
    pm25_values = [h['pm25'] for h in hourly_values]
    mean_value = sum(pm25_values) / len(pm25_values)
    max_value = max(pm25_values)

    return {
        'hours_above_threshold': hours_above_threshold,
        'max_consecutive_hours': max_consecutive,
        'persistence_ratio': persistence_ratio,
        'mean_value': mean_value,
        'max_value': max_value,
    }


def check_diurnal_pattern(monitor, start_time, end_time):
    """
    Check for abnormal diurnal (day/night) PM2.5 pattern indicating inversion.

    Normal pattern: PM2.5 typically peaks during evening/night and drops during day
    Inversion pattern: PM2.5 remains elevated or increases at night due to trapping

    Args:
        monitor: Monitor object or ID
        start_time: Start of analysis period
        end_time: End of analysis period

    Returns:
        Dictionary with diurnal pattern analysis
    """
    from camp.apps.entries.models import PM25

    night_start = time(20, 0)  # 8 PM
    night_end = time(8, 0)  # 8 AM

    # Get hourly data
    hourly_values = get_pm25_hourly_values(monitor, start_time, end_time)

    if not hourly_values:
        return {'pattern_detected': False, 'confidence': 0.0}

    # Separate into night and day values
    night_values = []
    day_values = []

    for h in hourly_values:
        hour_of_day = h['timestamp'].time()
        if hour_of_day >= night_start or hour_of_day < night_end:
            night_values.append(h['pm25'])
        else:
            day_values.append(h['pm25'])

    if not night_values or not day_values:
        return {'pattern_detected': False, 'confidence': 0.0}

    night_mean = sum(night_values) / len(night_values)
    day_mean = sum(day_values) / len(day_values)
    ratio = night_mean / day_mean if day_mean > 0 else 0

    # Inversion pattern: night PM2.5 significantly higher than day
    # Ratio > 1.2 suggests abnormal trapping
    pattern_detected = ratio >= 1.2

    # Calculate confidence based on consistency
    night_std = (
        sum((x - night_mean) ** 2 for x in night_values) / len(night_values)
    ) ** 0.5
    day_std = (sum((x - day_mean) ** 2 for x in day_values) / len(day_values)) ** 0.5

    # Lower variability = higher confidence
    variability = (night_std + day_std) / (night_mean + day_mean)
    confidence = min(1.0, max(0.0, 1.0 - variability))

    return {
        'pattern_detected': pattern_detected,
        'night_mean': night_mean,
        'day_mean': day_mean,
        'night_day_ratio': ratio,
        'confidence': confidence,
    }


def detect_and_confirm_inversion(
    latitude,
    longitude,
    monitor=None,
    start_time=None,
    end_time=None,
    min_inversion_strength_f=MIN_INVERSION_STRENGTH_F,
    max_boundary_layer_height_m=MAX_BOUNDARY_LAYER_HEIGHT_M,
    max_wind_speed_mph=MAX_WIND_SPEED_MPH,
    pm25_threshold=PM25_THRESHOLD,
    min_persistence_hours=MIN_PERSISTENCE_HOURS_WATCH,
):
    """
    Detect inversion events using OpenMeteo and confirm with PM2.5 data.

    Args:
        latitude: Latitude coordinate
        longitude: Longitude coordinate
        monitor: Monitor object for PM2.5 data (optional but recommended)
        start_time: Start of detection period
        end_time: End of detection period
        min_inversion_strength_f: Minimum temperature gradient for inversion (°F)
        max_boundary_layer_height_m: Maximum boundary layer height (meters)
        max_wind_speed_mph: Maximum wind speed for stagnant conditions (mph)
        pm25_threshold: PM2.5 threshold for unhealthy levels (μg/m³)
        min_persistence_hours: Minimum hours for inversion watch

    Returns:
        List of detected and confirmed Inversion objects
    """
    if start_time is None:
        start_time = timezone.now() - timedelta(hours=24)
    if end_time is None:
        end_time = timezone.now()

    # Fetch meteorological data from OpenMeteo
    met_data = fetch_openmeteo_data(latitude, longitude, start_time, end_time)

    # Detect inversions from meteorological conditions
    inversions = []
    consecutive_hours = 0
    current_inversion = None
    inversion_start_time = None

    for hour_data in met_data:
        # Check inversion conditions
        is_inversion = (
            hour_data['temp_gradient'] >= min_inversion_strength_f
            and hour_data.get('boundary_layer_height', 0) <= max_boundary_layer_height_m
            and hour_data['wind_speed'] <= max_wind_speed_mph
        )

        if is_inversion:
            consecutive_hours += 1

            if current_inversion is None:
                # Start new inversion event
                inversion_start_time = hour_data['timestamp']
                current_inversion = create_inversion_from_met_data(
                    hour_data, latitude, longitude
                )
        else:
            if (
                current_inversion is not None
                and consecutive_hours >= min_persistence_hours
            ):
                # End current inversion
                current_inversion.persistence_hours = consecutive_hours
                inversion_end_time = hour_data['timestamp']

                # Update period
                from psycopg2.extras import DateTimeTZRange

                current_inversion.period = DateTimeTZRange(
                    inversion_start_time, inversion_end_time
                )

                # Get PM2.5 metrics if monitor is provided
                if monitor:
                    pm25_metrics = get_pm25_metrics(
                        monitor, inversion_start_time, inversion_end_time
                    )
                    current_inversion.pm25_night_mean = pm25_metrics['pm25_night_mean']
                    current_inversion.pm25_day_mean = pm25_metrics['pm25_day_mean']
                    current_inversion.pm25_previous_day_mean = pm25_metrics[
                        'pm25_previous_day_mean'
                    ]

                    # Analyze persistence
                    persistence_data = analyze_pm25_persistence(
                        monitor,
                        inversion_start_time,
                        inversion_end_time,
                        threshold=pm25_threshold,
                    )

                    # Check diurnal pattern
                    diurnal_data = check_diurnal_pattern(
                        monitor, inversion_start_time, inversion_end_time
                    )

                    # Confirm with PM2.5 data
                    current_inversion.confirm_with_pm25()

                    # Adjust confidence based on PM2.5 analysis
                    if current_inversion.pm25_confirmed:
                        current_inversion.confidence = min(
                            1.0, current_inversion.confidence * 1.2
                        )

                    # Add persistence info to notes
                    current_inversion.notes = (
                        f'PM2.5 persistence: {persistence_data["max_consecutive_hours"]} hours above {pm25_threshold} μg/m³\n'
                        f'Diurnal pattern: {"Detected" if diurnal_data["pattern_detected"] else "Not detected"} '
                        f'(ratio: {diurnal_data.get("night_day_ratio", 0):.2f})'
                    )

                # Update severity classification
                current_inversion.update_severity()

                inversions.append(current_inversion)

            current_inversion = None
            consecutive_hours = 0
            inversion_start_time = None

    return inversions


def fetch_openmeteo_data(latitude, longitude, start_time, end_time):
    """
    Fetch meteorological data from OpenMeteo API in imperial units.

    Returns list of hourly data dictionaries with temperatures in Fahrenheit.
    """
    url = 'https://api.open-meteo.com/v1/forecast'

    params = {
        'latitude': latitude,
        'longitude': longitude,
        'hourly': [
            'temperature_2m',
            'temperature_80m',
            'surface_pressure',
            'cloudcover',
            'windspeed_10m',
            'shortwave_radiation',
            'boundary_layer_height',
        ],
        'temperature_unit': 'fahrenheit',
        'windspeed_unit': 'mph',
        'precipitation_unit': 'inch',
        'timezone': 'auto',
        'start_date': start_time.strftime('%Y-%m-%d'),
        'end_date': end_time.strftime('%Y-%m-%d'),
    }

    response = requests.get(url, params=params)
    response.raise_for_status()
    data = response.json()

    hourly_data = []
    hourly = data.get('hourly', {})

    for i in range(len(hourly.get('time', []))):
        temp_2m = hourly['temperature_2m'][i]
        temp_80m = hourly.get('temperature_80m', [None] * len(hourly['time']))[i]

        if temp_2m is not None and temp_80m is not None:
            hourly_data.append(
                {
                    'timestamp': datetime.fromisoformat(hourly['time'][i]),
                    'temp_surface': temp_2m,
                    'temp_aloft': temp_80m,
                    'temp_gradient': temp_80m - temp_2m,
                    'pressure': hourly.get(
                        'surface_pressure', [1013] * len(hourly['time'])
                    )[i],
                    'cloud_cover': hourly.get('cloudcover', [0] * len(hourly['time']))[
                        i
                    ],
                    'wind_speed': hourly.get(
                        'windspeed_10m', [0] * len(hourly['time'])
                    )[i],
                    'solar_radiation': hourly.get(
                        'shortwave_radiation', [0] * len(hourly['time'])
                    )[i],
                    'boundary_layer_height': hourly.get(
                        'boundary_layer_height', [None] * len(hourly['time'])
                    )[i],
                }
            )

    return hourly_data


def create_inversion_from_met_data(hour_data, latitude, longitude):
    """
    Create an Inversion object from meteorological data.
    """
    from django.contrib.gis.geos import Point

    inversion_type = classify_inversion_type(hour_data)

    # This creates an unsaved instance - you'll need to save it in your workflow
    return Inversion(
        location=Point(longitude, latitude),
        inversion_type=inversion_type,
        temperature_gradient=hour_data['temp_gradient'],
        surface_temperature=hour_data['temp_surface'],
        upper_air_temperature=hour_data['temp_aloft'],
        wind_speed=hour_data['wind_speed'],
        pressure=hour_data['pressure'],
        boundary_layer_height=hour_data.get('boundary_layer_height'),
        strength=abs(hour_data['temp_gradient']),
        period=(hour_data['timestamp'], hour_data['timestamp'] + timedelta(hours=1)),
    )


def classify_inversion_type(hour_data):
    """
    Classify inversion type based on meteorological conditions.
    """
    cloud_cover = hour_data.get('cloud_cover', 0)
    wind_speed = hour_data.get('wind_speed', 0)
    pressure = hour_data.get('pressure', 1013)
    solar_rad = hour_data.get('solar_radiation', 0)

    if cloud_cover < 30 and wind_speed < MAX_WIND_SPEED_MPH and solar_rad < 50:
        return InversionType.RADIATION
    elif pressure > 1020:
        return InversionType.SUBSIDENCE
    else:
        return InversionType.FRONTAL
