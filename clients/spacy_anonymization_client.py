import spacy
from spacy.tokens import Doc

from utils.logger import log_pretty, logger
from utils.pipeline_cost import TokenUsage

EXCLUDED_LABELS = {"PERSON", "ORG"}


class SpacyAnonymizationClient:
    def __init__(self, model: str) -> None:
        self._model = model
        self._nlp = spacy.load(model)

    @property
    def model(self) -> str:
        return self._model

    async def anonymize_article(self, chunks: list[str]) -> tuple[list[str], TokenUsage]:
        if not chunks:
            return [], TokenUsage()

        log_pretty(
            "Anonymizing article with spaCy",
            {
                "model": self._model,
                "chunk_count": len(chunks),
            },
        )

        results = [self._anonymize(doc) for doc in self._nlp.pipe(chunks)]
        logger.info("Anonymized %d chunks", len(results))
        return results, TokenUsage()

    @staticmethod
    def _anonymize(doc: Doc) -> str:
        text = doc.text
        out: list[str] = []
        last = 0
        for ent in doc.ents:
            if ent.label_ in EXCLUDED_LABELS:
                continue
            out.append(text[last:ent.start_char])
            out.append(f"[{ent.label_}]")
            last = ent.end_char
        out.append(text[last:])
        return "".join(out)
