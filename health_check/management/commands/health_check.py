import sys

from django.core.management.base import BaseCommand
from django.http import Http404

from health_check.mixins import CheckMixin


class Command(BaseCommand):
    help = "Run health checks and exit 0 if everything went well."

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._checker = CheckMixin()

    def add_arguments(self, parser):
        parser.add_argument("-s", "--subset", type=str, nargs=1)

    def handle(self, *args, **options):
        subset = options.get("subset", [])
        subset = subset[0] if subset else None
        try:
            errors = self._checker.run_check(subset=subset)
        except Http404 as e:
            self.stdout.write(str(e))
            sys.exit(1)

        for plugin_identifier, plugin in self._checker.filter_plugins(subset=subset).items():
            style_func = self.style.SUCCESS if not plugin.errors else self.style.ERROR
            self.stdout.write(f"{plugin_identifier:<24} ... {style_func(plugin.pretty_status())}\n")

        if errors:
            sys.exit(1)
