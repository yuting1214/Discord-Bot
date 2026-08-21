"""Guards on the always-on process's memory floor.

Railway bills by memory per minute and this container runs 24/7, so the idle
floor is effectively the whole bill. Import-weight wins regress silently the
first time someone adds a convenient import four levels down, which is why this
is asserted rather than just measured once.

The check must run in a fresh interpreter: by the time the rest of the suite has
run, sys.modules is already polluted by everything else that imported.
"""

import json
import subprocess
import sys

import pytest

# Every one of these was removed from the dependency tree or the import path on
# the way to 0.2.0. Re-introducing any of them into the entrypoint is a
# regression, not a detail.
FORBIDDEN = [
    "langchain",
    "langchain_core",
    "langchain_openai",
    "langchain_community",
    "tiktoken",
    "numpy",
    "meilisearch",
    "requests",
    "psycopg2",
    "pytz",
    # Prefix-command machinery for a bot that only serves slash commands.
    "discord.ext.commands",
]


def _modules_after_importing(target: str) -> set[str]:
    code = (
        "import json, sys, os; os.environ.setdefault('OPENAI_API_KEY', 'test-key-not-real');"
        f"import {target};"
        "print(json.dumps(sorted(sys.modules)))"
    )
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr[-2000:]
    return set(json.loads(proc.stdout.strip().splitlines()[-1]))


@pytest.mark.parametrize("entrypoint", ["src.backend.fastapi.main", "src.llm.chat"])
def test_no_removed_dependency_creeps_back(entrypoint):
    resident = _modules_after_importing(entrypoint)
    found = sorted(m for m in FORBIDDEN if m in resident)
    assert found == [], f"{entrypoint} pulls in removed dependencies: {found}"


def test_llm_layer_does_not_import_the_web_app():
    """Importing llm/ must not drag in FastAPI or the application settings.

    llm/ used to import src.backend.constants, which imported the settings module --
    so touching the LLM layer configured the whole application as a side effect.
    """
    resident = _modules_after_importing("src.llm.chat")
    assert "fastapi" not in resident
    assert "src.backend.fastapi.core.init_settings" not in resident


def test_connection_pool_is_sized_for_an_idle_service():
    """pool_size connections are held forever; max_overflow closes on return."""
    from src.backend.fastapi.dependencies.database import pool_options_for

    options = pool_options_for("postgresql+asyncpg://u:p@localhost:5432/db")
    assert options["pool_size"] == 1, "permanent connections are billed idle memory"
    assert options["max_overflow"] == 12, "burst headroom should stay generous"
    assert options["pool_pre_ping"] is True
    assert options["pool_recycle"] == 1800


def test_sqlite_takes_no_pool_arguments():
    """SQLite rejects them outright, so development must get an empty set."""
    from src.backend.fastapi.dependencies.database import pool_options_for

    assert pool_options_for("sqlite+aiosqlite:///./dev.db") == {}
