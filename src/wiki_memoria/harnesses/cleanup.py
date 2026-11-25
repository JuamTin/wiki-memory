import json
import os
from pathlib import Path
from urllib.error import URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from ..files import atomic_write, file_lock


class ConversationCleanup:
    def __init__(self) -> None:
        config = Path(os.environ.get("WIKI_MEMORIA_CONFIG", "~/.wiki-memoria/config.json")).expanduser()
        self.path = config.parent / "internal_sessions.json"

    def run(self, new_id: str | None = None) -> None:
        if not new_id and not self.path.is_file():
            return
        with file_lock(self.path.with_suffix(".lock")):
            ids = json.loads(self.path.read_text()) if self.path.exists() else []
            if new_id and new_id not in ids:
                ids.append(new_id)
            remaining = [item for item in ids if not self.delete(item)]
            atomic_write(self.path, json.dumps(remaining))

    @staticmethod
    def delete(conversation: str) -> bool:
        addr = os.getenv("ANTIGRAVITY_LS_ADDRESS", "")
        token = os.getenv("ANTIGRAVITY_CSRF_TOKEN")
        if not addr or not token:
            return False
        address = urlsplit(addr if "://" in addr else "http://" + addr)
        if address.hostname not in {"localhost", "127.0.0.1", "::1"}:
            return False
        url = f"{address.scheme}://{address.netloc}/product.v1.ConversationService/DeleteConversation"
        request = Request(url, json.dumps({"conversationId": conversation}).encode(),
                          {"Content-Type": "application/json", "Connect-Protocol-Version": "1",
                           "x-antigravity-csrf-token": token})
        try:
            with urlopen(request, timeout=2) as response:
                return response.status == 200
        except (URLError, OSError):
            return False
