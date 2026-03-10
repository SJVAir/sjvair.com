from typing import Optional
from django.contrib.gis.db import models
from django.contrib.postgres.fields import DateTimeRangeField
from django.db.models import Avg, F, Q
from django.utils import timezone
from datetime import datetime, timedelta, time
import requests


# Constants for inversion detection
MAX_BOUNDARY_LAYER_HEIGHT_M = 400  # Maximum boundary layer height in meters
MAX_WIND_SPEED_MPH = 4.5  # Maximum wind speed in mph (≈2.0 m/s)
MIN_DAY_OVER_DAY_INCREASE = 1.1  # Minimum day-over-day PM2.5 increase ratio
MIN_NIGHT_DAY_RATIO = 1.2  # Minimum night/day PM2.5 ratio for confirmation
MIN_INVERSION_STRENGTH_F = 2.7  # Minimum temperature gradient in °F (≈1.5°C)
MIN_PERSISTENCE_HOURS_WATCH = 6  # Minimum hours for inversion watch
MIN_PERSISTENCE_HOURS_ADVISORY = 12  # Minimum hours for inversion advisory
MIN_PERSISTENCE_HOURS_PERSISTENT = 48  # Minimum hours for persistent inversion event
PM25_THRESHOLD = 35.0  # PM2.5 threshold in μg/m³ (standard unit)

# Time definitions
NIGHT_START = time(20, 0)  # 8 PM
NIGHT_END = time(8, 0)  # 8 AM

# Note: OpenMeteo API supports these imperial units natively:
# - temperature_unit: 'fahrenheit'
# - windspeed_unit: 'mph'
# - precipitation_unit: 'inch'
# OpenMeteo does NOT provide imperial units for:
# - pressure (only hPa)
# - boundary_layer_height (only meters)
# - solar_radiation (only W/m²)


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
    Uses imperial units where OpenMeteo provides them natively (temperature, wind speed).
    Uses metric units where OpenMeteo only provides metric (pressure, boundary layer height).
    Analyzed at the county level.
    """

    location = models.PointField(
        help_text='Representative point for the county (e.g., county centroid)'
    )
    county = models.CharField(
        max_length=255, help_text='County name where the inversion event was detected'
    )
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

    # Meteorological data - imperial units where OpenMeteo provides them
    temperature_gradient = models.FloatField(
        help_text='Temperature difference between surface and upper air (°F)'
    )
    surface_temperature = models.FloatField(
        help_text='Surface temperature (°F) - from OpenMeteo'
    )
    upper_air_temperature = models.FloatField(
        help_text='Upper air temperature (°F) - from OpenMeteo'
    )
    wind_speed = models.FloatField(help_text='Wind speed (mph) - from OpenMeteo')

    # Meteorological data - metric units (OpenMeteo native)
    pressure = models.FloatField(
        help_text='Atmospheric pressure (hPa) - OpenMeteo native unit'
    )
    boundary_layer_height = models.FloatField(
        null=True,
        blank=True,
        help_text='Planetary boundary layer height (meters) - OpenMeteo native unit',
    )

    # Inversion characteristics
    strength = models.FloatField(
        help_text='Strength of inversion - temperature gradient magnitude (°F)'
    )
    confidence = models.FloatField(
        default=0.0, help_text='Confidence level of detection (0-1)'
    )

    # PM2.5 confirmation metrics (μg/m³ - standard international unit)
    # Aggregated from all monitors in the county
    pm25_confirmed = models.BooleanField(
        default=False,
        help_text='Whether pollution trapping was confirmed by PM2.5 behavior',
    )
    pm25_night_mean = models.FloatField(
        null=True,
        blank=True,
        help_text='County-wide mean PM2.5 during nighttime hours (μg/m³)',
    )
    pm25_day_mean = models.FloatField(
        null=True,
        blank=True,
        help_text='County-wide mean PM2.5 during daytime hours (μg/m³)',
    )
    pm25_previous_day_mean = models.FloatField(
        null=True,
        blank=True,
        help_text='County-wide mean PM2.5 from previous day (μg/m³)',
    )
    pm25_night_day_ratio = models.FloatField(
        null=True,
        blank=True,
        help_text='Ratio of nighttime to daytime PM2.5 (county-wide)',
    )
    monitor_count = models.IntegerField(
        default=0, help_text='Number of monitors used for PM2.5 aggregation'
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
            models.Index(fields=['county', '-detected_at']),
            models.Index(fields=['inversion_type', '-detected_at']),
            models.Index(fields=['is_active', '-detected_at']),
            models.Index(fields=['pm25_confirmed', '-detected_at']),
            models.Index(fields=['severity', '-detected_at']),
        ]
        unique_together = [['county', 'period']]

    def __str__(self):
        return (
            f'{self.get_inversion_type_display()} in {self.county} ({self.detected_at})'
        )

    @property
    def duration(self):
        """Calculate duration of the inversion event."""
        if self.period:
            return self.period.upper - self.period.lower
        return timedelta(hours=self.persistence_hours)

    def confirm_with_pm25(
        self,
        min_night_day_ratio: float = MIN_NIGHT_DAY_RATIO,
        min_day_over_day_increase: float = MIN_DAY_OVER_DAY_INCREASE,
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
        if self.persistence_hours >= 48 and self.pm25_confirmed:
            self.severity = InversionSeverity.PERSISTENT
        elif self.persistence_hours >= 12:
            self.severity = InversionSeverity.ADVISORY
        elif self.persistence_hours >= 6:
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
    cloud_cover = models.FloatField(
        help_text='Cloud cover percentage (0-100) - OpenMeteo native unit'
    )
    solar_radiation = models.FloatField(
        help_text='Solar radiation (W/m²) - OpenMeteo native unit'
    )
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
        null=True,
        blank=True,
        help_text='Rate of air descent (hPa/hour) - OpenMeteo native unit',
    )
    inversion_height = models.FloatField(
        help_text='Height of inversion layer (meters) - OpenMeteo native unit'
    )
    layer_thickness = models.FloatField(
        null=True,
        blank=True,
        help_text='Thickness of inversion layer (meters) - OpenMeteo native unit',
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
        null=True,
        blank=True,
        help_text='Speed of front movement (mph) - OpenMeteo native unit when available',
    )
    warm_air_temperature = models.FloatField(
        help_text='Warm air mass temperature (°F) - from OpenMeteo'
    )
    cold_air_temperature = models.FloatField(
        help_text='Cold air mass temperature (°F) - from OpenMeteo'
    )

    class Meta:
        ordering = ['-inversion__detected_at']

    def __str__(self):
        return f'Frontal Inversion ({self.get_front_type_display()}): {self.inversion}'


def get_county_pm25_metrics(county_name, start_time, end_time):
    """
    Calculate county-wide PM2.5 metrics for inversion confirmation.
    Aggregates data from all active monitors in the county.
    PM2.5 values remain in μg/m³ (standard international unit).

    Args:
        county_name: County name as string (from Monitor.county field)
        start_time: Start of analysis period
        end_time: End of analysis period

    Returns:
        Dictionary with county-wide PM2.5 metrics in μg/m³
    """
    from camp.apps.entries.models import PM25
    from camp.apps.monitors.models import Monitor

    # Get all active monitors in the county
    monitors = Monitor.objects.filter(county=county_name, is_active=True)

    if not monitors.exists():
        return {
            'pm25_night_mean': None,
            'pm25_day_mean': None,
            'pm25_previous_day_mean': None,
            'monitor_count': 0,
        }

    # Query PM2.5 data for all monitors in the county
    queryset = PM25.objects.filter(
        monitor__in=monitors,
        timestamp__gte=start_time,
        timestamp__lt=end_time,
        value__isnull=False,
    )

    # Calculate nighttime mean (8 PM to 8 AM) - county-wide average
    night_queryset = queryset.filter(
        Q(timestamp__time__gte=NIGHT_START) | Q(timestamp__time__lt=NIGHT_END)
    )
    pm25_night_mean = night_queryset.aggregate(avg=Avg('value'))['avg']

    # Calculate daytime mean (8 AM to 8 PM) - county-wide average
    day_queryset = queryset.filter(
        timestamp__time__gte=NIGHT_END, timestamp__time__lt=NIGHT_START
    )
    pm25_day_mean = day_queryset.aggregate(avg=Avg('value'))['avg']

    # Calculate previous day mean for trend analysis - county-wide average
    previous_day_start = start_time - timedelta(days=1)
    previous_day_end = start_time
    pm25_previous_day = PM25.objects.filter(
        monitor__in=monitors,
        timestamp__gte=previous_day_start,
        timestamp__lt=previous_day_end,
        value__isnull=False,
    ).aggregate(avg=Avg('value'))['avg']

    return {
        'pm25_night_mean': pm25_night_mean,
        'pm25_day_mean': pm25_day_mean,
        'pm25_previous_day_mean': pm25_previous_day,
        'monitor_count': monitors.count(),
    }


def get_county_pm25_hourly_values(county_name, start_time, end_time):
    """
    Get county-wide hourly PM2.5 values for detailed analysis.
    Averages data from all active monitors in the county.

    Args:
        county_name: County name as string (from Monitor.county field)
        start_time: Start of period
        end_time: End of period

    Returns:
        List of dictionaries with timestamp and county-wide average PM2.5 value
    """
    from camp.apps.entries.models import PM25
    from camp.apps.monitors.models import Monitor
    from django.db.models.functions import TruncHour

    # Get all active monitors in the county
    monitors = Monitor.objects.filter(county=county_name, is_active=True)

    if not monitors.exists():
        return []

    # Get hourly averages across all monitors in the county
    hourly_data = (
        PM25.objects.filter(
            monitor__in=monitors,
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


def analyze_county_pm25_persistence(
    county_name, start_time, end_time, threshold=PM25_THRESHOLD
):
    """
    Analyze county-wide PM2.5 persistence patterns during potential inversion period.
    Uses aggregated data from all monitors in the county.

    Args:
        county_name: County name as string (from Monitor.county field)
        start_time: Start of analysis period
        end_time: End of analysis period
        threshold: PM2.5 threshold in μg/m³

    Returns:
        Dictionary with persistence metrics
    """
    # Get county-wide hourly PM2.5 values
    hourly_values = get_county_pm25_hourly_values(county_name, start_time, end_time)

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


def check_county_diurnal_pattern(county_name, start_time, end_time):
    """
    Check for abnormal diurnal (day/night) PM2.5 pattern indicating inversion.
    Uses county-wide aggregated data.

    Normal pattern: PM2.5 typically peaks during evening/night and drops during day
    Inversion pattern: PM2.5 remains elevated or increases at night due to trapping

    Args:
        county_name: County name as string (from Monitor.county field)
        start_time: Start of analysis period
        end_time: End of analysis period

    Returns:
        Dictionary with diurnal pattern analysis
    """
    # Get county-wide hourly data
    hourly_values = get_county_pm25_hourly_values(county_name, start_time, end_time)

    if not hourly_values:
        return {'pattern_detected': False, 'confidence': 0.0}

    # Separate into night and day values
    night_values = []
    day_values = []

    for h in hourly_values:
        hour_of_day = h['timestamp'].time()
        if hour_of_day >= NIGHT_START or hour_of_day < NIGHT_END:
            night_values.append(h['pm25'])
        else:
            day_values.append(h['pm25'])

    if not night_values or not day_values:
        return {'pattern_detected': False, 'confidence': 0.0}

    night_mean = sum(night_values) / len(night_values)
    day_mean = sum(day_values) / len(day_values)
    ratio = night_mean / day_mean if day_mean > 0 else 0

    # Inversion pattern: night PM2.5 significantly higher than day
    pattern_detected = ratio >= MIN_NIGHT_DAY_RATIO

    # Calculate confidence based on consistency
    night_std = (
        sum((x - night_mean) ** 2 for x in night_values) / len(night_values)
    ) ** 0.5
    day_std = (sum((x - day_mean) ** 2 for x in day_values) / len(day_values)) ** 0.5

    # Lower variability = higher confidence
    variability = (
        (night_std + day_std) / (night_mean + day_mean)
        if (night_mean + day_mean) > 0
        else 1.0
    )
    confidence = min(1.0, max(0.0, 1.0 - variability))

    return {
        'pattern_detected': pattern_detected,
        'night_mean': night_mean,
        'day_mean': day_mean,
        'night_day_ratio': ratio,
        'confidence': confidence,
    }


def get_county_centroid(county_name):
    """
    Calculate the centroid location for a county based on all active monitors.

    Args:
        county_name: County name as string (from Monitor.county field)

    Returns:
        Tuple of (latitude, longitude) or None if no monitors found
    """
    from camp.apps.monitors.models import Monitor
    from django.db.models import Avg

    # Get average location of all active monitors in the county
    location_avg = Monitor.objects.filter(
        county=county_name, is_active=True, location__isnull=False
    ).aggregate(avg_lat=Avg('location__y'), avg_lon=Avg('location__x'))

    if location_avg['avg_lat'] and location_avg['avg_lon']:
        return (location_avg['avg_lat'], location_avg['avg_lon'])

    return None


def detect_inversions_by_county(
    county_name=None,
    start_time=None,
    end_time=None,
    min_inversion_strength_f=MIN_INVERSION_STRENGTH_F,
    max_boundary_layer_height_m=MAX_BOUNDARY_LAYER_HEIGHT_M,
    max_wind_speed_mph=MAX_WIND_SPEED_MPH,
    pm25_threshold=PM25_THRESHOLD,
    min_persistence_hours=MIN_PERSISTENCE_HOURS_WATCH,
):
    """
    Detect inversion events county by county using OpenMeteo and confirm with
    county-wide aggregated PM2.5 data.

    Args:
        county_name: Specific county name as string (None = all counties with monitors)
        start_time: Start of detection period
        end_time: End of detection period
        min_inversion_strength_f: Minimum temperature gradient for inversion (°F)
        max_boundary_layer_height_m: Maximum boundary layer height (meters)
        max_wind_speed_mph: Maximum wind speed for stagnant conditions (mph)
        pm25_threshold: PM2.5 threshold for unhealthy levels (μg/m³)
        min_persistence_hours: Minimum hours for inversion watch

    Returns:
        List of detected and confirmed Inversion objects by county
    """
    from camp.apps.monitors.models import Monitor

    if start_time is None:
        start_time = timezone.now() - timedelta(hours=24)
    if end_time is None:
        end_time = timezone.now()

    # Get counties to analyze
    if county_name:
        counties = [county_name]
    else:
        # Get all unique counties that have active monitors
        counties = (
            Monitor.objects.filter(is_active=True, county__isnull=False)
            .values_list('county', flat=True)
            .distinct()
        )

    all_inversions = []

    for county in counties:
        # Get county centroid based on monitor locations
        centroid = get_county_centroid(county)

        if not centroid:
            continue

        latitude, longitude = centroid

        # Detect inversions for this county
        county_inversions = detect_and_confirm_county_inversion(
            county,
            latitude,
            longitude,
            start_time,
            end_time,
            min_inversion_strength_f,
            max_boundary_layer_height_m,
            max_wind_speed_mph,
            pm25_threshold,
            min_persistence_hours,
        )

        all_inversions.extend(county_inversions)

    return all_inversions


def detect_and_confirm_county_inversion(
    county_name,
    latitude,
    longitude,
    start_time,
    end_time,
    min_inversion_strength_f=MIN_INVERSION_STRENGTH_F,
    max_boundary_layer_height_m=MAX_BOUNDARY_LAYER_HEIGHT_M,
    max_wind_speed_mph=MAX_WIND_SPEED_MPH,
    pm25_threshold=PM25_THRESHOLD,
    min_persistence_hours=MIN_PERSISTENCE_HOURS_WATCH,
):
    """
    Detect inversion events for a specific county using OpenMeteo and confirm
    with county-wide PM2.5 data.

    Uses units as provided by OpenMeteo:
    - Temperatures: °F (OpenMeteo imperial)
    - Wind speed: mph (OpenMeteo imperial)
    - Pressure: hPa (OpenMeteo native/metric)
    - Boundary layer height: meters (OpenMeteo native/metric)

    Args:
        county_name: County name as string (from Monitor.county field)
        latitude: Latitude coordinate (typically county centroid)
        longitude: Longitude coordinate (typically county centroid)
        start_time: Start of detection period
        end_time: End of detection period
        min_inversion_strength_f: Minimum temperature gradient (°F)
        max_boundary_layer_height_m: Maximum boundary layer height (meters)
        max_wind_speed_mph: Maximum wind speed (mph)
        pm25_threshold: PM2.5 threshold (μg/m³)
        min_persistence_hours: Minimum hours for detection

    Returns:
        List of detected Inversion objects for the county
    """
    # Fetch meteorological data from OpenMeteo
    met_data = fetch_openmeteo_data(latitude, longitude, start_time, end_time)

    if not met_data:
        return []

    # Detect inversions from meteorological conditions
    inversions = []
    consecutive_hours = 0
    current_inversion = None
    inversion_start_time = None

    for hour_data in met_data:
        # Check inversion conditions using appropriate units
        blh = hour_data.get('boundary_layer_height')
        is_inversion = (
            hour_data['temp_gradient'] >= min_inversion_strength_f  # °F
            and (blh is None or blh <= max_boundary_layer_height_m)  # meters
            and hour_data['wind_speed'] <= max_wind_speed_mph  # mph
        )

        if is_inversion:
            consecutive_hours += 1

            if current_inversion is None:
                # Start new inversion event
                inversion_start_time = hour_data['timestamp']
                current_inversion = create_county_inversion_from_met_data(
                    hour_data, county_name, latitude, longitude
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

                # Get county-wide PM2.5 metrics
                pm25_metrics = get_county_pm25_metrics(
                    county_name, inversion_start_time, inversion_end_time
                )
                current_inversion.pm25_night_mean = pm25_metrics['pm25_night_mean']
                current_inversion.pm25_day_mean = pm25_metrics['pm25_day_mean']
                current_inversion.pm25_previous_day_mean = pm25_metrics[
                    'pm25_previous_day_mean'
                ]
                current_inversion.monitor_count = pm25_metrics['monitor_count']

                # Analyze county-wide persistence
                persistence_data = analyze_county_pm25_persistence(
                    county_name,
                    inversion_start_time,
                    inversion_end_time,
                    threshold=pm25_threshold,
                )

                # Check county-wide diurnal pattern
                diurnal_data = check_county_diurnal_pattern(
                    county_name, inversion_start_time, inversion_end_time
                )

                # Confirm with PM2.5 data
                current_inversion.confirm_with_pm25()

                # Adjust confidence based on PM2.5 analysis
                if (
                    current_inversion.pm25_confirmed
                    and current_inversion.monitor_count > 0
                ):
                    # Higher confidence with more monitors
                    monitor_factor = min(
                        1.2, 1.0 + (current_inversion.monitor_count * 0.02)
                    )
                    current_inversion.confidence = min(
                        1.0, current_inversion.confidence * monitor_factor
                    )

                # Add persistence info to notes
                current_inversion.notes = (
                    f'County: {county_name}\n'
                    f'Monitors used: {current_inversion.monitor_count}\n'
                    f'PM2.5 persistence: {persistence_data["max_consecutive_hours"]} hours above {pm25_threshold} μg/m³\n'
                    f'Mean PM2.5: {persistence_data["mean_value"]:.1f} μg/m³\n'
                    f'Max PM2.5: {persistence_data["max_value"]:.1f} μg/m³\n'
                    f'Diurnal pattern: {"Detected" if diurnal_data["pattern_detected"] else "Not detected"} '
                    f'(night/day ratio: {diurnal_data.get("night_day_ratio", 0):.2f})'
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
    Fetch meteorological data from OpenMeteo API.
    Request imperial units where OpenMeteo provides them natively.
    Use metric units where OpenMeteo only provides metric.

    Returns list of hourly data dictionaries.
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
        # Request imperial units where OpenMeteo provides them
        'temperature_unit': 'fahrenheit',
        'windspeed_unit': 'mph',
        'precipitation_unit': 'inch',
        # Note: pressure stays in hPa, boundary_layer_height in meters (OpenMeteo native)
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
                    'temp_surface': temp_2m,  # °F from OpenMeteo
                    'temp_aloft': temp_80m,  # °F from OpenMeteo
                    'temp_gradient': temp_80m - temp_2m,  # °F
                    'pressure': hourly.get(
                        'surface_pressure', [1013] * len(hourly['time'])
                    )[i],  # hPa (OpenMeteo native)
                    'cloud_cover': hourly.get('cloudcover', [0] * len(hourly['time']))[
                        i
                    ],  # % (OpenMeteo native)
                    'wind_speed': hourly.get(
                        'windspeed_10m', [0] * len(hourly['time'])
                    )[i],  # mph from OpenMeteo
                    'solar_radiation': hourly.get(
                        'shortwave_radiation', [0] * len(hourly['time'])
                    )[i],  # W/m² (OpenMeteo native)
                    'boundary_layer_height': hourly.get(
                        'boundary_layer_height', [None] * len(hourly['time'])
                    )[i],  # meters (OpenMeteo native)
                }
            )

    return hourly_data


def create_county_inversion_from_met_data(hour_data, county_name, latitude, longitude):
    """
    Create an Inversion object for a county from meteorological data.
    Uses units as provided by OpenMeteo (no conversions).

    Args:
        hour_data: Dictionary with meteorological data
        county_name: County name as string (from Monitor.county field)
        latitude: Latitude coordinate
        longitude: Longitude coordinate

    Returns:
        Unsaved Inversion instance
    """
    from django.contrib.gis.geos import Point

    inversion_type = classify_inversion_type(hour_data)

    # This creates an unsaved instance - you'll need to save it in your workflow
    return Inversion(
        location=Point(longitude, latitude),
        county=county_name,
        inversion_type=inversion_type,
        temperature_gradient=hour_data['temp_gradient'],  # °F
        surface_temperature=hour_data['temp_surface'],  # °F
        upper_air_temperature=hour_data['temp_aloft'],  # °F
        wind_speed=hour_data['wind_speed'],  # mph
        pressure=hour_data['pressure'],  # hPa
        boundary_layer_height=hour_data.get('boundary_layer_height'),  # meters
        strength=abs(hour_data['temp_gradient']),  # °F
        period=(hour_data['timestamp'], hour_data['timestamp'] + timedelta(hours=1)),
    )


def classify_inversion_type(hour_data):
    """
    Classify inversion type based on meteorological conditions.
    Uses units as provided by OpenMeteo.
    """
    cloud_cover = hour_data.get('cloud_cover', 0)  # %
    wind_speed = hour_data.get('wind_speed', 0)  # mph
    pressure = hour_data.get('pressure', 1013)  # hPa
    solar_rad = hour_data.get('solar_radiation', 0)  # W/m²

    # Thresholds using appropriate units
    if cloud_cover < 30 and wind_speed < 4.5 and solar_rad < 50:
        return InversionType.RADIATION
    elif pressure > 1020:  # hPa
        return InversionType.SUBSIDENCE
    else:
        return InversionType.FRONTAL
