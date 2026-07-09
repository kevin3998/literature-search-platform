from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier


def test_write_jsonl_uses_per_write_temp_files_for_concurrent_writes(monkeypatch, tmp_path):
    from modules.structured_extraction import artifacts

    target = tmp_path / "audit" / "review_field_states_run_1.jsonl"
    barrier = Barrier(2)
    original_write_text = Path.write_text

    def delayed_write_text(self, *args, **kwargs):
        result = original_write_text(self, *args, **kwargs)
        if self.name.startswith(target.name) and ".tmp" in self.name:
            barrier.wait(timeout=5)
        return result

    monkeypatch.setattr(Path, "write_text", delayed_write_text)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(artifacts.write_jsonl, target, [{"thread": "a"}]),
            pool.submit(artifacts.write_jsonl, target, [{"thread": "b"}]),
        ]
        for future in futures:
            future.result(timeout=5)

    assert target.exists()
    assert "thread" in target.read_text(encoding="utf-8")
