import sys

from django.core.management.base import BaseCommand
from django.http import Http404

from health_check.mixins import CheckMixin


class Command(BaseCommand):
    help = "Run health checks for a configured HEALTH_CHECK['SUBSETS'] entry and exit 0 on success."

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._checker = CheckMixin()

    def add_arguments(self, parser):
        parser.add_argument(
            "-s",
            "--subset",
            type=str,
            required=True,
            help="Name of a subset declared under HEALTH_CHECK['SUBSETS'].",
        )

    def handle(self, *args, **options):
        subset = options["subset"]
        try:
            errors = self._checker.run_check(subset=subset)
            plugins = self._checker.filter_plugins(subset=subset)
        except Http404 as e:
            self.stdout.write(str(e))
            sys.exit(1)

        for plugin_identifier, plugin in plugins.items():
            style_func = self.style.SUCCESS if not plugin.errors else self.style.ERROR
            self.stdout.write(f"{plugin_identifier:<24} ... {style_func(plugin.pretty_status())}\n")

        if errors:
            sys.exit(1)
