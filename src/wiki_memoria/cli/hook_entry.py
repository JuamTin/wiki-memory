"""Fast console entry point. Keep the recursion sentinel ahead of all app imports."""
import os


def main() -> None:
    if os.environ.get("WIKI_MEMORIA_INTERNAL") == "1":
        print("{}")
        return
    import argparse
    import json
    import sys
    from .hooks import HookService

    parser = argparse.ArgumentParser()
    parser.add_argument("--harness", choices=("claude", "codex", "antigravity"), required=True)
    parser.add_argument("--event", choices=("start", "prompt", "stop"), required=True)
    args = parser.parse_args()
    try:
        result = HookService().handle(args.harness, args.event, json.load(sys.stdin))
    except (PermissionError, NotADirectoryError):
        result = {}
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
