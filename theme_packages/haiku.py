"""Haiku synthesis: 3 theme packages of string ideas from retrieved chunks."""

from __future__ import annotations

from typing import Any

from anthropic import AsyncAnthropic
from pydantic import BaseModel, Field

from theme_packages.constants import (
    IDEAS_PER_PACKAGE_MAX,
    IDEAS_PER_PACKAGE_MIN,
    PACKAGE_COUNT,
)
from utils.logger import log_pretty
from utils.pipeline_cost import TokenUsage

PACKAGES_TOOL = "submit_theme_packages"
MAX_TOKENS = 8192


class ThemePackagesError(Exception):
    pass


class ThemePackage(BaseModel):
    name: str = Field(
        description=(
            "Catchy 2–5 word theme name that is the core vibe of this package "
            "(e.g. 'Birthday Barbeque Bash', 'Garden Glow Soiree')"
        ),
    )
    ideas: list[str] = Field(
        min_length=IDEAS_PER_PACKAGE_MIN,
        max_length=IDEAS_PER_PACKAGE_MAX,
        description=(
            f"{IDEAS_PER_PACKAGE_MIN}-{IDEAS_PER_PACKAGE_MAX} diverse idea strings "
            "(~10-15 words each) covering different event elements, "
            "all aligned to the package name's vibe"
        ),
    )


class ThemePackagesResponse(BaseModel):
    packages: list[ThemePackage] = Field(
        min_length=PACKAGE_COUNT,
        max_length=PACKAGE_COUNT,
        description=f"Exactly {PACKAGE_COUNT} distinct named theme packages",
    )


def _extract_tool_input(response: object, tool_name: str) -> dict[str, Any]:
    content = getattr(response, "content", None) or []
    for block in content:
        if (
            getattr(block, "type", None) == "tool_use"
            and getattr(block, "name", None) == tool_name
        ):
            tool_input = getattr(block, "input", None)
            if not isinstance(tool_input, dict):
                raise ThemePackagesError(
                    f"Anthropic tool_use input is not an object for {tool_name}"
                )
            return tool_input
    raise ThemePackagesError(f"Anthropic returned no {tool_name} tool_use block")


async def synthesize_theme_packages(
    *,
    api_key: str,
    model: str,
    form_summary: str,
    chunk_texts: list[str],
) -> tuple[list[ThemePackage], TokenUsage]:
    client = AsyncAnthropic(api_key=api_key)
    sources = "\n\n".join(
        f"[{i}] {text.strip()}"
        for i, text in enumerate(chunk_texts, start=1)
        if text.strip()
    )
    if not sources:
        sources = "(no retrieved chunks)"

    system = (
        "You design complete theme packages for an event. "
        f"Return exactly {PACKAGE_COUNT} packages. "
        "Each package needs a short catchy theme name (2–5 words) that is the "
        "core vibe — e.g. 'Birthday Barbeque Bash', 'Midnight Masquerade', "
        "'Garden Glow Soiree'. That name is the north star: every idea in the "
        "package must reinforce that vibe. "
        "Each package must feel like a coherent full-picture vision of the event "
        "(vibe, food, desserts, drinks, decor, lighting, entertainment, activities, "
        "personalization elements, gifting, DIY, photo moments — pick a diverse mix). "
        "Make sure all facets of an event are evenly covered in a single package. "
        f"Each package has {IDEAS_PER_PACKAGE_MIN}-{IDEAS_PER_PACKAGE_MAX} idea "
        "strings, each about 10–15 words. "
        "The three packages must be clearly different from each other "
        "(different theme names and vibes). "
        "Within a package, ideas must be diverse — do not repeat the same angle. "
        "Ground ideas in the retrieved SOURCES. "
        "Do not mention sources, chunk numbers, or tags. "
        "Keep your tone and style fun and engaging since you are a party planner. "
    )
    user = (
        f"FORM:\n{form_summary}\n\n"
        f"SOURCES:\n{sources}\n\n"
        f"Return exactly {PACKAGE_COUNT} theme packages. "
        "Each needs a catchy theme name (core vibe) plus "
        f"{IDEAS_PER_PACKAGE_MIN}-{IDEAS_PER_PACKAGE_MAX} diverse idea strings "
        "(~10-15 words) that all fit that theme. All three packages must differ."
    )

    log_pretty(
        "Theme packages synthesis",
        {
            "model": model,
            "package_count": PACKAGE_COUNT,
            "source_count": len(chunk_texts),
        },
    )

    response = await client.messages.create(
        model=model,
        max_tokens=MAX_TOKENS,
        system=system,
        messages=[{"role": "user", "content": user}],
        tools=[
            {
                "name": PACKAGES_TOOL,
                "description": (
                    "Submit exactly three named theme packages "
                    "(each with a theme name + idea strings)."
                ),
                "input_schema": ThemePackagesResponse.model_json_schema(),
            },
        ],
        tool_choice={"type": "tool", "name": PACKAGES_TOOL},
    )

    usage = TokenUsage.from_anthropic(getattr(response, "usage", None))
    log_pretty(
        "Theme packages token usage",
        {
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
        },
    )

    tool_input = _extract_tool_input(response, PACKAGES_TOOL)
    parsed = ThemePackagesResponse.model_validate(tool_input)
    packages: list[ThemePackage] = []
    for pkg in parsed.packages:
        name = pkg.name.strip()
        if not name:
            raise ThemePackagesError("Package is missing a theme name")
        ideas = [idea.strip() for idea in pkg.ideas if idea.strip()]
        if len(ideas) < IDEAS_PER_PACKAGE_MIN:
            raise ThemePackagesError(
                f"Package '{name}' has only {len(ideas)} ideas; need at least "
                f"{IDEAS_PER_PACKAGE_MIN}"
            )
        packages.append(
            ThemePackage(name=name, ideas=ideas[:IDEAS_PER_PACKAGE_MAX])
        )
    if len(packages) < PACKAGE_COUNT:
        raise ThemePackagesError(
            f"Haiku returned {len(packages)} packages; need {PACKAGE_COUNT}"
        )
    return packages[:PACKAGE_COUNT], usage
