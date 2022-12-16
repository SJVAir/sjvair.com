{% load sjvair %}
Monitor Inactivity Alert!
=========================

{% for monitor_type, monitor_list in inactive_monitors.items %}
## {{ monitor_type }} ({{ monitor_list|length }} newly inactive)

{% for monitor in monitor_list %}
**{{ monitor.name }}** in {{ monitor.county }} County \
Last updated: {{ monitor.latest.timestamp }} ({{ monitor.latest.timestamp|timesince }} ago) \
{{ monitor.get_absolute_url|urlify }}
{% endfor %}
{% if not forloop.last %}-----{% endif %}
{% endfor %}
