"""CLI tests for the M7 interface (argparse).

The CLI shares the same application use cases as the API. To avoid real Anthropic
/ Gmail calls, ``build_container`` is monkeypatched to return the fake container.
Confirms the four commands produce the same contract as the API and that the
approver-resolution B3 precedence holds on the CLI path too.
"""

from __future__ import annotations

import json

import pytest

from email_agent.interface import cli


def _write_draft(tmp_path, draft_json: str) -> str:
    p = tmp_path / "draft.json"
    p.write_text(draft_json, encoding="utf-8")
    return str(p)


@pytest.fixture
def patch_build(monkeypatch, fake_container):
    monkeypatch.setattr(cli, "build_container", lambda _settings: fake_container)
    return fake_container


def test_cli_draft_prints_dto(patch_build, capsys):
    rc = cli.main(["draft", "--request", "Confirm the meeting"])
    assert rc == 0
    # CLI draft emits the round-trippable DraftResponseDTO (client holds state).
    out = json.loads(capsys.readouterr().out)
    assert out["recipients"] == ["alice@example.com"]
    assert out["state"] == "AWAITING_APPROVAL"


def test_cli_send_round_trips_dto_file(patch_build, tmp_path, capsys):
    # First draft -> capture DTO. Then send using that file.
    assert cli.main(["draft", "--request", "Send to Alice"]) == 0
    out = capsys.readouterr().out
    draft_path = _write_draft(tmp_path, out)
    rc = cli.main(["send", "--draft-file", draft_path, "--approver", "Abhishek"])
    assert rc == 0
    sent = json.loads(capsys.readouterr().out)
    assert sent["status"] == "SENT"
    assert sent["message_id"] == "<msg-123>"


def test_cli_send_missing_approver_fails(patch_build, tmp_path, capsys):
    patch_build.settings.user.name = ""
    assert cli.main(["draft", "--request", "Send"]) == 0
    out = capsys.readouterr().out
    draft_path = _write_draft(tmp_path, out)
    rc = cli.main(["send", "--draft-file", draft_path])
    assert rc == 2
    err = json.loads(capsys.readouterr().err)
    assert err["code"] == "validation_error"


def test_cli_reject(patch_build, tmp_path, capsys):
    assert cli.main(["draft", "--request", "Reject"]) == 0
    out = capsys.readouterr().out
    draft_path = _write_draft(tmp_path, out)
    rc = cli.main(["reject", "--draft-file", draft_path, "--reason", "nope"])
    assert rc == 0
    assert json.loads(capsys.readouterr().out)["status"] == "REJECTED"


def test_cli_missing_draft_file_reports_not_found(patch_build, capsys):
    rc = cli.main(["send", "--draft-file", "/no/such/draft.json", "--approver", "Abhishek"])
    assert rc == 2
    err = json.loads(capsys.readouterr().err)
    assert err["code"] == "not_found"
