Contracts

Purpose of the contracts are to explain the protocols that acs components (internal services) use to communicate with each other. Keeps the environment agnostic towards other components.

- acs_state.v1.json: canonical state envelope passed between integration and core.
- core_run.v1.json: core execution request envelope.
- fub_oauth.v1.json: Follow Up Boss oauth endpoint request/response schema.
- integration_actions.v1.json: provider-agnostic outbound actions envelope.
- integration_webhook_event.v1.json: normalized webhook event envelope for ingest/ledger.
