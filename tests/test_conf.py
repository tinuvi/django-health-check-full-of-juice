from django.test import SimpleTestCase

from health_check.conf import _DEFAULTS, get_setting


class TestGetSetting(SimpleTestCase):
    def test_returns_default_when_health_check_setting_absent(self):
        with self.settings():
            for key, expected in _DEFAULTS.items():
                with self.subTest(key=key):
                    self.assertEqual(get_setting(key), expected)

    def test_returns_default_when_key_missing_from_health_check_setting(self):
        with self.settings(HEALTH_CHECK={}):
            self.assertIs(get_setting("WARNINGS_AS_ERRORS"), True)
            self.assertEqual(get_setting("DISK_USAGE_MAX"), 90)

    def test_override_propagates_through_self_settings(self):
        self.assertIs(get_setting("WARNINGS_AS_ERRORS"), True)
        with self.settings(HEALTH_CHECK={"WARNINGS_AS_ERRORS": False}):
            self.assertIs(get_setting("WARNINGS_AS_ERRORS"), False)
        self.assertIs(get_setting("WARNINGS_AS_ERRORS"), True)

    def test_unknown_key_returns_none_when_no_default_supplied(self):
        with self.settings(HEALTH_CHECK={}):
            self.assertIsNone(get_setting("NOT_A_REAL_HEALTH_CHECK_SETTING"))

    def test_unknown_key_returns_supplied_default_value(self):
        with self.settings(HEALTH_CHECK={}):
            self.assertEqual(
                get_setting("NOT_A_REAL_HEALTH_CHECK_SETTING", default_value="fallback"),
                "fallback",
            )

    def test_defaults_dict_wins_over_supplied_default_value(self):
        with self.settings(HEALTH_CHECK={}):
            self.assertIs(
                get_setting("WARNINGS_AS_ERRORS", default_value="contrib-default"),
                True,
            )

    def test_health_check_setting_wins_over_supplied_default_value(self):
        with self.settings(HEALTH_CHECK={"NEW_CONTRIB_KEY": "from-settings"}):
            self.assertEqual(
                get_setting("NEW_CONTRIB_KEY", default_value="contrib-default"),
                "from-settings",
            )
