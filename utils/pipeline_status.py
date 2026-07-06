from models.event_scraped_content import Status

STATUS_ORDER: list[Status] = [
    "scraped",
    "chunked",
    "usability_classification",
    "ai_tagged",
    "embedded",
]


class PipelineSkip(Exception):
    def __init__(self, reason: str, message: str) -> None:
        self.reason = reason
        self.message = message
        super().__init__(message)


def _status_index(status: Status) -> int:
    return STATUS_ORDER.index(status)


def check_scrape(*, exists: bool, status: Status | None, page_url: str) -> None:
    if exists:
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
