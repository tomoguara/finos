"""Tests for the ``finos state`` toolkit (Step 1b)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from finos.cli.main import app
from finos.state import SupportState

ANSI = "\x1b["
FIELDS = ["query", "intent", "response", "context", "retrieved_sources"]


def _state(**overrides) -> dict:
    state = {
        "query": "test",
        "intent": "policy",
        "response": "",
        "context": "",
        "retrieved_sources": [],
    }
    state.update(overrides)
    return state


VALID = json.dumps(_state())
INVALID = json.dumps(_state(intent="bad_value"))
INPUT_COMMANDS = ["validate", "serialize", "deserialize"]


@pytest.fixture
def runner(monkeypatch: pytest.MonkeyPatch) -> CliRunner:
    monkeypatch.delenv("NO_COLOR", raising=False)
    return CliRunner()


def run(runner: CliRunner, *args: str, **kwargs):
    return runner.invoke(app, list(args), prog_name="finos", **kwargs)


# --- show -------------------------------------------------------------------


def test_show_human(runner: CliRunner):
    result = run(runner, "state", "show")
    assert result.exit_code == 0
    lines = result.stdout.splitlines()
    positions = [result.stdout.index(f"\n{name} ") for name in FIELDS]
    assert positions == sorted(positions)
    sources = next(line for line in lines if line.startswith("retrieved_sources"))
    assert "list[str]" in sources
    assert "Filenames" in sources


def test_show_json(runner: CliRunner):
    result = run(runner, "state", "show", "--json")
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["name"] == "SupportState"
    assert [f["name"] for f in data["fields"]] == FIELDS
    types = {f["name"]: f["type"] for f in data["fields"]}
    assert types["retrieved_sources"] == "list[str]"
    assert types["query"] == "str"
    assert all(set(f) == {"name", "type", "description"} for f in data["fields"])


def test_show_json_in_either_position(runner: CliRunner):
    assert (
        run(runner, "--json", "state", "show").stdout
        == run(runner, "state", "show", "--json").stdout
    )


def test_show_no_color_has_no_ansi(runner: CliRunner):
    result = run(runner, "state", "show", "--no-color", color=True)
    assert result.exit_code == 0
    assert ANSI not in result.stdout


# --- describe ---------------------------------------------------------------


def test_describe_human(runner: CliRunner):
    result = run(runner, "state", "describe")
    assert result.exit_code == 0
    rows = {line.split()[0]: line for line in result.stdout.splitlines() if line}
    assert "classify_intent" in rows["intent"]
    assert "policy_agent" in rows["context"]
    assert "policy_agent" in rows["retrieved_sources"]
    planned = [line for line in result.stdout.splitlines() if "history" in line]
    assert len(planned) == 1 and "Phase 2" in planned[0]


def test_describe_json(runner: CliRunner):
    result = run(runner, "state", "describe", "--json")
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert [f["name"] for f in data["fields"]] == FIELDS
    by_name = {f["name"]: f for f in data["fields"]}
    assert by_name["intent"]["written_by"] == "classify_intent"
    assert by_name["intent"]["initial"] == '""'
    assert [p["name"] for p in data["planned"]] == ["history"]


# --- init -------------------------------------------------------------------


def test_init_with_query(runner: CliRunner):
    result = run(runner, "state", "init", "--query", "What is the overdraft fee?")
    assert result.exit_code == 0
    assert json.loads(result.stdout) == _state(
        query="What is the overdraft fee?", intent=""
    )
    assert result.stdout.startswith("{\n  ")


def test_init_without_query(runner: CliRunner):
    result = run(runner, "state", "init")
    assert json.loads(result.stdout) == _state(query="", intent="")


def test_init_json_gives_the_same_output(runner: CliRunner):
    plain = run(runner, "state", "init", "-q", "x")
    assert run(runner, "state", "init", "-q", "x", "--json").stdout == plain.stdout
    assert run(runner, "-j", "state", "init", "-q", "x").stdout == plain.stdout


def test_init_output_passes_validation(runner: CliRunner):
    output = run(runner, "state", "init", "--query", "test").stdout
    result = run(runner, "state", "validate", "--file", "-", input=output)
    assert result.exit_code == 0


def test_init_cannot_set_other_fields(runner: CliRunner):
    result = run(runner, "state", "init", "--intent", "policy")
    assert result.exit_code == 2
    assert result.stdout == ""


# --- input pipeline ---------------------------------------------------------


@pytest.mark.parametrize("command", INPUT_COMMANDS)
def test_inline_data(runner: CliRunner, command: str):
    assert run(runner, "state", command, "--data", VALID).exit_code == 0
    assert run(runner, "state", command, "-d", VALID).exit_code == 0


@pytest.mark.parametrize("command", INPUT_COMMANDS)
def test_file(runner: CliRunner, command: str, tmp_path: Path):
    path = tmp_path / "state.json"
    path.write_text(VALID, encoding="utf-8")
    assert run(runner, "state", command, "--file", str(path)).exit_code == 0
    assert run(runner, "state", command, "-f", str(path)).exit_code == 0


@pytest.mark.parametrize("command", INPUT_COMMANDS)
def test_stdin(runner: CliRunner, command: str):
    assert run(runner, "state", command, "--file", "-", input=VALID).exit_code == 0


def _assert_usage_error(result, *needles: str) -> None:
    assert result.exit_code == 2
    assert result.stdout == ""
    for needle in needles:
        assert needle in result.stderr


@pytest.mark.parametrize("command", INPUT_COMMANDS)
def test_both_sources(runner: CliRunner, command: str, tmp_path: Path):
    path = tmp_path / "state.json"
    path.write_text(VALID, encoding="utf-8")
    result = run(runner, "state", command, "--data", VALID, "--file", str(path))
    _assert_usage_error(result, "--data", "--file")


@pytest.mark.parametrize("command", INPUT_COMMANDS)
def test_neither_source(runner: CliRunner, command: str):
    # Input is available on stdin, but must not be read without `--file -`.
    result = run(runner, "state", command, input=VALID)
    _assert_usage_error(result, "--data", "--file")


@pytest.mark.parametrize("command", INPUT_COMMANDS)
@pytest.mark.parametrize("json_flag", [[], ["--json"]])
def test_malformed_json(runner: CliRunner, command: str, json_flag: list[str]):
    result = run(runner, "state", command, "--data", "{not json", *json_flag)
    _assert_usage_error(result, "JSON")
    assert not result.stderr.lstrip().startswith("{")


@pytest.mark.parametrize("command", INPUT_COMMANDS)
def test_missing_file(runner: CliRunner, command: str, tmp_path: Path):
    path = tmp_path / "missing.json"
    result = run(runner, "state", command, "--file", str(path))
    _assert_usage_error(result, str(path))


@pytest.mark.parametrize("command", INPUT_COMMANDS)
def test_invalid_utf8(runner: CliRunner, command: str, tmp_path: Path):
    path = tmp_path / "state.json"
    path.write_bytes(b'{"query": "\xff"}')
    _assert_usage_error(run(runner, "state", command, "--file", str(path)), "UTF-8")
    _assert_usage_error(
        run(runner, "state", command, "--file", "-", input=b'{"query": "\xff"}'),
        "UTF-8",
    )


@pytest.mark.parametrize("command", INPUT_COMMANDS)
def test_non_object_json_is_invalid_state_not_unusable(runner: CliRunner, command: str):
    assert run(runner, "state", command, "--data", "[1, 2]").exit_code == 1


# --- validate ---------------------------------------------------------------


def test_validate_valid_state(runner: CliRunner):
    result = run(runner, "state", "validate", "--data", VALID)
    assert result.exit_code == 0
    assert "valid SupportState" in result.stdout


def test_validate_valid_mid_run_state(runner: CliRunner):
    state = json.dumps(_state(intent="policy", response="", context=""))
    assert run(runner, "state", "validate", "--data", state).exit_code == 0


def test_validate_invalid_state(runner: CliRunner):
    result = run(runner, "state", "validate", "--data", INVALID)
    assert result.exit_code == 1
    assert "intent" in result.stdout
    assert "bad_value" in result.stdout


def test_validate_not_an_object(runner: CliRunner):
    result = run(runner, "state", "validate", "--data", "[1, 2]")
    assert result.exit_code == 1
    assert "JSON object" in result.stdout


def test_validate_reports_every_problem(runner: CliRunner):
    data = '{"query": "test", "intent": "unknown_intent"}'
    result = run(runner, "state", "validate", "--data", data)
    assert result.exit_code == 1
    assert "unknown_intent" in result.stdout
    for valid in ("policy", "account_status", "escalation"):
        assert valid in result.stdout
    for name in ("response", "context", "retrieved_sources"):
        assert f"missing field '{name}'" in result.stdout


def test_validate_extra_field(runner: CliRunner):
    data = json.dumps(_state(history=[]))
    result = run(runner, "state", "validate", "--data", data)
    assert result.exit_code == 1
    assert "history" in result.stdout


@pytest.mark.parametrize("sources", ["a.md", ["a.md", 1]])
def test_validate_wrong_types(runner: CliRunner, sources):
    data = json.dumps(_state(retrieved_sources=sources))
    result = run(runner, "state", "validate", "--data", data)
    assert result.exit_code == 1
    assert "retrieved_sources" in result.stdout


def test_validate_unnormalized_intent(runner: CliRunner):
    data = json.dumps(_state(intent="Policy"))
    result = run(runner, "state", "validate", "--data", data)
    assert result.exit_code == 1
    assert "intent" in result.stdout


def test_validate_json_verdict(runner: CliRunner):
    result = run(runner, "state", "validate", "--json", "--data", INVALID)
    assert result.exit_code == 1
    verdict = json.loads(result.stdout)
    assert verdict["valid"] is False
    assert verdict["errors"]
    valid = json.loads(run(runner, "-j", "state", "validate", "-d", VALID).stdout)
    assert valid == {"valid": True, "errors": []}


def test_validate_colors_the_verdict(runner: CliRunner):
    result = run(runner, "state", "validate", "--data", VALID, color=True)
    assert ANSI in result.stdout


@pytest.mark.parametrize(
    "args, env",
    [
        (["--no-color"], {}),
        ([], {"NO_COLOR": "1"}),
    ],
)
def test_validate_color_can_be_disabled(runner: CliRunner, args, env):
    for data in (VALID, INVALID):
        result = run(
            runner, "state", "validate", "--data", data, *args, color=True, env=env
        )
        assert ANSI not in result.stdout


def test_validate_verbose_changes_only_stderr(runner: CliRunner):
    for data in (VALID, INVALID):
        quiet = run(runner, "state", "validate", "--strict", "-d", data)
        loud = run(runner, "-v", "state", "validate", "--strict", "-d", data, "-v")
        assert quiet.stdout == loud.stdout
        assert quiet.exit_code == loud.exit_code
        assert quiet.stderr == ""
        assert loud.stderr


def test_validate_json_flag_takes_no_value(runner: CliRunner):
    result = run(runner, "state", "validate", "--json", '{"query":"test"}')
    assert result.exit_code == 2


# --- validate --strict ------------------------------------------------------


def _strict(runner: CliRunner, **overrides):
    data = json.dumps(_state(**overrides))
    return run(runner, "state", "validate", "--strict", "--data", data)


@pytest.mark.parametrize(
    "name", ["account_fees.md", "fraud_policy.md", "loan_policy.md", "transfer_policy.md"]
)
def test_strict_known_source(runner: CliRunner, name: str):
    result = _strict(runner, context="c", retrieved_sources=[name])
    assert result.exit_code == 0, result.stdout


def test_strict_unknown_source(runner: CliRunner):
    result = _strict(runner, retrieved_sources=["nope.md"])
    assert result.exit_code == 1
    assert "nope.md" in result.stdout


@pytest.mark.parametrize(
    "path", ["../config.toml", "data/policy-docs/account_fees.md"]
)
def test_strict_path_instead_of_name(runner: CliRunner, path: str):
    result = _strict(runner, retrieved_sources=[path])
    assert result.exit_code == 1
    assert path in result.stdout


@pytest.mark.parametrize("intent", ["account_status", ""])
def test_strict_non_policy_state_with_context(runner: CliRunner, intent: str):
    result = _strict(runner, intent=intent, context="some context")
    assert result.exit_code == 1
    assert "context" in result.stdout


def test_strict_policy_state_with_no_retrieval_result(runner: CliRunner):
    assert _strict(runner, context="", retrieved_sources=[]).exit_code == 0


def test_strict_checks_are_off_by_default(runner: CliRunner):
    data = json.dumps(_state(retrieved_sources=["nope.md"]))
    assert run(runner, "state", "validate", "--data", data).exit_code == 0


def test_strict_missing_policy_directory(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    import finos.config

    missing = tmp_path / "no-such-dir"
    monkeypatch.setattr(finos.config, "POLICY_DOCS_DIR", missing)
    result = _strict(runner)
    _assert_usage_error(result, str(missing))


def test_strict_ignores_hidden_files_and_directories(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    import finos.config

    (tmp_path / "a.md").write_text("a", encoding="utf-8")
    (tmp_path / ".hidden.md").write_text("h", encoding="utf-8")
    (tmp_path / "sub").mkdir()
    monkeypatch.setattr(finos.config, "POLICY_DOCS_DIR", tmp_path)
    assert _strict(runner, retrieved_sources=["a.md"]).exit_code == 0
    assert _strict(runner, retrieved_sources=[".hidden.md"]).exit_code == 1
    assert _strict(runner, retrieved_sources=["sub"]).exit_code == 1


# --- serialize --------------------------------------------------------------

REORDERED = json.dumps(dict(reversed(list(_state(query="q").items()))))


def test_serialize_contract_order(runner: CliRunner):
    result = run(runner, "state", "serialize", "--data", REORDERED)
    assert result.exit_code == 0
    assert list(json.loads(result.stdout)) == FIELDS
    assert result.stdout.startswith('{\n  "query": "q",\n')


def test_serialize_compact(runner: CliRunner):
    result = run(runner, "state", "serialize", "--compact", "--data", VALID)
    assert result.exit_code == 0
    assert result.stdout == (
        '{"query":"test","intent":"policy","response":"",'
        '"context":"","retrieved_sources":[]}\n'
    )


def test_serialize_sorted_keys(runner: CliRunner):
    result = run(runner, "state", "serialize", "--sort-keys", "--data", VALID)
    assert list(json.loads(result.stdout)) == sorted(FIELDS)


def test_serialize_same_state_same_output(runner: CliRunner):
    first = run(runner, "state", "serialize", "--data", REORDERED)
    second = run(runner, "state", "serialize", "--data", json.dumps(_state(query="q")))
    assert first.stdout_bytes == second.stdout_bytes


def test_serialize_non_ascii(runner: CliRunner):
    data = json.dumps(_state(query="café"))
    result = run(runner, "state", "serialize", "--data", data)
    assert "café" in result.stdout
    assert "\\u" not in result.stdout


def test_serialize_json_flag_changes_nothing(runner: CliRunner):
    plain = run(runner, "state", "serialize", "--data", VALID).stdout
    assert run(runner, "state", "serialize", "--json", "--data", VALID).stdout == plain
    assert run(runner, "--json", "state", "serialize", "--data", VALID).stdout == plain


# --- deserialize ------------------------------------------------------------


def test_deserialize_expression(runner: CliRunner):
    data = json.dumps(_state(retrieved_sources=["account_fees.md"]))
    result = run(runner, "state", "deserialize", "--data", data)
    assert result.exit_code == 0
    text = result.stdout.strip()
    assert text.startswith("SupportState(query='test', ")
    assert text.endswith("retrieved_sources=['account_fees.md'])")


def test_deserialize_round_trip(runner: CliRunner):
    state = _state(query="it's \"quoted\" é", context="x\ny", retrieved_sources=["a"])
    result = run(runner, "state", "deserialize", "--data", json.dumps(state))
    assert eval(result.stdout, {"SupportState": SupportState}) == state


def test_deserialize_json_in_either_position(runner: CliRunner):
    after = run(runner, "state", "deserialize", "--data", REORDERED, "--json")
    before = run(runner, "--json", "state", "deserialize", "--data", REORDERED)
    serialized = run(runner, "state", "serialize", "--data", REORDERED)
    assert after.exit_code == before.exit_code == 0
    assert after.stdout == before.stdout == serialized.stdout


# --- converters on invalid state --------------------------------------------


@pytest.mark.parametrize("command", ["serialize", "deserialize"])
@pytest.mark.parametrize("json_flag", [[], ["--json"]])
def test_converters_refuse_invalid_state_on_stderr(
    runner: CliRunner, command: str, json_flag: list[str]
):
    data = '{"query": "test", "intent": "bad_value"}'
    result = run(runner, "state", command, "--data", data, *json_flag)
    assert result.exit_code == 1
    assert result.stdout == ""
    for needle in ("bad_value", "response", "context", "retrieved_sources"):
        assert needle in result.stderr


def test_serialize_redirected_output_stays_clean(tmp_path: Path):
    import subprocess
    import sys

    out = tmp_path / "out.json"
    with out.open("w") as handle:
        result = subprocess.run(
            [sys.executable, "-m", "finos", "state", "serialize", "--data", INVALID],
            stdout=handle,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
    assert result.returncode == 1
    assert "intent" in result.stderr
    assert out.read_text() == ""


# --- offline, without settings ----------------------------------------------

ALL_COMMANDS = [
    (["show"], 0),
    (["describe"], 0),
    (["init", "--query", "test"], 0),
    (["validate", "--strict", "--data", VALID], 0),
    (["serialize", "--data", VALID], 0),
    (["deserialize", "--data", VALID], 0),
]


@pytest.mark.parametrize("args, code", ALL_COMMANDS)
def test_state_commands_run_without_settings(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch, args: list[str], code: int
):
    import finos.config

    def refuse():
        raise AssertionError("state commands must not load settings")

    monkeypatch.setattr(finos.config, "get_settings", refuse)
    for name in ("OPENAI_API_KEY", "LANGCHAIN_API_KEY", "LANGSMITH_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    result = run(runner, "state", *args)
    assert result.exit_code == code, result.output
    result = run(runner, "--json", "state", *args)
    assert result.exit_code == code, result.output


def test_state_group_help_lists_all_commands(runner: CliRunner):
    result = run(runner, "state", "--help")
    assert result.exit_code == 0
    for name in ("show", "describe", "init", "validate", "serialize", "deserialize"):
        assert name in result.stdout


# --- converters writing to --output ------------------------------------------

CONVERTERS = ["serialize", "deserialize"]


@pytest.mark.parametrize("command", CONVERTERS)
@pytest.mark.parametrize("extra", [[], ["--json"]])
def test_output_holds_the_same_bytes_as_stdout(
    runner: CliRunner, tmp_path: Path, command: str, extra: list[str]
):
    path = tmp_path / "out.txt"
    printed = run(runner, "state", command, "--data", REORDERED, *extra)
    result = run(runner, "state", command, "--data", REORDERED, *extra, "-o", str(path))
    assert result.exit_code == 0, result.output
    assert result.stdout == ""
    assert path.read_bytes() == printed.stdout_bytes


def test_output_honors_formatting_options(runner: CliRunner, tmp_path: Path):
    path = tmp_path / "out.json"
    result = run(
        runner, "state", "serialize", "--compact", "--sort-keys",
        "--data", VALID, "--output", str(path),
    )
    assert result.exit_code == 0
    text = path.read_text("utf-8")
    assert text.count("\n") == 1 and text.endswith("\n")
    assert list(json.loads(text)) == sorted(FIELDS)


def test_deserialize_output_with_and_without_json(runner: CliRunner, tmp_path: Path):
    expression, as_json = tmp_path / "state.py", tmp_path / "state.json"
    assert run(runner, "state", "deserialize", "-d", VALID, "-o", str(expression)).exit_code == 0
    assert run(runner, "--json", "state", "deserialize", "-d", VALID, "-o", str(as_json)).exit_code == 0
    assert expression.read_text("utf-8").startswith("SupportState(query='test', ")
    assert json.loads(as_json.read_text("utf-8")) == json.loads(VALID)


def test_output_keeps_non_ascii_as_utf8(runner: CliRunner, tmp_path: Path):
    path = tmp_path / "out.json"
    run(runner, "state", "serialize", "-d", json.dumps(_state(query="café")), "-o", str(path))
    assert "café".encode("utf-8") in path.read_bytes()


@pytest.mark.parametrize("command", CONVERTERS)
def test_output_creates_parent_directories(
    runner: CliRunner, tmp_path: Path, command: str
):
    path = tmp_path / "a" / "b" / "out.txt"
    result = run(runner, "state", command, "--data", VALID, "--output", str(path))
    assert result.exit_code == 0
    assert path.is_file()


@pytest.mark.parametrize("command", CONVERTERS)
def test_dash_output_means_stdout(runner: CliRunner, command: str):
    plain = run(runner, "state", command, "--data", VALID)
    dashed = run(runner, "state", command, "--data", VALID, "--output", "-")
    assert dashed.exit_code == 0
    assert dashed.stdout == plain.stdout != ""


def test_verbose_names_the_destination(runner: CliRunner, tmp_path: Path):
    path = tmp_path / "out.json"
    result = run(runner, "-v", "state", "serialize", "-d", VALID, "-o", str(path))
    assert result.exit_code == 0
    assert result.stdout == ""
    assert str(path) in result.stderr


def test_quiet_write_reports_nothing(runner: CliRunner, tmp_path: Path):
    result = run(runner, "state", "serialize", "-d", VALID, "-o", str(tmp_path / "o"))
    assert result.stdout == "" and result.stderr == ""


@pytest.mark.parametrize("command", CONVERTERS)
def test_existing_output_is_refused(runner: CliRunner, tmp_path: Path, command: str):
    path = tmp_path / "out.txt"
    path.write_text("keep me", encoding="utf-8")
    result = run(runner, "state", command, "--data", VALID, "--output", str(path))
    _assert_usage_error(result, str(path), "--force")
    assert path.read_text("utf-8") == "keep me"


@pytest.mark.parametrize("command", CONVERTERS)
def test_force_overwrites(runner: CliRunner, tmp_path: Path, command: str):
    path = tmp_path / "out.txt"
    path.write_text("old", encoding="utf-8")
    printed = run(runner, "state", command, "--data", VALID)
    result = run(runner, "state", command, "-d", VALID, "-o", str(path), "--force")
    assert result.exit_code == 0
    assert path.read_bytes() == printed.stdout_bytes


@pytest.mark.parametrize("command", CONVERTERS)
def test_force_without_output(runner: CliRunner, command: str):
    result = run(runner, "state", command, "--data", VALID, "--force")
    _assert_usage_error(result, "--force", "--output")


def test_output_can_replace_its_own_input(runner: CliRunner, tmp_path: Path):
    path = tmp_path / "state.json"
    path.write_text(REORDERED, encoding="utf-8")
    result = run(runner, "state", "serialize", "-f", str(path), "-o", str(path), "--force")
    assert result.exit_code == 0
    assert list(json.loads(path.read_text("utf-8"))) == FIELDS


@pytest.mark.parametrize("command", CONVERTERS)
@pytest.mark.parametrize("force", [[], ["--force"]])
def test_invalid_state_leaves_destination_alone(
    runner: CliRunner, tmp_path: Path, command: str, force: list[str]
):
    new, existing = tmp_path / "sub" / "new.txt", tmp_path / "existing.txt"
    existing.write_text("keep me", encoding="utf-8")
    for path in (new, existing):
        result = run(runner, "state", command, "-d", INVALID, "-o", str(path), *force)
        assert result.exit_code == 1
        assert "bad_value" in result.stderr
        assert result.stdout == ""
    assert not new.exists() and not new.parent.exists()
    assert existing.read_text("utf-8") == "keep me"


@pytest.mark.parametrize("command", CONVERTERS)
@pytest.mark.parametrize("force", [[], ["--force"]])
def test_directory_destination_is_unwritable(
    runner: CliRunner, tmp_path: Path, command: str, force: list[str]
):
    result = run(runner, "state", command, "-d", VALID, "-o", str(tmp_path), *force)
    _assert_usage_error(result, str(tmp_path))


def test_destination_under_a_file_is_unwritable(runner: CliRunner, tmp_path: Path):
    blocker = tmp_path / "file"
    blocker.write_text("x", encoding="utf-8")
    result = run(runner, "state", "serialize", "-d", VALID, "-o", str(blocker / "out.json"))
    _assert_usage_error(result, "cannot write")


def test_unusable_input_is_reported_before_output(runner: CliRunner, tmp_path: Path):
    path = tmp_path / "out.json"
    result = run(runner, "state", "serialize", "-d", "{not json", "-o", str(path))
    _assert_usage_error(result, "JSON")
    assert not path.exists()


@pytest.mark.parametrize("command", CONVERTERS)
def test_output_options_listed_in_help(runner: CliRunner, command: str):
    result = run(runner, "state", command, "--help")
    for flag in ("--output", "-o", "--force", "--file"):
        assert flag in result.stdout


def test_output_option_is_only_on_converters(runner: CliRunner, tmp_path: Path):
    result = run(runner, "state", "validate", "-d", VALID, "-o", str(tmp_path / "x"))
    assert result.exit_code == 2
