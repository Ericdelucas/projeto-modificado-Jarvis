"""Configuration kept inside the programming module."""

from dataclasses import dataclass


@dataclass
class ProgramacaoConfig:
    enabled: bool = False
    general_model: str = "qwen3:1.7b"
    code_model: str = "qwen2.5-coder:3b"
    rag_enabled: bool = True
    embedding_model: str = "nomic-embed-text"
    books_dir: str = "books-programação"
    vector_db_dir: str = ".runtime/vector_db"
    chunk_chars: int = 1600
    chunk_overlap: int = 200
    top_k: int = 3
    min_score: float = 0.35
    max_context_chars: int = 4800
    embedding_timeout: float = 15.0
    indexing_timeout: float = 120.0

    def validate(self) -> None:
        if not 0 <= self.chunk_overlap < self.chunk_chars <= 16000:
            raise ValueError("Use 0 <= chunk_overlap < chunk_chars <= 16000")
        if not 1 <= self.top_k <= 10:
            raise ValueError("top_k deve estar entre 1 e 10")
        if not 256 <= self.max_context_chars <= 16000:
            raise ValueError("max_context_chars deve estar entre 256 e 16000")
        if (
            not -1 <= self.min_score <= 1
            or self.embedding_timeout <= 0
            or self.indexing_timeout <= 0
        ):
            raise ValueError("min_score ou embedding_timeout inválido")
