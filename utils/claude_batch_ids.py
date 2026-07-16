from pathlib import Path

BATCH_IDS_PATH = Path("output/claude_batch_ids.txt")
_HEADER = "timestamp | batch_id | no_of_messages\n"


def append_claude_batch_id(
    *,
    timestamp: str,
    batch_id: str,
    no_of_messages: int,
    path: Path = BATCH_IDS_PATH,
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(_HEADER, encoding="utf-8")
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"{timestamp} | {batch_id} | {no_of_messages}\n")
    return path
