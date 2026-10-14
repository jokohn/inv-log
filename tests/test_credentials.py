import json

import pytest

from app.sheets import Problem, load_service_account_credentials
from app.sheets import connection_error
from types import SimpleNamespace


@pytest.mark.parametrize("kind", ["installed", "web"])
def test_oauth_file_explains_service_account_requirement(tmp_path, kind):
    path = tmp_path / "oauth.json"
    path.write_text(json.dumps({kind: {"client_secret": "must-not-be-displayed"}}))
    with pytest.raises(Problem, match="OAuth client configuration") as exc:
        load_service_account_credentials(path)
    assert "must-not-be-displayed" not in str(exc.value)


@pytest.mark.parametrize("contents", ['not json', '[]', '{}', '{"type":"service_account"}'])
def test_invalid_credential_file_is_actionable(tmp_path, contents):
    path = tmp_path / "invalid.json"
    path.write_text(contents)
    with pytest.raises(Problem, match="service-account"):
        load_service_account_credentials(path)


def test_missing_credential_file(tmp_path):
    with pytest.raises(Problem, match="readable"):
        load_service_account_credentials(tmp_path / "absent.json")


def test_permission_error_suggests_sharing_without_raw_provider_data():
    error = Exception("secret provider detail")
    error.resp = SimpleNamespace(status=403)
    error.content = b'{"error":{"message":"The caller does not have permission"}}'
    assert "client_email as Editor" in connection_error(error)
    assert "secret provider detail" not in connection_error(error)


def test_disabled_api_is_distinguished_from_sheet_permissions():
    error = Exception()
    error.resp = SimpleNamespace(status=403)
    error.content = b'{"error":{"details":[{"reason":"SERVICE_DISABLED"}]}}'
    assert "API is disabled" in connection_error(error)
