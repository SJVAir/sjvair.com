{% load sjvair %}
Backfill Job Failed
====================

**{{ job_label }}** has failed after {{ job.consecutive_failures }} consecutive stalled batches and stopped retrying.

* **State**: {{ job.state }}
* **Cursor**: {{ job.cursor }}
* **Range**: {{ job.range_start }} &ndash; {{ job.range_end }}
* **Last error**: {{ job.last_error }}

This job will not resume on its own. Check `{{ management_command }} status` for details, investigate the cause, and either fix the underlying issue and `{{ management_command }} start --force` a new run, or leave it as-is if no further action is needed.
