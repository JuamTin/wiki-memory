import threading
from collections.abc import Sequence

from ..config import Embeddings


class LocalEmbedder:
    def __init__(self, config: Embeddings) -> None:
        self.config = config
        self._model = None
        self.error: str | None = None
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    @property
    def is_ready(self) -> bool:
        return self._model is not None

    def start_background_load(self) -> None:
        with self._lock:
            if self.config.enabled and self._thread is None:
                self._thread = threading.Thread(target=self._load, name="wiki-minilm", daemon=True)
                self._thread.start()

    def wait(self) -> None:
        self.start_background_load()
        if self._thread:
            self._thread.join()
        if self.error:
            raise RuntimeError(self.error)

    def _load(self) -> None:
        try:
            from fastembed import TextEmbedding
            self._model = TextEmbedding(model_name=self.config.model, threads=self.config.threads,
                                        cache_dir=str(self.config.cache_dir))
        except Exception as exc:
            self.error = f"{type(exc).__name__}: {exc}"

    def embed_passages(self, texts: Sequence[str]) -> list[bytes]:
        if self._model is None:
            raise RuntimeError("Modelo pendiente")
        return [v.astype("<f4").tobytes() for v in self._model.passage_embed(list(texts))]

    def embed_query(self, text: str) -> bytes:
        if self._model is None:
            raise RuntimeError("Modelo pendiente")
        return next(self._model.query_embed(text)).astype("<f4").tobytes()
