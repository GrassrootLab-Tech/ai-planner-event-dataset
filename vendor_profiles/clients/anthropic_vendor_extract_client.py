from __future__ import annotations

from typing import Any

import json_repair
from anthropic import AsyncAnthropic
from pydantic import ValidationError

from utils.logger import log_pretty, logger
from utils.pipeline_cost import TokenUsage
from vendor_profiles.models.vendor_profile import VendorProfile
from vendor_profiles.prompts.vendor_profile_extract import SYSTEM_PROMPT

TOOL_NAME = "submit_vendor_profile"
MAX_TOKENS = 8_192
_VALIDATE_STRIP_ATTEMPTS = 8

_EMPTY_STRINGS = {"", "null", "none", "n/a", "na", "undefined"}


class VendorExtractError(Exception):
    pass


class AnthropicVendorExtractClient:
    def __init__(self, client: AsyncAnthropic, model: str) -> None:
        self._client = client
        self._model = model

    @property
    def model(self) -> str:
        return self._model

    async def extract_profile(
        self,
        *,
        page_url: str,
        markdown: str,
    ) -> tuple[VendorProfile, TokenUsage]:
        user_content = (
            f"page_url: {page_url}\n\n"
            "markdown:\n"
            f"{markdown}"
        )

        log_pretty(
            "Extracting vendor profile",
            {
                "model": self._model,
                "page_url": page_url,
                "markdown_chars": len(markdown),
            },
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
                        "Submit the structured vendor profile extracted from "
                        "the page markdown. Omit unknown fields."
                    ),
                    "input_schema": VendorProfile.model_json_schema(),
                },
            ],
            tool_choice={"type": "tool", "name": TOOL_NAME},
        )

        usage = TokenUsage.from_anthropic(getattr(response, "usage", None))
        print(
            f"Haiku tokens — input: {usage.input_tokens}, "
            f"output: {usage.output_tokens}"
        )
        logger.info(
            "Haiku token usage input=%d output=%d",
            usage.input_tokens,
            usage.output_tokens,
        )
        tool_input = self._extract_tool_input(response)
        normalized = self.normalize_tool_input(tool_input)
        profile = self.validate_profile(normalized)
        return profile, usage

    @staticmethod
    def _extract_tool_input(response: object) -> dict | str:
        content = getattr(response, "content", None) or []
        for block in content:
            if (
                getattr(block, "type", None) == "tool_use"
                and getattr(block, "name", None) == TOOL_NAME
            ):
                tool_input = getattr(block, "input", None)
                if isinstance(tool_input, (dict, str)):
                    return tool_input
                raise VendorExtractError("Tool input is not an object or string")
        raise VendorExtractError(f"No {TOOL_NAME} tool use in response")

    @classmethod
    def normalize_tool_input(cls, tool_input: dict | str) -> dict:
        """Coerce common malformed tool payloads without changing valid ones."""
        data: Any = tool_input
        if isinstance(data, str):
            data = cls._loads_repaired_json(data)
            if data is None:
                raise VendorExtractError(
                    "Tool input string could not be parsed as JSON"
                )
        if not isinstance(data, dict):
            raise VendorExtractError("Tool input is not an object")

        data = cls._repair_nested_json_strings(data)
        data = cls._coerce_empty_to_none(data)
        data = cls._coerce_known_shapes(data)

        business_name = data.get("business_name")
        if isinstance(business_name, str):
            data["business_name"] = business_name.strip()
        return data

    @classmethod
    def validate_profile(cls, data: dict) -> VendorProfile:
        payload: dict[str, Any] = dict(data)
        name = payload.get("business_name")
        if isinstance(name, str):
            payload["business_name"] = name.strip()
        name = payload.get("business_name")
        if not isinstance(name, str) or not name:
            raise VendorExtractError("business_name is required")

        last_exc: ValidationError | None = None
        for attempt in range(_VALIDATE_STRIP_ATTEMPTS):
            try:
                return VendorProfile.model_validate(payload)
            except ValidationError as exc:
                last_exc = exc
                stripped = cls._strip_invalid_optional_fields(payload, exc)
                if not stripped:
                    break
                logger.warning(
                    "VendorProfile validation failed (attempt %d); "
                    "stripped invalid optional fields: %s",
                    attempt + 1,
                    stripped,
                )
        detail = last_exc.errors() if last_exc is not None else []
        raise VendorExtractError(
            f"VendorProfile validation failed after repair: {detail}"
        ) from last_exc

    @staticmethod
    def _loads_repaired_json(raw: str) -> Any | None:
        try:
            return json_repair.loads(raw)
        except Exception:
            return None

    @classmethod
    def _repair_nested_json_strings(cls, value: Any) -> Any:
        if isinstance(value, dict):
            return {
                key: cls._repair_nested_json_strings(item)
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [cls._repair_nested_json_strings(item) for item in value]
        if isinstance(value, str):
            text = value.strip()
            if len(text) >= 2 and text[0] in "[{" and text[-1] in "]}":
                parsed = cls._loads_repaired_json(text)
                if isinstance(parsed, (dict, list)):
                    return cls._repair_nested_json_strings(parsed)
            return value
        return value

    @classmethod
    def _coerce_empty_to_none(cls, value: Any) -> Any:
        if isinstance(value, dict):
            return {
                key: cls._coerce_empty_to_none(item)
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [cls._coerce_empty_to_none(item) for item in value]
        if isinstance(value, str) and value.strip().lower() in _EMPTY_STRINGS:
            return None
        return value

    @classmethod
    def _coerce_known_shapes(cls, data: dict[str, Any]) -> dict[str, Any]:
        """Light in-schema fixes only (tool schema already defines field names)."""
        out = dict(data)

        # Wrap single objects / JSON strings that should be lists
        for list_key in (
            "categories",
            "services_provided",
            "faqs",
            "languages",
            "genres_or_styles",
            "portfolio_files",
            "available_dates",
            "unavailable_dates",
            "setup_requirements",
            "prices",
            "packages",
            "available_addons",
            "mandatory_fees",
            "reviews",
            "verified_badges",
            "awards",
            "similar_vendors",
            "social_media",
            "past_events",
            "upcoming_events",
            "reasons_to_book_me",
            "booking_notes",
            "unions",
            "influences_and_inspiration",
            "team",
        ):
            value = out.get(list_key)
            if isinstance(value, dict):
                out[list_key] = [value]
            elif isinstance(value, str):
                parsed = cls._loads_repaired_json(value)
                if isinstance(parsed, list):
                    out[list_key] = parsed
                elif value.strip():
                    out[list_key] = [value.strip()]

        # portfolio_files: bare URL string items → {type, url}
        portfolio = out.get("portfolio_files")
        if isinstance(portfolio, list):
            coerced_p: list[Any] = []
            for item in portfolio:
                if isinstance(item, str) and item.strip():
                    coerced_p.append({"type": "image", "url": item.strip()})
                elif isinstance(item, dict):
                    coerced_p.append(item)
            out["portfolio_files"] = coerced_p or None

        # reasons_to_book_me: bare string items → highlight object (description only)
        highlights = out.get("reasons_to_book_me")
        if isinstance(highlights, list):
            coerced_h: list[Any] = []
            for item in highlights:
                if isinstance(item, str):
                    text = item.strip()
                    if text:
                        coerced_h.append({"reason_description": text})
                elif isinstance(item, dict):
                    coerced_h.append(item)
            out["reasons_to_book_me"] = coerced_h or None

        for obj_key in (
            "location",
            "service_area",
            "logistic_details",
            "years_in_business",
            "weekly_hours",
            "gig_length",
            "price_range",
        ):
            value = out.get(obj_key)
            if value == [] or value == {}:
                out[obj_key] = None

        return out

    @classmethod
    def _strip_invalid_optional_fields(
        cls,
        payload: dict[str, Any],
        exc: ValidationError,
    ) -> list[str]:
        stripped: list[str] = []
        for err in exc.errors():
            loc = err.get("loc") or ()
            if not loc:
                continue
            # Never drop the only required field
            if loc == ("business_name",) or loc[0] == "business_name":
                continue
            path = ".".join(str(part) for part in loc)
            if cls._unset_path(payload, loc):
                stripped.append(path)
        return stripped

    @classmethod
    def _unset_path(cls, data: Any, loc: tuple[Any, ...]) -> bool:
        if not loc:
            return False
        head, *rest = loc
        if isinstance(data, dict):
            if head not in data:
                return False
            if not rest:
                data.pop(head, None)
                return True
            child = data[head]
            changed = cls._unset_path(child, tuple(rest))
            # Drop emptied containers left behind
            if changed and child in ({}, []):
                data.pop(head, None)
            return changed
        if isinstance(data, list) and isinstance(head, int):
            if head < 0 or head >= len(data):
                return False
            if not rest:
                data.pop(head)
                return True
            return cls._unset_path(data[head], tuple(rest))
        return False
