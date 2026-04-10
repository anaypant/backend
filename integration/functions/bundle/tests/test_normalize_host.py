from store.gcp_identity import normalize_internal_gateway_hostname


def test_normalize_plain_hostname():
    assert normalize_internal_gateway_hostname("acs-db-internal-abc.uc.gateway.dev") == "acs-db-internal-abc.uc.gateway.dev"


def test_normalize_strips_https_scheme():
    assert (
        normalize_internal_gateway_hostname("https://acs-db-internal-abc.uc.gateway.dev")
        == "acs-db-internal-abc.uc.gateway.dev"
    )


def test_normalize_strips_double_scheme():
    assert (
        normalize_internal_gateway_hostname("https://https://acs-db-internal-abc.uc.gateway.dev")
        == "acs-db-internal-abc.uc.gateway.dev"
    )


def test_normalize_strips_path():
    assert (
        normalize_internal_gateway_hostname("https://acs-db-internal-abc.uc.gateway.dev/db/read")
        == "acs-db-internal-abc.uc.gateway.dev"
    )


def test_normalize_strips_trailing_slash():
    assert normalize_internal_gateway_hostname("acs-db-internal-abc.uc.gateway.dev/") == "acs-db-internal-abc.uc.gateway.dev"
