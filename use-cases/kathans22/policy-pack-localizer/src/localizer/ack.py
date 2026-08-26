"""Renders the acknowledgement form from known fields into a known template.

Deterministic, per CLAUDE.md rule 6: known fields (office, country, pack
version, core hash, safeguarding lead) filled into a known template. No
SuperDocs chat call is made to produce the text — spending an operation on
this would be spending money to do arithmetic badly. SuperDocs is still used
to upload and export the finished document, since upload and export never
cost operations.
"""

from __future__ import annotations

from pathlib import Path

from . import config as config_module
from . import corelock
from .ledger import Ledger
from .mcp_client import SuperDocsClient
from .packs import OUT_DIR, _default_downloader, _write_export

# Field labels in each office's working language. Kept as plain data, not a
# translation call: these five labels never vary per country, only by
# language, so there is nothing here that needs a model to decide.
_LABELS = {
    "en": {
        "title": "Acknowledgement of Receipt",
        "office": "Office",
        "country": "Country",
        "pack_version": "Policy pack version",
        "core_hash": "Protected core hash",
        "safeguarding_lead": "Safeguarding lead",
        "recipient_name": "Recipient name",
        "recipient_role": "Recipient role",
        "date": "Date",
        "signature": "Signature",
        "return_address": "Return this form to",
        "statement": (
            "I confirm that I have received and read the Meridian Relief Trust "
            "Safeguarding Policy pack for this office, including its country-specific "
            "annexes, and that the protected core hash above matches the version issued."
        ),
    },
    "fr": {
        "title": "Accusé de réception",
        "office": "Bureau",
        "country": "Pays",
        "pack_version": "Version du dossier de politique",
        "core_hash": "Empreinte du socle protégé",
        "safeguarding_lead": "Référent protection",
        "recipient_name": "Nom du destinataire",
        "recipient_role": "Fonction du destinataire",
        "date": "Date",
        "signature": "Signature",
        "return_address": "Retourner ce formulaire à",
        "statement": (
            "Je confirme avoir reçu et lu le dossier de la politique de protection "
            "Meridian Relief Trust pour ce bureau, y compris ses annexes propres au "
            "pays, et que l'empreinte du socle protégé ci-dessus correspond à la "
            "version publiée."
        ),
    },
    "pt": {
        "title": "Comprovante de Recebimento",
        "office": "Escritório",
        "country": "País",
        "pack_version": "Versão do pacote de política",
        "core_hash": "Hash do núcleo protegido",
        "safeguarding_lead": "Responsável pela proteção",
        "recipient_name": "Nome do destinatário",
        "recipient_role": "Função do destinatário",
        "date": "Data",
        "signature": "Assinatura",
        "return_address": "Devolver este formulário para",
        "statement": (
            "Confirmo que recebi e li o pacote da Política de Proteção da Meridian "
            "Relief Trust para este escritório, incluindo seus anexos específicos do "
            "país, e que o hash do núcleo protegido acima corresponde à versão emitida."
        ),
    },
}

_BLANK = "________________________"


def render_form(country: dict, manifest: dict) -> str:
    """Build the acknowledgement form's markdown text for one country.

    Every field comes from `country` (the country's YAML), `manifest`
    (core_version), or the persisted core lock (core_hash) for that
    country's language — nothing here is generated. `return_address` is
    derived from the country's own office and country name, since no
    country YAML carries a distinct postal address and one would only
    duplicate the office/country fields already present.
    """
    language = country["language"]
    labels = _LABELS.get(language, _LABELS["en"])
    core_version = manifest["core_version"]
    core_hash = corelock.load_lock(core_version, language)["core_hash"]
    return_address = f"{country['office']}, {country['country']}"

    lines = [
        f"## 1 {labels['title']}",
        "",
        labels["statement"],
        "",
        f"- **{labels['office']}:** {country['office']}",
        f"- **{labels['country']}:** {country['country']}",
        f"- **{labels['pack_version']}:** v{core_version}",
        f"- **{labels['core_hash']}:** `{core_hash}`",
        f"- **{labels['safeguarding_lead']}:** {country['safeguarding_lead']}",
        f"- **{labels['recipient_name']}:** {_BLANK}",
        f"- **{labels['recipient_role']}:** {_BLANK}",
        f"- **{labels['date']}:** {_BLANK}",
        f"- **{labels['signature']}:** {_BLANK}",
        "",
        f"{labels['return_address']}: {return_address}",
        "",
    ]
    return "\n".join(lines)


def _content_key(country_code: str, core_version: int) -> str:
    return f"ack:{country_code}:v{core_version}"


_EXPORT_FILES = (("markdown", "acknowledgement.md"), ("docx", "acknowledgement.docx"))


def _files_exist(pack_dir: Path) -> bool:
    return all((pack_dir / filename).exists() for _, filename in _EXPORT_FILES)


async def generate_acknowledgement(
    country_code: str,
    *,
    ledger: Ledger | None = None,
    manifest: dict | None = None,
    country: dict | None = None,
    out_dir: Path = OUT_DIR,
    client_factory=SuperDocsClient,
    downloader=_default_downloader,
) -> dict:
    """Render, upload, and export one country's acknowledgement form.

    Zero operations: the text is built deterministically by `render_form`,
    and upload/export never cost operations. SuperDocs is used only to
    render and export the finished markdown as a styled docx.
    """
    ledger = ledger if ledger is not None else Ledger()
    manifest = manifest if manifest is not None else config_module.load_manifest()
    country = (
        country
        if country is not None
        else config_module.load_country(config_module.COUNTRIES_DIR / f"{country_code}.yaml")
    )

    pack_dir = out_dir / country_code
    content_key = _content_key(country_code, manifest["core_version"])

    if ledger.already_charged(content_key) and _files_exist(pack_dir):
        ledger.record(
            "ack", country_code, chat_calls=0, wall_time=0.0,
            content_key=content_key, output_exists=True,
        )
        return {
            "country_code": country_code,
            "exports": {fmt: pack_dir / filename for fmt, filename in _EXPORT_FILES},
            "skipped": True,
        }

    markdown_text = render_form(country, manifest)
    session_id = f"ack-{country_code.lower()}"

    exports: dict[str, Path] = {}
    async with client_factory() as client:
        await client.upload(
            filename="acknowledgement.md",
            file_base64=_b64(markdown_text),
            session_id=session_id,
        )
        ledger.record("upload", country_code, chat_calls=0, wall_time=0.0)

        exports["markdown"] = await _write_export(
            {"text": markdown_text}, pack_dir / "acknowledgement.md", "markdown"
        )
        docx_response = await client.export(session_id=session_id, format="docx")
        exports["docx"] = await _write_export(
            docx_response, pack_dir / "acknowledgement.docx", "docx", downloader=downloader
        )
        ledger.record("export-docx", country_code, chat_calls=0, wall_time=0.0)

    ledger.record(
        "ack", country_code, chat_calls=0, wall_time=0.0,
        content_key=content_key, output_exists=False,
    )

    return {"country_code": country_code, "exports": exports, "skipped": False}


def _b64(text: str) -> str:
    import base64

    return base64.b64encode(text.encode("utf-8")).decode("ascii")
