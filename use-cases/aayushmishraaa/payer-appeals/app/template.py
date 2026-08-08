"""The appeal letter template, and the instruction that fills it.

The template is a real document with real structure, uploaded as the starting point rather
than asked for from the model. That matters for two reasons: appeal letters have a house
format that a compliance team has already signed off, and starting from a document means the
model performs *targeted edits on named sections* — which is the thing SuperDocs is good at —
instead of generating prose from nothing, which is the thing everything is good at.

The instruction is where the honesty rules live. They are written as constraints on what the
letter may assert, not as style guidance, because the failure that matters here is a letter
that reads beautifully and states something nobody documented.
"""

from __future__ import annotations

from .grounding import Relevance, RelevanceCheck


def appeal_template_html(
    *,
    patient_name: str,
    member_id: str,
    claim_id: str,
    payer_name: str,
    provider_name: str,
) -> str:
    """The house appeal-letter format, as a document to be edited."""
    return f"""
<h1>Appeal of Claim Determination</h1>

<p><strong>To:</strong> {payer_name}, Appeals Unit</p>
<p><strong>From:</strong> {provider_name}</p>
<p><strong>Re:</strong> Claim {claim_id} — {patient_name}, Member ID {member_id}</p>

<h2>Basis of this appeal</h2>
<p>[The ground on which the claim was denied, stated back to the payer in their own terms.]</p>

<h2>Why the determination should be reconsidered</h2>
<p>[The specific documented clinical fact that answers that ground, and how it answers it.]</p>

<h2>Supporting documentation</h2>
<p>[What is enclosed, and what is not.]</p>

<h2>Relief requested</h2>
<p>[What the provider is asking the payer to do.]</p>

<p>Respectfully submitted,<br/>{provider_name}</p>
""".strip()


_HONESTY_RULES = """
RULES ABOUT WHAT THIS LETTER MAY ASSERT — these override any instruction to be persuasive:

1. Use ONLY the clinical fact given above. Do not add diagnoses, dates, durations, dosages,
   measurements, test results or treatment history that were not supplied. If a detail would
   strengthen the letter and you were not given it, leave it out and say what is missing.

2. Do not characterise the patient's condition beyond what the supplied fact states.

3. If the enclosed documentation is not listed, write that the enclosures are to be confirmed
   rather than naming documents you have not been told exist.

4. Write in the professional register of a provider appealing to a payer. Persuasive is fine.
   Inventing is not. A payer will verify every specific in this letter, and a clinician will be
   asked to stand behind it.
""".strip()


def build_instruction(
    *, denial_reason: str, clinical_fact: str, relevance: RelevanceCheck
) -> str:
    """The editing instruction sent to SuperDocs."""

    if relevance.verdict is Relevance.ADDRESSES:
        pairing = (
            "The clinical fact directly answers the stated ground for denial. Make that "
            "connection explicit: name the ground, then show precisely how the fact answers it."
        )
    elif relevance.verdict is Relevance.PARTIAL:
        pairing = (
            "It is unclear whether the clinical fact answers the stated ground. State the "
            "ground, state the fact, and describe the connection ONLY as far as the fact "
            "actually supports it. Do not overstate it."
        )
    else:
        # The dangerous case, handled explicitly. The letter is still drafted — refusing would
        # push the user to write it by hand with no warning at all — but it is drafted honestly,
        # and it tells the payer what is missing rather than manufacturing a rebuttal.
        pairing = (
            "IMPORTANT: the clinical fact supplied does NOT appear to answer the stated ground "
            "for denial. Do not invent a connection between them. Write the letter so that it: "
            "(a) states the ground for denial accurately; (b) states the clinical fact "
            "accurately as supporting background; and (c) says plainly, in the 'Supporting "
            "documentation' section, that documentation directly addressing this ground is "
            "still required and is not enclosed. A letter that admits a gap is useful. A letter "
            "that papers over one is a false statement to an insurer."
        )

    return f"""
Fill in this appeal letter template, editing each bracketed placeholder section in place.

GROUND FOR DENIAL (as stated by the payer):
{denial_reason}

CLINICAL FACT OFFERED IN REBUTTAL (the only clinical information you have):
{clinical_fact}

RELEVANCE ASSESSMENT: {relevance.reason}

HOW TO PAIR THEM:
{pairing}

{_HONESTY_RULES}

Replace every bracketed placeholder. Keep the headings and the overall structure exactly as
they are — this is an approved house format.
""".strip()
