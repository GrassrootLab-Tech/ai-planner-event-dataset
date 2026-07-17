from models.event_scraped_content import Status

STATUS_ORDER: list[Status] = [
    "scraped",
    "chunked",
    "usability_classification",
    "claude_batch_queued",
    "ai_tagged",
    "anonymized",
    "embedded",
]

PIPELINE_STEP_NAMES: list[str] = [
    "scrape",
    "chunk",
    "classify",
    "tag",
    "anonymize",
    "embed",
]


class PipelineSkip(Exception):
    def __init__(self, reason: str, message: str) -> None:
        self.reason = reason
        self.message = message
        super().__init__(message)


def _status_index(status: Status) -> int:
    return STATUS_ORDER.index(status)


def check_scrape(*, exists: bool, status: Status | None, page_url: str) -> None:
    if exists and status != "failed":
        raise PipelineSkip(
            "already_done",
            f"Already scraped: page_url={page_url} (status={status})",
        )


def check_step(*, status: Status | None, required: Status, step_name: str) -> None:
    if status is None:
        raise PipelineSkip(
            "not_ready",
            f"Not yet ready for {step_name}: page has not been scraped",
        )

    if status == "failed":
        raise PipelineSkip(
            "not_ready",
            f"Not yet ready for {step_name}: scrape status is 'failed'",
        )

    if status == required:
        return

    if _status_index(status) > _status_index(required):
        raise PipelineSkip(
            "already_done",
            f"Already done for {step_name}: status is '{status}'",
        )

    raise PipelineSkip(
        "not_ready",
        f"Not yet ready for {step_name}: status is '{status}', expected '{required}'",
    )


def steps_to_run(*, exists: bool, status: Status | None) -> list[str]:
    if not exists:
        return list(PIPELINE_STEP_NAMES)

    current_status = status or "scraped"
    if current_status == "failed":
        return list(PIPELINE_STEP_NAMES)
    if current_status == "claude_batch_queued":
        return []

    status_index = _status_index(current_status)
    steps: list[str] = []

    if status_index < _status_index("chunked"):
        steps.append("chunk")
    if status_index < _status_index("usability_classification"):
        steps.append("classify")
    if status_index < _status_index("claude_batch_queued"):
        steps.append("tag")
    if status_index < _status_index("anonymized"):
        steps.append("anonymize")
    if status_index < _status_index("embedded"):
        steps.append("embed")

    return steps


def skip_message_for_step(
    step: str,
    *,
    exists: bool,
    status: Status | None,
    page_url: str,
) -> str:
    if step == "scrape":
        return f"Already scraped: page_url={page_url} (status={status})"

    step_labels = {
        "chunk": "chunking",
        "classify": "classification",
        "tag": "tagging",
        "anonymize": "anonymization",
        "embed": "embedding",
    }
    return f"Already done for {step_labels[step]}: status is '{status}'"
