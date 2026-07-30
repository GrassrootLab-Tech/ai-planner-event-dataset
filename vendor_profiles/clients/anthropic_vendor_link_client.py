from __future__ import annotations

from anthropic import AsyncAnthropic
from pydantic import BaseModel, Field

from utils.logger import log_pretty, logger
from utils.pipeline_cost import TokenUsage
from vendor_profiles.prompts.vendor_profile_links import SYSTEM_PROMPT

TOOL_NAME = "submit_vendor_profile_urls"
MAX_TOKENS = 8_192


class VendorProfileLinksResult(BaseModel):
    urls: list[str] = Field(default_factory=list)


class VendorLinkFilterError(Exception):
    pass


class AnthropicVendorLinkClient:
    def __init__(self, client: AsyncAnthropic, model: str) -> None:
        self._client = client
        self._model = model

    @property
    def model(self) -> str:
        return self._model

    async def filter_profile_urls(
        self,
        *,
        page_title: str | None,
        all_links: list[str],
    ) -> tuple[list[str], TokenUsage]:
        if not all_links:
            return [], TokenUsage()

        title = (page_title or "").strip() or "(untitled directory page)"
        user_content = (
            f"page_title: {title}\n\n"
            "all_links:\n"
            + "\n".join(f"- {link}" for link in all_links)
        )

        log_pretty(
            "Filtering vendor profile links",
            {"model": self._model, "link_count": len(all_links), "page_title": title},
        )

        response = await self._client.messages.create(
            model=self._model,
            max_tokens=MAX_TOKENS,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_content}],
            tools=[
                {
                    "name": TOOL_NAME,
                    "description": (
                        "Return only URLs that are single-vendor profile pages."
                    ),
                    "input_schema": VendorProfileLinksResult.model_json_schema(),
                },
            ],
            tool_choice={"type": "tool", "name": TOOL_NAME},
        )

        usage = TokenUsage.from_anthropic(getattr(response, "usage", None))
        print(
            f"Haiku tokens — input: {usage.input_tokens}, output: {usage.output_tokens}"
        )
        logger.info(
            "Haiku token usage input=%d output=%d",
            usage.input_tokens,
            usage.output_tokens,
        )
        tool_input = self._extract_tool_input(response)
        parsed = VendorProfileLinksResult.model_validate(tool_input)
        seen: set[str] = set()
        urls: list[str] = []
        for url in parsed.urls:
            cleaned = (url or "").strip()
            if not cleaned or cleaned in seen:
                continue
            seen.add(cleaned)
            urls.append(cleaned)
        logger.info(
            "Haiku kept %d/%d links as vendor profiles", len(urls), len(all_links)
        )
        return urls, usage

    @staticmethod
    def _extract_tool_input(response: object) -> dict:
        content = getattr(response, "content", None) or []
        for block in content:
            if (
                getattr(block, "type", None) == "tool_use"
                and getattr(block, "name", None) == TOOL_NAME
            ):
                tool_input = getattr(block, "input", None)
                if not isinstance(tool_input, dict):
                    raise VendorLinkFilterError("Tool input is not an object")
                return tool_input
        raise VendorLinkFilterError(
            "No submit_vendor_profile_urls tool use in response"
        )
