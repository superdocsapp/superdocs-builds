import unittest
from unittest import mock

import main


class TestResolveApiKey(unittest.TestCase):
    def tearDown(self):
        main.os.environ.pop("SUPERDOCS_API_KEY", None)

    def test_uses_env_var_without_prompting(self):
        main.os.environ["SUPERDOCS_API_KEY"] = "env-key-123"
        with mock.patch.object(main.sys, "stdin") as fake_stdin:
            fake_stdin.isatty.return_value = True
            with mock.patch("main.getpass.getpass") as fake_getpass:
                fake_getpass.side_effect = AssertionError("must not prompt when env var is set")
                self.assertEqual(main.resolve_api_key(), "env-key-123")
        fake_getpass.assert_not_called()

    def test_prompts_masked_when_env_var_missing(self):
        with mock.patch.object(main.sys, "stdin") as fake_stdin:
            fake_stdin.isatty.return_value = True
            with mock.patch("main.getpass.getpass", return_value="typed-key") as fake_getpass:
                self.assertEqual(main.resolve_api_key(), "typed-key")
        fake_getpass.assert_called_once()
        self.assertEqual(main.os.environ["SUPERDOCS_API_KEY"], "typed-key")

    def test_never_echoes_the_key(self):
        with mock.patch.object(main.sys, "stdin") as fake_stdin:
            fake_stdin.isatty.return_value = True
            with mock.patch("main.getpass.getpass", return_value="typed-key") as fake_getpass:
                with mock.patch.object(main.console, "print") as fake_print:
                    main.resolve_api_key()
        printed = [call.args[0] for call in fake_print.call_args_list]
        joined = " ".join(str(p) for p in printed)
        self.assertNotIn("typed-key", joined)

    def test_exits_when_no_interactive_terminal(self):
        with mock.patch.object(main.sys, "stdin") as fake_stdin:
            fake_stdin.isatty.return_value = False
            with self.assertRaises(SystemExit):
                main.resolve_api_key()

    def test_empty_prompt_is_rejected(self):
        with mock.patch.object(main.sys, "stdin") as fake_stdin:
            fake_stdin.isatty.return_value = True
            with mock.patch("main.getpass.getpass", return_value="   "):
                with self.assertRaises(SystemExit):
                    main.resolve_api_key()


if __name__ == "__main__":
    unittest.main()
