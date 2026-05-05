from providers.followupboss.egress import apply_outbound_actions
from providers.followupboss.fub_direct_ops import (
    notes_create,
    notes_list,
    people_create,
    people_get,
    people_set_stage,
    people_update,
    tags_add,
    tags_remove,
    tasks_create,
    trigger_import,
    migration_import_batch,
)
from providers.followupboss.oauth import (
    connection_status,
    disconnect,
    internal_webhook_sync,
    list_registered_webhooks,
    oauth_callback,
    oauth_start,
    refresh,
    resync_webhooks,
)
from providers.followupboss.people_list import list_people_page
from providers.followupboss.qa_http import qa_unit_checks
from providers.followupboss.webhooks import webhook_ingress, webhook_test


class FollowUpBossProvider:
    provider_key = "followupboss"

    def oauth_start(self, request):
        return oauth_start(request)

    def connection_status(self, request):
        return connection_status(request)

    def oauth_callback(self, request):
        return oauth_callback(request)

    def internal_webhook_sync(self, request):
        return internal_webhook_sync(request)

    def refresh(self, request):
        return refresh(request)

    def disconnect(self, request):
        return disconnect(request)

    def resync_webhooks(self, request):
        return resync_webhooks(request)

    def list_webhooks(self, request):
        return list_registered_webhooks(request)

    def webhook_test(self, request):
        return webhook_test(request)

    def qa_unit_checks(self, request):
        return qa_unit_checks(request)

    def webhook_ingress(self, request):
        return webhook_ingress(request)

    def list_people_page(self, request):
        return list_people_page(request)

    def people_get(self, request):
        return people_get(request)

    def people_create(self, request):
        return people_create(request)

    def people_update(self, request):
        return people_update(request)

    def people_set_stage(self, request):
        return people_set_stage(request)

    def tags_add(self, request):
        return tags_add(request)

    def tags_remove(self, request):
        return tags_remove(request)

    def notes_create(self, request):
        return notes_create(request)

    def notes_list(self, request):
        return notes_list(request)

    def tasks_create(self, request):
        return tasks_create(request)

    def trigger_import(self, request):
        return trigger_import(request)

    def migration_import_batch(self, request):
        return migration_import_batch(request)

    def apply_outbound_actions(self, connection_id: str, actions: list[dict]) -> dict:
        return apply_outbound_actions(connection_id, actions)
