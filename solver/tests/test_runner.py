import json
from pathlib import Path

import windtunnel.runner as runner


def test_main_reports_error_as_json_event(capsys):
    # run-dir 不存在 -> error 事件 + exit 1
    rc = runner.main(["--run-dir", "/nonexistent/run"])
    assert rc == 1
    line = capsys.readouterr().out.strip().splitlines()[-1]
    evt = json.loads(line)
    assert evt["event"] == "error"
    assert "message" in evt


def test_system_specs_positive():
    cpu, mem = runner._system_specs()
    assert cpu >= 1
    assert mem > 0


def test_template_dir_exists():
    assert (runner._template_dir() / "system" / "controlDict").is_file()
