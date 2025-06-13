from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import datetime
import pytz

from camp.apps.calibrations.models import CalibrationPair
from camp.apps.calibrations.tasks import train_pair
from camp.apps.calibrations import trainers


class Command(BaseCommand):
    help = 'Train calibration pairs manually.'

    def add_arguments(self, parser):
        parser.add_argument('-e', '--entry-type', action='append', help='Filter by entry type(s)')
        parser.add_argument('-t', '--trainer', action='append', help='Specify trainer(s) to use')
        parser.add_argument('-p', '--pair', action='append', type=int, help='Specify pair ID(s)')
        parser.add_argument('-d', '--date', type=str, help='Date/time for calibration (ISO format)')
        parser.add_argument('--local', action='store_true', help='Run locally instead of queueing')
        parser.add_argument('--dry-run', action='store_true', help='Print actions without executing')

    def handle(self, *args, **options):
        self.options = options
        self.end_time = self.get_target_time()

        training_tasks = self.get_training_tasks()

        if not training_tasks:
            self.stdout.write(self.style.WARNING('No training tasks to run.'))
            return

        if self.options.get('dry_run'):
            self.print_training_tasks(training_tasks)
        else:
            self.execute_training_tasks(training_tasks)

    def get_target_time(self):
        date_option = self.options.get('date')

        if date_option:
            return timezone.make_aware(datetime.fromisoformat(date_option))

        pacific = pytz.timezone('America/Los_Angeles')
        now_pacific = timezone.now().astimezone(pacific)
        midnight_pacific = now_pacific.replace(hour=0, minute=0, second=0, microsecond=0)
        return midnight_pacific.astimezone(timezone.utc)

    def get_training_tasks(self):
        entry_types = self.options.get('entry_type') or []
        trainer_names = self.options.get('trainer') or []
        pair_ids = self.options.get('pair') or []

        pairs = CalibrationPair.objects.filter(is_enabled=True)

        if entry_types:
            pairs = pairs.filter(entry_type__in=entry_types)

        if pair_ids:
            pairs = pairs.filter(pk__in=pair_ids)

        if not pairs.exists():
            return []

        if trainer_names:
            trainer_classes = [trainers[name] for name in trainer_names]
        else:
            trainer_classes = None

        tasks = []
        for pair in pairs:
            applicable = trainer_classes or pair.get_trainers()
            for trainer in applicable:
                tasks.append((pair, trainer))

        return tasks

    def print_training_tasks(self, tasks):
        for pair, trainer in tasks:
            label = f"Pair {pair.pk} | Trainer {trainer.name} | Date {self.end_time.date()}"
            self.stdout.write(self.style.NOTICE(f"[Dry-run] Would train: {label}"))

    def execute_training_tasks(self, tasks):
        local = self.options.get('local')
        task_func = train_pair.call_local if local else train_pair

        for pair, trainer in tasks:
            label = f"Pair {pair.pk} | Trainer {trainer.name} | Date {self.end_time.date()} | {'local' if local else 'queued'}"
            self.stdout.write(self.style.SUCCESS(f"Training: {label}"))
            task_func(pair.pk, trainer.name, end_time=self.end_time)
