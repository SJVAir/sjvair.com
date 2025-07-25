{% load sjvair %}
Your data export is ready for download:

* **Monitor**: [{{ monitor.name }}]({{ monitor.get_absolute_url|urlify }}) ({{ monitor.get_device }})
* **Date Range**: {{ start_date }} - {{ end_date }}
* **Download**: [{{ url }}]({{ url }})

Thanks!

--The [SJVAir.com](https://www.sjvair.com/) team
