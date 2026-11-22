"""잘못된 배포 설정에서는 설치·수집하지 않고, 수집 실패는 빌드를 중단한다."""
import os
import subprocess
import unittest
from unittest.mock import patch

from scripts import build_render


class RenderBuildTest(unittest.TestCase):
    def test_missing_or_invalid_region_codes_prevent_all_build_commands(self):
        for codes in ("", "41135;echo", "1234", "１２３４５"):
            with self.subTest(codes=codes), patch.dict(os.environ, {"DEPLOY_RENT_CODES": codes}), \
                    patch("backend.security.SecuritySettings.load"), patch.object(build_render.subprocess, "run") as run:
                with self.assertRaises(RuntimeError):
                    build_render.main()
                run.assert_not_called()

    def test_missing_public_data_key_prevents_install_and_collection(self):
        with patch.dict(os.environ, {"DEPLOY_RENT_CODES": "41135"}), patch("backend.security.SecuritySettings.load"), \
                patch("config.get_data_go_kr_key", return_value=None), patch.object(build_render.subprocess, "run") as run:
            with self.assertRaises(RuntimeError):
                build_render.main()
            run.assert_not_called()

    def test_partial_collection_failure_cannot_produce_a_successful_deploy(self):
        def command(args, **kwargs):
            if "scripts/prewarm_rent.py" in args:
                raise subprocess.CalledProcessError(1, args)

        with patch.dict(os.environ, {"DEPLOY_RENT_CODES": "41135 11680"}), \
                patch("backend.security.SecuritySettings.load"), patch("config.get_data_go_kr_key", return_value="fake-key"), \
                patch.object(build_render.shutil, "which", return_value="npm"), \
                patch.object(build_render.subprocess, "run", side_effect=command) as run:
            with self.assertRaises(subprocess.CalledProcessError):
                build_render.main()
            args = run.call_args.args[0]
            self.assertEqual(args[-2:], ["41135", "11680"])
            self.assertNotIn("fake-key", str(run.call_args_list))
            self.assertTrue(all(call.kwargs["check"] for call in run.call_args_list))

    def test_missing_auth_prevents_any_build_commands(self):
        with patch("backend.security.SecuritySettings.load", side_effect=RuntimeError("configuration")), \
                patch.object(build_render.subprocess, "run") as run:
            with self.assertRaises(RuntimeError):
                build_render.main()
            run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
