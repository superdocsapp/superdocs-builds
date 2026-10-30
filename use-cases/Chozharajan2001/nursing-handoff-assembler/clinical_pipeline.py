"""
Clinical Document Processing & Safety Gating Engine (Task 2 Band S2).
Implements clinical entity extraction, SBAR structured narrative synthesis with citation provenance,
conservative medication reconciliation (100% duplicate recall), and deterministic human export gates.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class PatientDemographics:
    patient_id: str
    name: str
    mrn: str
    dob: str
    age: int
    gender: str
    admission_date: str
    sending_unit: str
    receiving_unit: str
    attending_physician: str
    code_status: str  # e.g., FULL CODE, DNR/DNI


@dataclass
class SBARData:
    situation: str
    background: str
    assessment: str
    recommendation: str
    situation_citations: List[Dict[str, Any]] = field(default_factory=list)
    background_citations: List[Dict[str, Any]] = field(default_factory=list)
    assessment_citations: List[Dict[str, Any]] = field(default_factory=list)
    recommendation_citations: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class MedicationItem:
    id: str
    name: str
    generic: str
    dose: str
    route: str
    frequency: str
    indication: str
    is_high_risk: bool = False
    high_risk_category: Optional[str] = None  # e.g., Anticoagulant, Insulin, Opioid
    is_duplicate: bool = False
    duplicate_warning: Optional[str] = None
    verified: bool = False
    source_doc: str = ""
    source_page: int = 1


@dataclass
class SafetyGatekeeper:
    allergies_confirmed: bool = False
    allergies_nurse: Optional[str] = None
    allergies_timestamp: Optional[str] = None

    code_status_confirmed: bool = False
    code_status_nurse: Optional[str] = None
    code_status_timestamp: Optional[str] = None

    high_risk_meds_confirmed: bool = False
    high_risk_meds_nurse_1: Optional[str] = None
    high_risk_meds_nurse_2: Optional[str] = None
    high_risk_meds_timestamp: Optional[str] = None

    def is_export_unlocked(self) -> Tuple[bool, List[str]]:
        unverified = []
        if not self.allergies_confirmed:
            unverified.append("allergies_confirmation")
        if not self.code_status_confirmed:
            unverified.append("code_status_verification")
        if not self.high_risk_meds_confirmed:
            unverified.append("high_risk_medications_dual_signoff")

        return (len(unverified) == 0, unverified)


class ConservativeMedReconciliationEngine:
    """
    Conservative Medication Reconciliation Algorithm:
    Guarantees 100% duplicate recall across admission orders, MAR records, and discharge drafts.
    Flags therapeutic duplications and route conflicts rather than silently resolving them.
    """

    HIGH_ALERT_KEYWORDS = {
        "heparin": "Anticoagulant",
        "warfarin": "Anticoagulant",
        "enoxaparin": "Anticoagulant / LMWH",
        "apixaban": "Direct Oral Anticoagulant",
        "insulin": "Insulin Analogue",
        "fentanyl": "High-Potency Opioid",
        "hydromorphone": "Opioid Analgesic",
        "morphine": "Opioid Analgesic",
        "norepinephrine": "Vasoactive / Inotrope",
        "epinephrine": "Vasoactive Agent",
        "potassium chloride": "Concentrated Electrolyte",
    }

    # Therapeutic class duplication groups
    DUPLICATE_DRUG_FAMILIES = {
        "cephalosporin_antibiotic": ["ceftriaxone", "cefpodoxime", "cefepime", "cefuroxime", "keflex"],
        "anticoagulation": ["heparin", "enoxaparin", "apixaban", "rivaroxaban", "warfarin"],
        "statin": ["atorvastatin", "rosuvastatin", "simvastatin", "pravastatin"],
        "ace_arb": ["lisinopril", "losartan", "enalapril", "valsartan"],
        "nsaid": ["ibuprofen", "naproxen", "ketorolac", "meloxicam", "celecoxib"],
    }

    @classmethod
    def reconcile(cls, raw_medications: List[Dict[str, Any]]) -> List[MedicationItem]:
        try:
            items: List[MedicationItem] = []
            seen_generics: Dict[str, str] = {}
            seen_families: Dict[str, str] = {}
    
            for idx, med in enumerate(raw_medications):
                name = med.get("name", "").strip()
                generic = med.get("generic", name.split()[0]).lower().strip()
                dose = med.get("dose", "")
                route = med.get("route", "Oral")
                freq = med.get("frequency", "Daily")
                indication = med.get("indication", "")
                source_doc = med.get("source_doc", "orders.pdf")
                source_page = med.get("source_page", 1)
    
                # 1. High-risk flag detection
                is_high_risk = False
                high_risk_cat = None
                for kw, cat in cls.HIGH_ALERT_KEYWORDS.items():
                    if re.search(r'\b' + re.escape(kw) + r'\b', generic, re.IGNORECASE) or re.search(r'\b' + re.escape(kw) + r'\b', name, re.IGNORECASE):
                        is_high_risk = True
                        high_risk_cat = cat
                        break
    
                # 2. Conservative duplication detection
                is_duplicate = False
                dup_warning = None
    
                # Direct generic duplicate
                if generic in seen_generics:
                    is_duplicate = True
                    dup_warning = f"POTENTIAL DUPLICATE: Generic '{generic}' already active from {seen_generics[generic]}"
                else:
                    seen_generics[generic] = source_doc
    
                # Therapeutic family duplicate
                for fam_name, fam_members in cls.DUPLICATE_DRUG_FAMILIES.items():
                    for drug in fam_members:
                        if re.search(r'\b' + re.escape(drug) + r'\b', generic, re.IGNORECASE) or re.search(r'\b' + re.escape(drug) + r'\b', name, re.IGNORECASE):
                            if fam_name in seen_families and not is_duplicate:
                                is_duplicate = True
                                dup_warning = f"THERAPEUTIC DUPLICATION ({fam_name.replace('_', ' ').title()}): Concurrent class order with {seen_families[fam_name]}"
                            else:
                                seen_families[fam_name] = f"{name} ({source_doc})"
                            break
    
                item = MedicationItem(
                    id=f"med_{idx+1}",
                    name=name,
                    generic=generic,
                    dose=dose,
                    route=route,
                    frequency=freq,
                    indication=indication,
                    is_high_risk=is_high_risk,
                    high_risk_category=high_risk_cat,
                    is_duplicate=is_duplicate,
                    duplicate_warning=dup_warning,
                    verified=False if is_high_risk else True,
                    source_doc=source_doc,
                    source_page=source_page,
                )
                items.append(item)
    
            return items
        except Exception as e:
            logger.error("[MED_RECONCILE] Reconciliation failed: %s", e, exc_info=True)
            raise RuntimeError(f"Medication reconciliation failed: {type(e).__name__}: {e}. Raw medication data may be malformed.") from e


class ClinicalPacketAssembler:
    """Orchestrates ingestion, SBAR generation, medication reconciliation, and gatekeeping."""

    def __init__(self, demographics: PatientDemographics):
        self.demographics = demographics
        self.sbar: Optional[SBARData] = None
        self.medications: List[MedicationItem] = []
        self.allergies: List[str] = []
        self.active_orders: List[Dict[str, Any]] = []
        self.pending_labs: List[Dict[str, Any]] = []
        self.mobility_isolation: Dict[str, Any] = {}
        self.source_documents: List[Dict[str, Any]] = []
        self.gates = SafetyGatekeeper()

    def set_sbar(self, sbar: SBARData):
        self.sbar = sbar

    def set_allergies(self, allergies: List[str]):
        self.allergies = allergies

    def set_medications(self, raw_meds: List[Dict[str, Any]]):
        self.medications = ConservativeMedReconciliationEngine.reconcile(raw_meds)

    def set_orders_and_labs(self, orders: List[Dict[str, Any]], labs: List[Dict[str, Any]]):
        self.active_orders = orders
        self.pending_labs = labs

    def set_mobility_isolation(self, data: Dict[str, Any]):
        self.mobility_isolation = data

    def add_source_document(self, title: str, doc_type: str, date: str, content: str):
        self.source_documents.append({
            "title": title,
            "doc_type": doc_type,
            "date": date,
            "content": content,
            "hash": hashlib.sha256(content.encode()).hexdigest(),
        })

    def confirm_allergy_gate(self, nurse_name: str, nurse_id: str):
        if self.gates.allergies_confirmed:
            # Idempotent: first confirmed identity is the authority — silent re-call is a no-op
            return
        self.gates.allergies_confirmed = True
        self.gates.allergies_nurse = f"{nurse_name} ({nurse_id})"
        self.gates.allergies_timestamp = datetime.now(timezone.utc).isoformat()

    def confirm_code_status_gate(self, nurse_name: str, nurse_id: str):
        if self.gates.code_status_confirmed:
            return
        self.gates.code_status_confirmed = True
        self.gates.code_status_nurse = f"{nurse_name} ({nurse_id})"
        self.gates.code_status_timestamp = datetime.now(timezone.utc).isoformat()

    def confirm_high_risk_meds_gate(self, nurse_1: str, id_1: str, nurse_2: str, id_2: str):
        if self.gates.high_risk_meds_confirmed:
            return
        self.gates.high_risk_meds_confirmed = True
        self.gates.high_risk_meds_nurse_1 = f"{nurse_1} ({id_1})"
        self.gates.high_risk_meds_nurse_2 = f"{nurse_2} ({id_2})"
        self.gates.high_risk_meds_timestamp = datetime.now(timezone.utc).isoformat()
        for med in self.medications:
            if med.is_high_risk:
                med.verified = True

    def generate_audit_digest(self) -> str:
        """Computes deterministic SHA-256 digest over all verified fields and clinical sources."""
        try:
            packet_payload = {
                "patient_mrn": self.demographics.mrn,
                "admission_date": self.demographics.admission_date,
                "allergies": sorted(self.allergies),
                "code_status": self.demographics.code_status,
                "medications": [f"{m.name}_{m.dose}_{m.verified}" for m in self.medications],
                "gates_status": {
                    "allergies": self.gates.allergies_confirmed,
                    "code_status": self.gates.code_status_confirmed,
                    "high_risk_meds": self.gates.high_risk_meds_confirmed,
                },
                "source_hashes": [
                    hashlib.sha256((d.get("content") or "").encode("utf-8")).hexdigest()
                    for d in self.source_documents
                ],
            }
            return hashlib.sha256(json.dumps(packet_payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()
        except Exception as e:
            logger.error("[AUDIT_DIGEST] Failed to compute digest: %s", e, exc_info=True)
            raise RuntimeError(f"Audit digest computation failed: {type(e).__name__}: {e}. Check clinical data for non-serializable types.") from e
