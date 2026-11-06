"""Types the template contract knows about but v1 doesn't build. Templates that use them are refused, so the GUI builder
can list them later without a schema change."""
from __future__ import annotations

from .base import StepType


class _NotYet(StepType):
    implemented = False

    def validate_config(self, config):
        return [f"The '{self.type}' step type is defined but isn't available yet."]

    def validate_response(self, config, data):
        return {}, [f"The '{self.type}' step type isn't available yet."]


class CredentialShare(_NotYet):
    type = "credential_share"


class InfoVideo(_NotYet):
    type = "info_video"


class PaymentLink(_NotYet):
    type = "payment_link"
