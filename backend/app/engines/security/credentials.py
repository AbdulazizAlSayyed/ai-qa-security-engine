"""Turning a stored credential reference into a usable credential.

This is the only place in the platform that reads a credential value, and
it reads it from the process environment - never from MongoDB, which holds
nothing but the variable names.

The boundary is deliberately narrow. :class:`RuntimeCredential` exists for
the moment between "a future phase needs to log in" and "the login has been
attempted", and is built to be hard to leak from:

* ``repr`` and ``str`` are overridden, so it cannot be printed, logged,
  interpolated into a message or shown in a traceback's local variables;
* it is not a pydantic model and has no ``model_dump``, so it cannot be
  serialised into an API response by accident;
* nothing persists it, and no route returns it.

A missing variable is a configuration error with a clear message naming the
variable that is unset. It is never substituted, never guessed, and never
silently skipped - a test that appears to run under an identity it never
actually had is worse than one that refuses to start.

Phase 12 does not log in. This resolver is the configuration boundary the
later phases will call; nothing in the current pipeline invokes it.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol


class CredentialError(Exception):
    """A credential could not be resolved. Safe to show and to log.

    Carries the variable names involved, never a value - the names are what
    the operator has to act on.
    """

    def __init__(self, message: str, *, missing: tuple[str, ...] = ()) -> None:
        super().__init__(message)
        self.message = message
        self.missing = missing


@dataclass(frozen=True)
class RuntimeCredential:
    """A resolved username and password, in memory, briefly.

    ``password`` is a real secret for as long as this object exists. Every
    way of accidentally rendering it has been closed off; the remaining way
    to read it is to ask for ``.password`` explicitly, which is the point.
    """

    username: str
    password: str = field(repr=False)
    #: Where it came from, so a caller can say what it used without saying what it was.
    source: str = ""

    def __repr__(self) -> str:  # pragma: no cover - exercised via tests on str()
        return f"RuntimeCredential(username={self.username!r}, password=<redacted>)"

    def __str__(self) -> str:
        return self.__repr__()

    def __format__(self, _spec: str) -> str:
        return self.__repr__()


class SupportsCredentialReference(Protocol):
    """The shape this resolver needs: the names, and something to call it."""

    name: str
    username: str | None


def _reference_names(reference: Any) -> tuple[str | None, str | None]:
    """Read ``username_env`` / ``password_env`` off a model or a plain dict."""
    if reference is None:
        return None, None
    if isinstance(reference, Mapping):
        return reference.get("username_env"), reference.get("password_env")
    return getattr(reference, "username_env", None), getattr(reference, "password_env", None)


class CredentialResolver:
    """Resolves a test account's credentials from the environment.

    ``environ`` is injectable so tests can exercise it without touching the
    real process environment; it defaults to ``os.environ``.
    """

    def __init__(self, environ: Mapping[str, str] | None = None) -> None:
        self._environ = environ if environ is not None else os.environ

    def _lookup(self, variable: str) -> str | None:
        value = self._environ.get(variable)
        if value is None:
            return None
        value = value.strip()
        return value or None

    def is_resolvable(self, account: Mapping[str, Any] | Any) -> bool:
        """Can :meth:`resolve` succeed right now? No value is returned.

        Used to report configuration state - an operator needs to know
        whether there is still setup to do, which is not the same as being
        shown the secret.
        """
        try:
            self.resolve(account)
        except CredentialError:
            return False
        return True

    def resolve(self, account: Mapping[str, Any] | Any) -> RuntimeCredential:
        """Return the credential for ``account``.

        The username comes from ``credential_reference.username_env`` when
        that is set, and otherwise from the account's own ``username``. The
        password only ever comes from ``credential_reference.password_env``.

        Raises :class:`CredentialError` naming the unset variables. Nothing
        is substituted and nothing is created.
        """
        if isinstance(account, Mapping):
            name = str(account.get("name") or "test account")
            username = account.get("username")
            reference = account.get("credential_reference")
            enabled = account.get("enabled", True)
        else:
            name = str(getattr(account, "name", None) or "test account")
            username = getattr(account, "username", None)
            reference = getattr(account, "credential_reference", None)
            enabled = getattr(account, "enabled", True)

        if not enabled:
            raise CredentialError(
                f"Test account {name!r} is disabled, so its credentials are not "
                "available for use."
            )

        username_env, password_env = _reference_names(reference)

        if not password_env:
            raise CredentialError(
                f"Test account {name!r} has no credential_reference.password_env, so "
                "there is no environment variable to read a password from."
            )

        missing: list[str] = []

        password = self._lookup(password_env)
        if password is None:
            missing.append(password_env)

        if username_env:
            resolved_username = self._lookup(username_env)
            if resolved_username is None:
                missing.append(username_env)
        else:
            resolved_username = username

        if missing:
            raise CredentialError(
                f"Test account {name!r} cannot be resolved: environment "
                f"variable(s) {', '.join(sorted(missing))} are not set on this "
                "machine. Set them in the backend's environment; they are never "
                "stored by the platform.",
                missing=tuple(sorted(missing)),
            )

        if not resolved_username:
            raise CredentialError(
                f"Test account {name!r} has no username, and no username_env to read "
                "one from."
            )

        # password is not None here: `missing` would have been non-empty.
        assert password is not None
        return RuntimeCredential(
            username=resolved_username,
            password=password,
            source=f"env:{password_env}",
        )


__all__ = [
    "CredentialError",
    "CredentialResolver",
    "RuntimeCredential",
]
