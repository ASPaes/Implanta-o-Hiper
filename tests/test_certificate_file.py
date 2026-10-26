from pathlib import Path

import pytest

from app.services.certificate_file import temporary_certificate_file
from app.services.contract_adapter import ContractApiError


def test_certificate_is_downloaded_with_longer_timeout_and_removed(monkeypatch):
    class Response:
        status_code = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def iter_bytes(self):
            yield b"fake-pfx-bytes"

    def fake_stream(method, url, *, headers, timeout):
        assert method == "GET"
        assert url == "https://contratos.example/api/certificados/1"
        assert headers == {"Authorization": "Bearer fake-token"}
        assert timeout == 60
        return Response()

    monkeypatch.setattr("app.services.certificate_file.httpx.stream", fake_stream)
    with temporary_certificate_file(
        "https://contratos.example", "fake-token", "/api/certificados/1"
    ) as path:
        assert path.read_bytes() == b"fake-pfx-bytes"
        downloaded = Path(path)
    assert not downloaded.exists()


def test_certificate_reference_must_stay_on_contract_api_host():
    with pytest.raises(ContractApiError):
        with temporary_certificate_file(
            "https://contratos.example", "fake-token", "https://outside.example/pfx"
        ):
            pass
