from providers.followupboss.provider import FollowUpBossProvider
from providers.glyde.provider import GlydeProvider


PROVIDER_REGISTRY = {
    "followupboss": FollowUpBossProvider(),
    "glyde": GlydeProvider(),
}
