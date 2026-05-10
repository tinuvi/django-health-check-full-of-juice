from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.test import SimpleTestCase

from health_check.backends import BaseHealthCheckBackend
from health_check.management.commands.health_check import Command
from health_check.mixins import CheckMixin
from health_check.plugins import plugin_dir


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


class TestCommand(SimpleTestCase):
    def setUp(self):
        plugin_dir.reset()
        plugin_dir.register(FailPlugin)
        plugin_dir.register(OkPlugin)
        self.addCleanup(plugin_dir.reset)

    def test_command(self):
        stdout = StringIO()
        with self.assertRaises(SystemExit):
            call_command("health_check", stdout=stdout)
        stdout.seek(0)
        self.assertEqual(
            stdout.read(),
            "FailPlugin               ... unknown error: Oops\nOkPlugin                 ... working\n",
        )

    def test_command_with_subset(self):
        SUBSET_NAME_1 = "subset-1"
        SUBSET_NAME_2 = "subset-2"
        with self.settings(
            HEALTH_CHECK={
                "SUBSETS": {
                    SUBSET_NAME_1: ["OkPlugin"],
                    SUBSET_NAME_2: ["OkPlugin", "FailPlugin"],
                }
            }
        ):
            stdout = StringIO()
            call_command("health_check", f"--subset={SUBSET_NAME_1}", stdout=stdout)
            stdout.seek(0)
            self.assertEqual(stdout.read(), "OkPlugin                 ... working\n")

    def test_command_with_failed_check_subset(self):
        SUBSET_NAME = "subset-2"
        with self.settings(HEALTH_CHECK={"SUBSETS": {SUBSET_NAME: ["OkPlugin", "FailPlugin"]}}):
            stdout = StringIO()
            with self.assertRaises(SystemExit):
                call_command("health_check", f"--subset={SUBSET_NAME}", stdout=stdout)
            stdout.seek(0)
            self.assertEqual(
                stdout.read(),
                "FailPlugin               ... unknown error: Oops\nOkPlugin                 ... working\n",
            )

    def test_command_with_non_existence_subset(self):
        SUBSET_NAME = "subset-2"
        NON_EXISTENCE_SUBSET_NAME = "abcdef12"
        with self.settings(HEALTH_CHECK={"SUBSETS": {SUBSET_NAME: ["OkPlugin"]}}):
            stdout = StringIO()
            with self.assertRaises(SystemExit):
                call_command("health_check", f"--subset={NON_EXISTENCE_SUBSET_NAME}", stdout=stdout)
            stdout.seek(0)
            self.assertEqual(stdout.read(), f"Subset: '{NON_EXISTENCE_SUBSET_NAME}' does not exist.\n")

    def test_command_exits_zero_when_all_plugins_pass(self):
        """When every plugin passes, the command must NOT raise SystemExit (exit 0)."""
        plugin_dir.reset()
        plugin_dir.register(OkPlugin)

        stdout = StringIO()
        try:
            call_command("health_check", stdout=stdout)
        except SystemExit as e:
            self.fail(f"Command unexpectedly exited with SystemExit({e.code}) on a clean run")
        stdout.seek(0)
        self.assertEqual(stdout.read(), "OkPlugin                 ... working\n")

    def test_command_exits_one_when_any_plugin_fails(self):
        """When any critical plugin fails, the command must raise SystemExit(1)."""
        stdout = StringIO()
        with self.assertRaises(SystemExit) as ctx:
            call_command("health_check", stdout=stdout)
        self.assertEqual(ctx.exception.code, 1)


class TestCommandStructuralContract(SimpleTestCase):
    """
    Structural guarantees for the management command after the composition refactor.

    These tests pin down the contract that fixed the pyrefly `inconsistent-inheritance`
    error: `Command` must NOT inherit from `CheckMixin`, but must still expose Django's
    `BaseCommand.check` (Django's system-check entrypoint) intact, while delegating
    health-check work to a composed `CheckMixin` instance.
    """

    def setUp(self):
        plugin_dir.reset()
        plugin_dir.register(FailPlugin)
        plugin_dir.register(OkPlugin)
        self.addCleanup(plugin_dir.reset)

    def test_command_does_not_inherit_check_mixin(self):
        """Composition, not inheritance: CheckMixin must NOT be in Command's MRO."""
        self.assertNotIn(CheckMixin, Command.__mro__)
        self.assertIn(BaseCommand, Command.__mro__)

    def test_command_holds_a_check_mixin_instance(self):
        """Command must compose a CheckMixin instance (not subclass it)."""
        cmd = Command()
        self.assertIsInstance(cmd._checker, CheckMixin)

    def test_command_check_signature_is_django_basecommand(self):
        """
        Command.check must be Django's BaseCommand.check, NOT the health-check method.

        This is the entire point of the refactor: previously CheckMixin.check(subset)
        shadowed BaseCommand.check(app_configs, tags, ...) and broke type-checking
        and Django's system-check protocol.
        """
        import inspect

        sig = inspect.signature(Command.check)
        params = sig.parameters
        # BaseCommand.check has these named params; CheckMixin.check has only "subset".
        self.assertIn("app_configs", params)
        self.assertIn("tags", params)
        self.assertIn("display_num_errors", params)
        self.assertNotIn("subset", params)
        # And it must be the actual function from BaseCommand.
        self.assertIs(Command.check, BaseCommand.check)

    def test_command_django_system_check_runs_without_typeerror(self):
        """
        Django's system-check entrypoint on Command works with BaseCommand's signature.

        Previously CheckMixin.check shadowed it with a different signature, raising TypeError.
        See https://docs.djangoproject.com/en/5.2/topics/testing/overview/ for testing patterns;
        system checks are part of Django's command lifecycle.
        """
        cmd = Command()
        # Should not raise. Returns None on success or raises SystemCheckError.
        cmd.check(
            app_configs=None,
            tags=None,
            display_num_errors=False,
            include_deployment_checks=False,
            fail_level=40,
            databases=None,
        )

    def test_command_handles_run_check_via_composition(self):
        """End-to-end through call_command exercises the composed _checker."""
        stdout = StringIO()
        with self.assertRaises(SystemExit):
            call_command("health_check", stdout=stdout)
        stdout.seek(0)
        output = stdout.read()
        self.assertIn("FailPlugin", output)
        self.assertIn("OkPlugin", output)

    def test_command_invocations_do_not_share_checker_state(self):
        """Each Command instance must own a fresh CheckMixin (no class-level sharing)."""
        cmd_a = Command()
        cmd_b = Command()
        self.assertIsNot(cmd_a._checker, cmd_b._checker)


class TestCommandSubsetsWithSkipChecks(SimpleTestCase):
    """
    End-to-end coverage for `python manage.py health_check -s <subset> --skip-checks`.

    Models a realistic deployment: a `readiness` subset of crucial dependencies
    that must be up before the app accepts traffic, and an `integrations`
    subset that fans out to every integration (a superset of `readiness`).
    `--skip-checks` is Django's `BaseCommand` flag that bypasses the
    `django.core.checks` system-check phase; it must compose cleanly with
    the library's `--subset` argument.
    """

    SUBSETS = {
        "readiness": ["DatabasePlugin", "CachePlugin"],
        "integrations": ["DatabasePlugin", "CachePlugin", "ThirdPartyAPIPlugin"],
    }

    def setUp(self):
        plugin_dir.reset()
        plugin_dir.register(DatabasePlugin)
        plugin_dir.register(CachePlugin)
        plugin_dir.register(ThirdPartyAPIPlugin)
        self.addCleanup(plugin_dir.reset)

    def test_readiness_subset_with_skip_checks_runs_only_crucial_plugins(self):
        with self.settings(HEALTH_CHECK={"SUBSETS": self.SUBSETS}):
            stdout = StringIO()
            call_command("health_check", "--subset=readiness", "--skip-checks", stdout=stdout)
        output = stdout.getvalue()
        self.assertIn("DatabasePlugin", output)
        self.assertIn("CachePlugin", output)
        self.assertNotIn("ThirdPartyAPIPlugin", output)

    def test_integrations_subset_with_skip_checks_runs_every_registered_plugin(self):
        with self.settings(HEALTH_CHECK={"SUBSETS": self.SUBSETS}):
            stdout = StringIO()
            call_command("health_check", "--subset=integrations", "--skip-checks", stdout=stdout)
        output = stdout.getvalue()
        self.assertIn("DatabasePlugin", output)
        self.assertIn("CachePlugin", output)
        self.assertIn("ThirdPartyAPIPlugin", output)

    def test_skip_checks_does_not_skip_health_check_plugins(self):
        """`--skip-checks` only skips Django's system checks — health-check plugins still run."""
        with self.settings(HEALTH_CHECK={"SUBSETS": self.SUBSETS}):
            stdout = StringIO()
            call_command("health_check", "--subset=readiness", "--skip-checks", stdout=stdout)
        output = stdout.getvalue()
        self.assertIn("working", output)

    def test_e2e_command_with_subset_and_skip_checks_via_argv(self):
        """
        E2E: the literal CLI invocation `python manage.py health_check -s readiness --skip-checks`.

        It parses through Django's argv pipeline, runs only the `readiness`
        subset, and bypasses Django's system-check phase.

        Uses `run_from_argv` (not `call_command`) because `call_command`
        defaults `skip_checks=True` for programmatic invocations, which
        would mask whether `--skip-checks` was actually parsed and honored.
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
        """
        Control: without `--skip-checks` in argv, Django invokes `BaseCommand.check`.

        `BaseCommand.check` is Django's system-check entrypoint.
        """
        with (
            self.settings(HEALTH_CHECK={"SUBSETS": self.SUBSETS}),
            patch.object(Command, "check") as mock_check,
        ):
            Command(stdout=StringIO()).run_from_argv(["manage.py", "health_check", "-s", "readiness"])
        mock_check.assert_called_once()
