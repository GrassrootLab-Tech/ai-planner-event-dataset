from tags.definitions.activities_experience import TAGS as ACTIVITIES_EXPERIENCE_TAGS
from tags.definitions.budget_procurement import TAGS as BUDGET_PROCUREMENT_TAGS
from tags.definitions.content_meta import TAGS as CONTENT_META_TAGS
from tags.definitions.core_event_identity import TAGS as CORE_EVENT_IDENTITY_TAGS
from tags.definitions.culture_context import TAGS as CULTURE_CONTEXT_TAGS
from tags.definitions.decor_styling import TAGS as DECOR_STYLING_TAGS
from tags.definitions.food_drink import TAGS as FOOD_DRINK_TAGS
from tags.definitions.logistics_timing import TAGS as LOGISTICS_TIMING_TAGS
from tags.definitions.theme_aesthetic import TAGS as THEME_AESTHETIC_TAGS

TAGS = {
    **CONTENT_META_TAGS,
    **CORE_EVENT_IDENTITY_TAGS,
    **THEME_AESTHETIC_TAGS,
    **LOGISTICS_TIMING_TAGS,
    **BUDGET_PROCUREMENT_TAGS,
    **FOOD_DRINK_TAGS,
    **ACTIVITIES_EXPERIENCE_TAGS,
    **DECOR_STYLING_TAGS,
    **CULTURE_CONTEXT_TAGS,
}
