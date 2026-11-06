"""Who is calling.

Two kinds of caller: a person signed in through Supabase (a JWT signed with the
project's asymmetric signing key, checked against SUPABASE_JWKS_URL, or with the
legacy JWT secret) and a service (a scheduled job) holding one of
SERVICE_TOKENS. With AUTH_DISABLED=1 and APP_ENV=local, everyone is the local
developer. Nothing else gets through, and a missing configuration fails closed.
"""
from __future__ import annotations

import hmac
from dataclasses import dataclass
from functools import lru_cache

import jwt
from fastapi import HTTPException, Request

from .config import Settings

ASYMMETRIC_ALGS = ["ES256", "RS256"]


@dataclass(frozen=True)
class Actor:
    id: str
    label: str  # shown in the activity log
    kind: str  # "user", "service" or "local"


def authenticate(settings: Settings, authorization: str | None) -> Actor:
    if settings.auth_disabled:
        return Actor("local", "local", "local")
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "Sign in required.", headers={"WWW-Authenticate": "Bearer"})
    token = authorization[7:].strip()

    for svc in settings.service_tokens:
        if hmac.compare_digest(token, svc):
            return Actor("service", "service", "service")

    try:
        alg = jwt.get_unverified_header(token).get("alg")
    except jwt.PyJWTError:
        raise HTTPException(401, "Invalid or expired session.", headers={"WWW-Authenticate": "Bearer"}) from None

    # Each key only accepts its own algorithms, so an HS256 token can't be checked against the public key.
    if alg in ASYMMETRIC_ALGS and settings.supabase_jwks_url:
        key, algs = None, ASYMMETRIC_ALGS
    elif alg == "HS256" and settings.supabase_jwt_secret:
        key, algs = settings.supabase_jwt_secret, ["HS256"]
    else:
        raise HTTPException(401, "Invalid credentials.", headers={"WWW-Authenticate": "Bearer"})

    try:
        if key is None:
            key = _jwks_client(settings.supabase_jwks_url).get_signing_key_from_jwt(token).key
        claims = jwt.decode(token, key, algorithms=algs, audience="authenticated", options={"require": ["exp", "sub"]})
    except jwt.PyJWTError:
        raise HTTPException(401, "Invalid or expired session.", headers={"WWW-Authenticate": "Bearer"}) from None
    return Actor(str(claims["sub"]), str(claims.get("email") or claims["sub"]), "user")


@lru_cache(maxsize=4)
def _jwks_client(url: str) -> jwt.PyJWKClient:
    # Keys are fetched once and cached; an unknown kid (key rotation) triggers a refetch.
    return jwt.PyJWKClient(url, cache_keys=True, lifespan=600)


def current_actor(request: Request) -> Actor:
    return authenticate(request.app.state.settings, request.headers.get("Authorization"))
