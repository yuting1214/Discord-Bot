"""Layered configuration: environment > config/bot.yaml > defaults.

The precedence is the whole point. This template publishes environment variables
that deployers already set on Railway, and a configuration file that quietly won
over them would change a running bot's behaviour on its next rebuild.
"""

import textwrap

import pytest
import yaml

from src.config import (
    _ENV_OVERRIDES,
    BotConfig,
    apply_env_overrides,
    load_config,
)


def write(tmp_path, body: str):
    path = tmp_path / "bot.yaml"
    path.write_text(textwrap.dedent(body), encoding="utf-8")
    return path


def test_defaults_are_a_complete_configuration():
    """A missing file is not an error: the bot has to run with no YAML at all,
    because the file is only present in a checkout of this repository."""
    config = load_config(path=None, environ={})
    assert config.llm.provider == "openai"
    assert config.llm.temperature is None, "reasoning models reject any value but their own"
    assert config.search.top_n > 0
    assert config.prompts.system.strip()


def test_a_missing_file_falls_back_to_defaults(tmp_path):
    config = load_config(path=tmp_path / "absent.yaml", environ={})
    assert config == BotConfig()


def test_the_file_overrides_the_defaults(tmp_path):
    path = write(tmp_path, """
        llm:
          provider: openrouter
          timeout: 5
        search:
          top_n: 11
    """)
    config = load_config(path=path, environ={})
    assert config.llm.provider == "openrouter"
    assert config.llm.timeout == 5
    assert config.search.top_n == 11
    assert config.llm.max_retries == 2, "unspecified keys keep their defaults"


def test_the_environment_overrides_the_file(tmp_path):
    """Railway variables are how a deployed service is retuned without a
    rebuild. The file must never win over them."""
    path = write(tmp_path, """
        llm:
          provider: openrouter
        search:
          top_n: 11
    """)
    config = load_config(path=path, environ={"LLM_PROVIDER": "openai", "SEARCH_TOP_N": "3"})
    assert config.llm.provider == "openai"
    assert config.search.top_n == 3


def test_every_published_variable_still_works():
    """These names predate the file and are set on live deployments, so none of
    them may be dropped or renamed."""
    environ = {
        "LLM_PROVIDER": "openrouter",
        "OPENAI_MODEL": "gpt-x",
        "OPENROUTER_MODEL": "vendor/gpt-x",
        "LLM_TEMPERATURE": "0.25",
        "LLM_REASONING": "false",
        "LLM_TIMEOUT": "12.5",
        "LLM_MAX_RETRIES": "7",
        "EMBEDDING_MODEL": "embed-x",
        "EMBEDDING_DIM": "256",
        "SEARCH_TOP_N": "9",
        "SEARCH_RRF_K": "30",
        "SEARCH_LEXICAL_WEIGHT": "2.0",
        "SEARCH_SEMANTIC_WEIGHT": "0.5",
        "SEARCH_SEMANTIC_MAX_DISTANCE": "0.42",
        "SUMMARY_ENABLED": "false",
        "SUMMARY_IDLE_MINUTES": "5",
        "SUMMARY_SWEEP_INTERVAL_MINUTES": "2",
        "SUMMARY_BATCH_SIZE": "4",
        "MEMORY_WINDOW_SIZE": "8",
    }
    assert set(environ) == {name for name, _, _ in _ENV_OVERRIDES}, "the mapping table drifted"

    config = load_config(path=None, environ=environ)
    assert config.llm.provider == "openrouter"
    assert config.llm.model_for("openai") == "gpt-x"
    assert config.llm.model_for("openrouter") == "vendor/gpt-x"
    assert config.llm.temperature == 0.25
    assert config.llm.reasoning is False
    assert config.llm.timeout == 12.5
    assert config.llm.max_retries == 7
    assert config.embeddings.model == "embed-x"
    assert config.embeddings.dimensions == 256
    assert config.search.top_n == 9
    assert config.search.rrf_k == 30
    assert config.search.weights.lexical == 2.0
    assert config.search.weights.semantic == 0.5
    assert config.search.semantic_max_distance == 0.42
    assert config.summary.enabled is False
    assert config.summary.idle_minutes == 5
    assert config.summary.sweep_interval_minutes == 2
    assert config.summary.batch_size == 4
    assert config.memory.window_size == 8


def test_an_empty_temperature_means_unset_not_zero():
    """`LLM_TEMPERATURE=` is how a Railway variable is cleared, and 0.0 is a real
    temperature that reasoning models reject with a 400."""
    assert load_config(path=None, environ={"LLM_TEMPERATURE": ""}).llm.temperature is None
    assert load_config(path=None, environ={"LLM_TEMPERATURE": "0"}).llm.temperature == 0.0


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("true", True), ("TRUE", True), ("1", True), ("yes", True), ("on", True),
     ("false", False), ("0", False), ("no", False), ("", False), ("maybe", False)],
)
def test_booleans_accept_what_a_deployer_would_type(raw, expected):
    assert load_config(path=None, environ={"LLM_REASONING": raw}).llm.reasoning is expected


def test_one_malformed_variable_does_not_take_the_process_down(caplog):
    """A bad value in the dashboard should degrade to the default, not crash the
    container on boot where nobody can reach the dashboard to fix it."""
    with caplog.at_level("WARNING"):
        config = load_config(path=None, environ={"SEARCH_TOP_N": "lots", "LLM_PROVIDER": "openrouter"})
    assert config.search.top_n == BotConfig().search.top_n
    assert config.llm.provider == "openrouter", "the other variables still applied"
    assert "SEARCH_TOP_N" in caplog.text


def test_a_broken_file_falls_back_rather_than_crashing(tmp_path):
    path = tmp_path / "bot.yaml"
    path.write_text("llm:\n  provider: [unclosed\n", encoding="utf-8")
    assert load_config(path=path, environ={}) == BotConfig()


def test_a_file_that_is_not_a_mapping_is_ignored(tmp_path):
    path = tmp_path / "bot.yaml"
    path.write_text("- just\n- a list\n", encoding="utf-8")
    assert load_config(path=path, environ={}) == BotConfig()


def test_the_shipped_file_parses_and_matches_the_schema():
    """config/bot.yaml is the documentation for these settings, so a key that no
    longer exists is a broken instruction to a deployer."""
    from src.config import DEFAULT_CONFIG_PATH

    assert DEFAULT_CONFIG_PATH.is_file(), DEFAULT_CONFIG_PATH
    raw = yaml.safe_load(DEFAULT_CONFIG_PATH.read_text(encoding="utf-8"))

    def walk(data: dict, model, path=""):
        for key, value in data.items():
            assert key in model.model_fields, f"{path}{key} is not a setting"
            if isinstance(value, dict):
                nested = model.model_fields[key].annotation
                if hasattr(nested, "model_fields"):
                    walk(value, nested, f"{path}{key}.")

    walk(raw, BotConfig)
    BotConfig.model_validate(raw)


def test_no_secret_is_ever_read_from_the_file():
    """The file is committed to a public template repository."""
    secrets = ("OPENAI_API_KEY", "DISCORD_TOKEN", "DATABASE_URL", "SECRET_KEY",
               "PASSWORD", "USER_NAME", "OPENROUTER_API_KEY")
    mapped = {name for name, _, _ in _ENV_OVERRIDES}
    assert mapped.isdisjoint(secrets)

    from src.config import DEFAULT_CONFIG_PATH

    body = DEFAULT_CONFIG_PATH.read_text(encoding="utf-8")
    for secret in secrets:
        assert secret not in body or "environment-only" in body


def test_overrides_do_not_mutate_the_callers_dictionary_shape():
    """A scalar where the schema wants a mapping must not raise -- a deployer
    typing `llm: openrouter` should get defaults, not a crash on boot."""
    data = {"llm": "openrouter"}
    apply_env_overrides(data, {"OPENAI_MODEL": "gpt-x"})
    assert data["llm"] == "openrouter"


def test_env_example_documents_every_variable():
    """.env.example is where a deployer looks for the knobs. A variable that
    exists and is not listed there is one nobody will find."""
    import pathlib

    from src.config import DEFAULT_CONFIG_PATH

    env_example = (DEFAULT_CONFIG_PATH.parents[1] / ".env.example").read_text()
    undocumented = [name for name, _, _ in _ENV_OVERRIDES if name not in env_example]
    assert not undocumented, f"add these to .env.example: {undocumented}"

    readme = pathlib.Path(DEFAULT_CONFIG_PATH.parents[1] / "README.md").read_text()
    assert "config/bot.yaml" in readme, "the README must point at the config file"
