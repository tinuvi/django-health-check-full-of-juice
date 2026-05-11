from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.test import SimpleTestCase

from health_check.backends import BaseHealthCheckBackend
from health_check.management.commands.health_check import Command
from health_check.mixins import CheckMixin


class FailPlugin(BaseHealthCheckBackend):
    def check_status(self):
        self.add_error("Oops")


class OkPlugin(BaseHealthCheckBackend):
    def check_status(self):
        pass


class DatabasePlugin(BaseHealthCheckBackend):
    def check_status(self):
        pass


class CachePlugin(BaseHealthCheckBackend):
    def check_status(self):
        pass


class ThirdPartyAPIPlugin(BaseHealthCheckBackend):
    def check_status(self):
        pass


_SUBSETS = {
    "fail-and-ok": [
        "tests.test_commands.FailPlugin",
        "tests.test_commands.OkPlugin",
    ],
    "ok-only": ["tests.test_commands.OkPlugin"],
}


class TestCommand(SimpleTestCase):
    def test_subset_argument_is_required(self):
        with self.assertRaises(CommandError):
            call_command("health_check")

    def test_subset_runs_only_listed_backends(self):
        with self.settings(HEALTH_CHECK={"SUBSETS": _SUBSETS}):
            stdout = StringIO()
            call_command("health_check", "--subset=ok-only", stdout=stdout)
        self.assertEqual(stdout.getvalue(), "OkPlugin                 ... working\n")

    def test_subset_with_failed_check_exits_one(self):
        with self.settings(HEALTH_CHECK={"SUBSETS": _SUBSETS}):
            stdout = StringIO()
            with self.assertRaises(SystemExit) as ctx:
                call_command("health_check", "--subset=fail-and-ok", stdout=stdout)
            self.assertEqual(ctx.exception.code, 1)
        self.assertEqual(
            stdout.getvalue(),
            "FailPlugin               ... unknown error: Oops\nOkPlugin                 ... working\n",
        )

    def test_unknown_subset_writes_error_and_exits(self):
        with self.settings(HEALTH_CHECK={"SUBSETS": _SUBSETS}):
            stdout = StringIO()
            with self.assertRaises(SystemExit):
                call_command("health_check", "--subset=ghost", stdout=stdout)
        self.assertIn("Subset: 'ghost' does not exist.", stdout.getvalue())

    def test_command_exits_zero_when_all_plugins_pass(self):
        with self.settings(HEALTH_CHECK={"SUBSETS": _SUBSETS}):
            stdout = StringIO()
            try:
                call_command("health_check", "--subset=ok-only", stdout=stdout)
            except SystemExit as e:
                self.fail(f"Command unexpectedly exited with SystemExit({e.code}) on a clean run")
        self.assertEqual(stdout.getvalue(), "OkPlugin                 ... working\n")


class TestCommandStructuralContract(SimpleTestCase):
    """
    Structural guarantees for the management command after the composition refactor.

    Pin down the contract that fixed the pyrefly ``inconsistent-inheritance``
    error: ``Command`` must NOT inherit from ``CheckMixin``, but must still
    expose Django's ``BaseCommand.check`` (Django's system-check entrypoint)
    intact, while delegating health-check work to a composed ``CheckMixin``
    instance.
    """

    def test_command_does_not_inherit_check_mixin(self):
        self.assertNotIn(CheckMixin, Command.__mro__)
        self.assertIn(BaseCommand, Command.__mro__)

    def test_command_holds_a_check_mixin_instance(self):
        cmd = Command()
        self.assertIsInstance(cmd._checker, CheckMixin)

    def test_command_check_signature_is_django_basecommand(self):
        import inspect

        sig = inspect.signature(Command.check)
        params = sig.parameters
        self.assertIn("app_configs", params)
        self.assertIn("tags", params)
        self.assertIn("display_num_errors", params)
        self.assertNotIn("subset", params)
        self.assertIs(Command.check, BaseCommand.check)

    def test_command_django_system_check_runs_without_typeerror(self):
        cmd = Command()
        cmd.check(
            app_configs=None,
            tags=None,
            display_num_errors=False,
            include_deployment_checks=False,
            fail_level=40,
            databases=None,
        )

    def test_command_invocations_do_not_share_checker_state(self):
        cmd_a = Command()
        cmd_b = Command()
        self.assertIsNot(cmd_a._checker, cmd_b._checker)


class TestCommandSubsetsWithSkipChecks(SimpleTestCase):
    """End-to-end coverage for ``python manage.py health_check -s <subset> --skip-checks``."""

    SUBSETS = {
        "readiness": [
            "tests.test_commands.DatabasePlugin",
            "tests.test_commands.CachePlugin",
        ],
        "integrations": [
            "tests.test_commands.DatabasePlugin",
            "tests.test_commands.CachePlugin",
            "tests.test_commands.ThirdPartyAPIPlugin",
        ],
    }

    def test_readiness_subset_with_skip_checks_runs_only_crucial_plugins(self):
        with self.settings(HEALTH_CHECK={"SUBSETS": self.SUBSETS}):
            stdout = StringIO()
            call_command("health_check", "--subset=readiness", "--skip-checks", stdout=stdout)
        output = stdout.getvalue()
        self.assertIn("DatabasePlugin", output)
        self.assertIn("CachePlugin", output)
        self.assertNotIn("ThirdPartyAPIPlugin", output)

    def test_integrations_subset_with_skip_checks_runs_every_listed_plugin(self):
        with self.settings(HEALTH_CHECK={"SUBSETS": self.SUBSETS}):
            stdout = StringIO()
            call_command("health_check", "--subset=integrations", "--skip-checks", stdout=stdout)
        output = stdout.getvalue()
        self.assertIn("DatabasePlugin", output)
        self.assertIn("CachePlugin", output)
        self.assertIn("ThirdPartyAPIPlugin", output)

    def test_skip_checks_does_not_skip_health_check_plugins(self):
        with self.settings(HEALTH_CHECK={"SUBSETS": self.SUBSETS}):
            stdout = StringIO()
            call_command("health_check", "--subset=readiness", "--skip-checks", stdout=stdout)
        output = stdout.getvalue()
        self.assertIn("working", output)

    def test_e2e_command_with_subset_and_skip_checks_via_argv(self):
        """
        E2E: the literal CLI invocation ``python manage.py health_check -s readiness --skip-checks``.

        Uses ``run_from_argv`` (not ``call_command``) because ``call_command``
        defaults ``skip_checks=True`` for programmatic invocations, which
        would mask whether ``--skip-checks`` was actually parsed and honored.
        """
        stdout = StringIO()
        with (
            self.settings(HEALTH_CHECK={"SUBSETS": self.SUBSETS}),
            patch.object(Command, "check") as mock_check,
        ):
            Command(stdout=stdout).run_from_argv(["manage.py", "health_check", "-s", "readiness", "--skip-checks"])
        output = stdout.getvalue()
        self.assertIn("DatabasePlugin", output)
        self.assertIn("CachePlugin", output)
        self.assertNotIn("ThirdPartyAPIPlugin", output)
        mock_check.assert_not_called()

    def test_argv_without_skip_checks_djangos_system_check_phase_runs(self):
        with (
            self.settings(HEALTH_CHECK={"SUBSETS": self.SUBSETS}),
            patch.object(Command, "check") as mock_check,
        ):
            Command(stdout=StringIO()).run_from_argv(["manage.py", "health_check", "-s", "readiness"])
        mock_check.assert_called_once()
