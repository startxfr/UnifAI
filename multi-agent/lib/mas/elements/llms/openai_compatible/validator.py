"""
Validator for OpenAI-compatible LLM — checks API connectivity and model availability.
"""

import socket
import ssl
from typing import List
from urllib.parse import urlsplit

import httpx
from openai import (
    OpenAI,
    AuthenticationError,
    PermissionDeniedError,
    BadRequestError,
    NotFoundError,
    RateLimitError,
    APITimeoutError,
    APIConnectionError,
    APIStatusError,
)

from mas.elements.common.validator import (
    BaseElementValidator,
    ValidatorReport,
    ValidationContext,
    ValidationMessage,
    ValidationCode,
)
from mas.elements.llms.openai_compatible.config import OpenAICompatibleConfig


class OpenAICompatibleLLMValidator(BaseElementValidator):
    """
    Validates OpenAI-compatible LLM configuration.

    Checks:
    - API endpoint reachability
    - API key validity (where applicable)
    - Model availability
    """

    def _validate_via_completion(
        self,
        client: OpenAI,
        model_name: str,
    ) -> None:
        """
        Validate model by making a minimal completion request.

        Used for OpenAI-compatible APIs that don't implement /v1/models/{id}.
        Raises appropriate OpenAI exceptions on failure.
        """
        client.completions.create(
            model=model_name,
            prompt="test",
            max_tokens=1,
        )

    def validate(
        self,
        config: OpenAICompatibleConfig,
        context: ValidationContext,
    ) -> ValidatorReport:
        messages: List[ValidationMessage] = []

        if config.forward_user_token:
            # The credential is the acting user's token, which only exists at
            # run time: probing the model with the static api_key would only
            # test a key that is never sent. Check reachability instead.
            return self._validate_forwarded(config, context)

        try:
            with httpx.Client(
                verify=config.verify_ssl,
                timeout=context.timeout_seconds,
            ) as http_client:
                client = OpenAI(
                    base_url=str(config.base_url),
                    api_key=config.api_key,
                    timeout=context.timeout_seconds,
                    http_client=http_client,
                )

                try:
                    client.models.retrieve(config.model_name)
                except NotFoundError:
                    # Many OpenAI-compatible APIs don't implement /v1/models/{id}
                    # Fall back to a minimal completion request
                    self._validate_via_completion(client, config.model_name)

                messages.append(self._info(
                    "MODEL_AVAILABLE",
                    f"Successfully connected and found model '{config.model_name}'",
                    field="model_name",
                ))

        except (AuthenticationError, PermissionDeniedError):
            messages.append(self._error(
                ValidationCode.INVALID_CREDENTIALS.value,
                "Authentication failed - check API key",
                field="api_key",
            ))
        except BadRequestError:
            messages.append(self._error(
                ValidationCode.INVALID_CREDENTIALS.value,
                "Bad request - check API key and configuration",
                field="api_key",
            ))
        except NotFoundError:
            messages.append(self._error(
                "MODEL_NOT_FOUND",
                f"Model '{config.model_name}' not found",
                field="model_name",
            ))
        except RateLimitError:
            messages.append(self._error(
                "RATE_LIMITED",
                "Rate limit exceeded",
                field="base_url",
            ))
        except APITimeoutError:
            messages.append(self._error(
                ValidationCode.NETWORK_TIMEOUT.value,
                f"Connection timed out after {context.timeout_seconds}s",
                field="base_url",
            ))
        except APIConnectionError:
            messages.append(self._error(
                ValidationCode.ENDPOINT_UNREACHABLE.value,
                "Cannot connect to API endpoint",
                field="base_url",
            ))
        except APIStatusError as e:
            messages.append(self._error(
                ValidationCode.NETWORK_ERROR.value,
                f"API error (HTTP {e.status_code})",
                field="base_url",
            ))

        return self._build_report(messages=messages)

    @staticmethod
    def _connect(base_url: str, verify_ssl: bool, timeout: float) -> None:
        """Open (and close) a connection to the endpoint's host and port, TLS included for https."""
        parts = urlsplit(base_url)
        https = parts.scheme == "https"
        host, port = parts.hostname, parts.port or (443 if https else 80)
        with socket.create_connection((host, port), timeout=timeout) as raw:
            if https:
                ctx = ssl.create_default_context()
                if not verify_ssl:
                    ctx.check_hostname = False
                    ctx.verify_mode = ssl.CERT_NONE
                with ctx.wrap_socket(raw, server_hostname=host):
                    pass

    def _validate_forwarded(
        self,
        config: OpenAICompatibleConfig,
        context: ValidationContext,
    ) -> ValidatorReport:
        """Reachability-only check for an LLM that forwards the user's token.

        The endpoint is only connected to (TCP, and the TLS handshake for https), never sent a request: a request
        without a token is a 401 in the gateway's logs on every reconcile. Only a connection failure or a timeout
        is an error.
        """
        messages: List[ValidationMessage] = []
        try:
            self._connect(str(config.base_url), config.verify_ssl, context.timeout_seconds)
            messages.append(self._info(
                "MODEL_CHECK_SKIPPED",
                "Endpoint reachable; the model is not probed because requests "
                "carry the acting user's token, which only exists at run time",
                field="model_name",
            ))
        except (socket.timeout, TimeoutError):
            messages.append(self._error(
                ValidationCode.NETWORK_TIMEOUT.value,
                f"Connection timed out after {context.timeout_seconds}s",
                field="base_url",
            ))
        except (OSError, ssl.SSLError):
            messages.append(self._error(
                ValidationCode.ENDPOINT_UNREACHABLE.value,
                "Cannot connect to API endpoint",
                field="base_url",
            ))
        return self._build_report(messages=messages)
