"""
E-sign handoff. SuperDocs' job ends at producing the finished, formatted document -- this module is
DELIBERATELY the only place that ever talks to DocuSign, and it's never confused with SuperDocs' own
surface. `EsignProvider` is the interface; `DocuSignMCPClient` is a REAL client against DocuSign's own
published MCP server (confirmed via their developer docs: production `https://mcp.docusign.com/mcp`,
sandbox `https://mcp-d.docusign.com/mcp`); `FakeEsignProvider` is the test double.
"""
from __future__ import annotations

import abc
import os
from dataclasses import dataclass
from typing import Optional


@dataclass
class EnvelopeResult:
    envelope_id: str
    status: str  # "sent" | "created" | ...
    provider: str  # "docusign" -- makes it explicit in logs/tests which provider actually handled this


class EsignProvider(abc.ABC):
    @abc.abstractmethod
    def send_for_signature(self, pdf_bytes: bytes, signer_name: str, signer_email: str, subject: str) -> EnvelopeResult:
        ...


class DocuSignMCPClient(EsignProvider):
    """Real client against DocuSign's own MCP server. Requires a DocuSign developer account and an access
    token (see README's 'what's honestly a gap' -- full OAuth flow is not implemented here, a pre-obtained
    token is read from env instead, a deliberate and logged scope cut).

    SANDBOX_URL is DocuSign's own documented free developer sandbox -- confirmed via their developer docs,
    not invented. Envelopes created here are marked non-binding test envelopes by DocuSign itself.
    """

    SANDBOX_URL = "https://mcp-d.docusign.com/mcp"
    PRODUCTION_URL = "https://mcp.docusign.com/mcp"

    def __init__(self, access_token: Optional[str] = None, account_id: Optional[str] = None, use_sandbox: bool = True):
        self.access_token = access_token or os.getenv("DOCUSIGN_ACCESS_TOKEN")
        self.account_id = account_id or os.getenv("DOCUSIGN_ACCOUNT_ID")
        self.base_url = self.SANDBOX_URL if use_sandbox else self.PRODUCTION_URL
        if not self.access_token or not self.account_id:
            raise ValueError(
                "DOCUSIGN_ACCESS_TOKEN and DOCUSIGN_ACCOUNT_ID must be set. Create a free DocuSign "
                "developer account at developers.docusign.com, complete the OAuth flow to get an access "
                "token, and find your account id on the Apps and Keys page."
            )

    def send_for_signature(self, pdf_bytes: bytes, signer_name: str, signer_email: str, subject: str) -> EnvelopeResult:
        # Real MCP client connection over streamable HTTP, calling DocuSign's own envelope-creation tool.
        # Imported lazily so this class can be instantiated and its error-handling tested without the `mcp`
        # client package needing to be installed for the rest of the test suite.
        import asyncio
        import base64
        from mcp import ClientSession
        from mcp.client.streamable_http import streamablehttp_client

        async def _send():
            headers = {"Authorization": f"Bearer {self.access_token}"}
            async with streamablehttp_client(self.base_url, headers=headers) as (read, write, _):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.call_tool("create_envelope", {
                        "accountId": self.account_id,
                        "emailSubject": subject,
                        "documents": [{
                            "documentBase64": base64.b64encode(pdf_bytes).decode("ascii"),
                            "name": "Proposal.pdf",
                            "fileExtension": "pdf",
                            "documentId": "1",
                        }],
                        "recipients": {"signers": [{
                            "email": signer_email, "name": signer_name,
                            "recipientId": "1", "routingOrder": "1",
                        }]},
                        "status": "sent",
                    })
                    return result

        result = asyncio.run(_send())
        envelope_id = result.content[0].text if result.content else "unknown"
        return EnvelopeResult(envelope_id=envelope_id, status="sent", provider="docusign")


class FakeEsignProvider(EsignProvider):
    """Test double -- records what it was asked to send without any network call, so the pipeline's
    approval-gating logic (never send without approval) can be tested with zero credentials."""

    def __init__(self):
        self.sent_envelopes: list[dict] = []

    def send_for_signature(self, pdf_bytes: bytes, signer_name: str, signer_email: str, subject: str) -> EnvelopeResult:
        envelope_id = f"fake-envelope-{len(self.sent_envelopes) + 1}"
        self.sent_envelopes.append({
            "envelope_id": envelope_id, "signer_name": signer_name, "signer_email": signer_email,
            "subject": subject, "pdf_size_bytes": len(pdf_bytes),
        })
        return EnvelopeResult(envelope_id=envelope_id, status="sent", provider="docusign-fake")
