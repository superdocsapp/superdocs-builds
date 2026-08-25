from config.credit import CREDIT_ROLES


def build_analyze_messages(request: dict) -> list[dict[str, str]]:
    roles = "\n".join(f"{role_id}: {role['description']}" for role_id, role in CREDIT_ROLES.items())
    return [
        {"role": "system", "content": f'''Return only valid JSON.

Use only the provided author IDs. Map contribution evidence to these CRediT role IDs:
{roles}

Keep exact evidence from the input. Do not guess: "helped with the research" is ambiguous with no role IDs. Funding and conflicts are separate from CRediT roles. funding_acquisition requires explicit evidence that an author secured funding. Empty conflicts means unknown.

Examples: "designed the study" means conceptualization; do not add methodology unless the text specifically describes designing research methods, a protocol, or a model. "built the software" means software. "cleaned the dataset" means data_curation.

Return:
{{
  "contributions": [{{ "authorId": "", "evidence": "", "roleIds": [], "status": "proposed" }}],
  "funding": {{ "status": "reported", "funder": "", "awardNumber": "", "evidence": "" }},
  "conflicts": {{ "status": "none", "items": [] }}
}}'''},
        {"role": "user", "content": __import__("json").dumps(request, separators=(",", ":"), ensure_ascii=False)},
    ]
