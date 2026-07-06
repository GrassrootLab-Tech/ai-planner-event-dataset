import importlib


def load_prompt(name: str) -> str:
    module = importlib.import_module(f"prompts.{name}")
    return module.SYSTEM_PROMPT
