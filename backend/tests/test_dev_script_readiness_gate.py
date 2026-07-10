from pathlib import Path


def test_dev_script_uses_deep_readiness_before_marking_backend_ready():
    script = Path("dev.sh").read_text(encoding="utf-8")

    assert "/api/readiness" in script
    assert "后端已就绪" not in script.split("/api/readiness", 1)[0]


def test_dev_script_checks_structured_extraction_routes_before_marking_ready():
    script = Path("dev.sh").read_text(encoding="utf-8")

    assert "BACKEND_CONTRACT_PROBE" in script
    assert "/api/structured-extraction/tasks/__route_probe__/collection/candidates" in script
    assert 'probe_status" == "401"' in script
    assert "backend_contract_ok" in script
    assert "后端已就绪" not in script.split("backend_contract_ok", 1)[0]


def test_dev_script_restarts_backend_instead_of_reusing_existing_listener():
    script = Path("dev.sh").read_text(encoding="utf-8")

    assert "backend_reused" not in script
    assert "检测到已有后端进程，正在停止" in script
    assert "检测到已有可用后端，复用" not in script
    assert "stop_existing_backend" in script


def test_dev_script_runs_postgres_migrations_and_worker():
    script = Path("dev.sh").read_text(encoding="utf-8")

    assert "DATABASE_URL" in script
    assert "postgresql+psycopg://literature_agent:literature_agent_dev@127.0.0.1" in script
    assert "alembic -c" in script
    assert "upgrade head" in script
    assert "worker_pid" in script
    assert "python -m core.worker.main" in script
    assert "START_WORKER" in script
    assert "LITERATURE_MEMORY_DB_PATH" not in script


def test_dev_script_normalizes_secret_key_path_before_starting_processes():
    script = Path("dev.sh").read_text(encoding="utf-8")

    assert "normalize_runtime_path" in script
    assert 'export LITERATURE_SECRET_KEY_PATH="$(normalize_runtime_path "$LITERATURE_SECRET_KEY_PATH")"' in script
