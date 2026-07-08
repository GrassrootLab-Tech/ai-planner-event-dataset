from tags.definitions import TAGS
from tags.order import METADATA_TAG_ORDER
from tags.spec import TagDefinition, TagSpec


class TagRegistry:
    def __init__(self, tags: dict[str, TagSpec] | None = None) -> None:
        source = tags if tags is not None else TAGS
        self._tags = {
            name: TagDefinition(name=name, **spec.__dict__)
            for name, spec in source.items()
        }

    def get(self, name: str) -> TagDefinition:
        if name not in self._tags:
            raise KeyError(f"Unknown tag: {name}")
        return self._tags[name]

    def get_many(self, names: list[str]) -> list[TagDefinition]:
        return [self.get(name) for name in names]

    def all_tags(self) -> list[TagDefinition]:
        ordered = [self.get(name) for name in METADATA_TAG_ORDER if name in self._tags]
        ordered_names = {tag.name for tag in ordered}
        extras = [tag for name, tag in self._tags.items() if name not in ordered_names]
        return ordered + extras
