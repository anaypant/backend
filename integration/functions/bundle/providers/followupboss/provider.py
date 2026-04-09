from providers.followupboss.egress import apply_outbound_actions
from providers.followupboss.oauth import disconnect, oauth_callback, oauth_start, refresh, resync_webhooks
from providers.followupboss.webhooks import webhook_ingress


class FollowUpBossProvider:
    provider_key = "followupboss"

    def oauth_start(self, request):
        return oauth_start(request)

    def oauth_callback(self, request):
        return oauth_callback(request)

    def refresh(self, request):
        return refresh(request)

    def disconnect(self, request):
        return disconnect(request)

    def resync_webhooks(self, request):
        return resync_webhooks(request)

    def webhook_ingress(self, request):
        return webhook_ingress(request)

    def apply_outbound_actions(self, connection_id: str, actions: list[dict]) -> dict:
        return apply_outbound_actions(connection_id, actions)
