"""Temporary certificate download for a future certificate configuration step."""

import os
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Iterator
from urllib.parse import urljoin, urlsplit

import httpx

from app.services.contract_adapter import ContractApiError, ContractUnavailableError


CERTIFICATE_TIMEOUT_SECONDS = int(os.getenv("CERTIFICATE_TIMEOUT_SECONDS", "60"))


@contextmanager
def temporary_certificate_file(
    base_url: str, token: str, file_ref: str,
    *, timeout: int = CERTIFICATE_TIMEOUT_SECONDS,
) -> Iterator[Path]:
    """Download only when needed and delete the file upon leaving this scope."""
    base = urlsplit(base_url)
    url = urljoin(base_url.rstrip("/") + "/", file_ref)
    target = urlsplit(url)
    if (base.scheme not in {"http", "https"} or target.scheme != base.scheme
            or target.netloc != base.netloc or not file_ref):
        raise ContractApiError("Referência do certificado digital inválida.")
    with TemporaryDirectory(prefix="hiper-cert-") as directory:
        path = Path(directory) / "certificado.pfx"
        try:
            with httpx.stream(
                "GET", url, headers={"Authorization": f"Bearer {token}"},
                timeout=timeout,
            ) as response:
                if response.status_code >= 400:
                    raise ContractApiError("Falha ao baixar o certificado digital.")
                with path.open("wb") as output:
                    for chunk in response.iter_bytes():
                        output.write(chunk)
        except httpx.TimeoutException as error:
            raise ContractUnavailableError(
                "O download do certificado digital demorou a responder."
            ) from error
        except httpx.RequestError as error:
            raise ContractUnavailableError(
                "Não foi possível baixar o certificado digital."
            ) from error
        yield path
