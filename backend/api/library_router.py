from __future__ import annotations

import os
import time

from fastapi import APIRouter

from core.schemas import LibraryFile

router = APIRouter(prefix="/api", tags=["library"])

# 团队部署时，把环境变量 LIBRARY_DIR 指向真实的本地文献库目录即可，
# 比如 export LIBRARY_DIR=/data/shared/literature
LIBRARY_DIR = os.environ.get("LIBRARY_DIR", "")

_MOCK_FILES = [
    "Retrieval-Augmented_Generation_for_Knowledge-Intensive_NLP.pdf",
    "A_Survey_of_LLMs_for_Scientific_Literature_Mining.pdf",
    "Self-RAG_Learning_to_Retrieve_Generate_and_Critique.pdf",
    "From_Literature_Review_to_Hypothesis.pdf",
    "Towards_Reproducible_Experiment_Design.pdf",
]


@router.get("/library")
def list_library_files() -> list[LibraryFile]:
    if LIBRARY_DIR and os.path.isdir(LIBRARY_DIR):
        files = []
        for name in sorted(os.listdir(LIBRARY_DIR)):
            full = os.path.join(LIBRARY_DIR, name)
            if os.path.isfile(full):
                stat = os.stat(full)
                files.append(
                    LibraryFile(
                        name=name,
                        path=full,
                        size_kb=round(stat.st_size / 1024, 1),
                        modified=stat.st_mtime,
                    )
                )
        return files

    # 未配置真实目录时返回演示数据，方便先看界面效果
    now = time.time()
    return [
        LibraryFile(name=n, path=f"/library/{n}", size_kb=round(120 + i * 37.5, 1), modified=now - i * 86400)
        for i, n in enumerate(_MOCK_FILES)
    ]
