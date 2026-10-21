"""Canonical job-architecture catalog and scoring lexicons.

Families, tracks, and levels are organization-agnostic. Scoring never
branches on corpus id, role id, or employer name.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from job_architecture.models import CareerTrack, CareerTrackKind, JobFamily, LevelDefinition

CANONICAL_FAMILY_ID = "canonical"


@dataclass(frozen=True)
class Lexeme:
    pattern: str
    weight: float = 1.0


def compile_lexemes(lexemes: tuple[Lexeme, ...]) -> tuple[tuple[re.Pattern[str], float, str], ...]:
    compiled: list[tuple[re.Pattern[str], float, str]] = []
    for item in lexemes:
        compiled.append((re.compile(item.pattern, re.IGNORECASE), item.weight, item.pattern))
    return tuple(compiled)


JOB_FAMILIES: tuple[JobFamily, ...] = (
    JobFamily(
        id="engineering",
        name="Engineering",
        description="Design, build, test, and operate software and platform systems.",
        typical_domains=["backend", "frontend", "infrastructure", "quality engineering", "sre"],
    ),
    JobFamily(
        id="product",
        name="Product",
        description="Own product outcomes, discovery, and roadmap trade-offs.",
        typical_domains=["product management", "clinical product"],
    ),
    JobFamily(
        id="design",
        name="Design",
        description="Research, interaction design, and design-system authorship.",
        typical_domains=["product design", "design systems"],
    ),
    JobFamily(
        id="data",
        name="Data",
        description="Pipelines, analytic datasets, experimentation, and applied science.",
        typical_domains=["data engineering", "data science", "informatics"],
    ),
    JobFamily(
        id="security",
        name="Security",
        description="Application and product security, threat modeling, and secure SDLC.",
        typical_domains=["application security", "secure sdlc"],
    ),
    JobFamily(
        id="customer_success",
        name="Customer Success",
        description="Post-sale account outcomes: adoption, renewal, and named books of business.",
        typical_domains=["enterprise success", "renewals"],
    ),
    JobFamily(
        id="implementation",
        name="Implementation",
        description="Configure, train, and launch software at customer sites.",
        typical_domains=["professional services", "customer implementation"],
    ),
    JobFamily(
        id="operations",
        name="Operations",
        description="Run operational queues, staffing, and day-to-day delivery floors.",
        typical_domains=["care delivery operations", "operational staffing"],
    ),
    JobFamily(
        id="people",
        name="People",
        description="HR advisory, employee relations, recruiting, and workforce planning.",
        typical_domains=["hrbp", "talent acquisition"],
    ),
    JobFamily(
        id="finance",
        name="Finance",
        description="Planning, forecasting, and variance analysis for the company plan.",
        typical_domains=["fp&a", "financial planning"],
    ),
)

CAREER_TRACKS: tuple[CareerTrack, ...] = (
    CareerTrack(
        id="individual_contributor",
        family_id=CANONICAL_FAMILY_ID,
        kind=CareerTrackKind.INDIVIDUAL_CONTRIBUTOR,
        name="Individual Contributor",
        description="Contribution through craft, not through a reporting chain.",
    ),
    CareerTrack(
        id="people_manager",
        family_id=CANONICAL_FAMILY_ID,
        kind=CareerTrackKind.PEOPLE_MANAGER,
        name="People Manager",
        description="Accountable for hiring, coaching, and performance of direct reports.",
    ),
)

LEVEL_DEFINITIONS: tuple[LevelDefinition, ...] = (
    LevelDefinition(
        id="ic1",
        family_id=CANONICAL_FAMILY_ID,
        track_id="individual_contributor",
        label="IC1",
        rank=1,
        scope="Local ticket or single small tool.",
        autonomy="Follows established patterns; work is assigned.",
        impact="Affects a small local user group.",
        leadership="Little or no mentorship expectation.",
        people_management="No people-management responsibility.",
    ),
    LevelDefinition(
        id="ic2",
        family_id=CANONICAL_FAMILY_ID,
        track_id="individual_contributor",
        label="IC2",
        rank=2,
        scope="Bounded component or named project.",
        autonomy="Chooses implementation details inside existing standards.",
        impact="Squad or single product surface.",
        leadership="May pair or answer questions; does not set direction.",
        people_management="No people-management responsibility.",
    ),
    LevelDefinition(
        id="ic3",
        family_id=CANONICAL_FAMILY_ID,
        track_id="individual_contributor",
        label="IC3",
        rank=3,
        scope="Named service, product area, or book of work.",
        autonomy="Independent within published standards.",
        impact="Multiple consuming teams or a defined customer set.",
        leadership="Mentors through review; may lead short projects.",
        people_management="No people-management responsibility.",
    ),
    LevelDefinition(
        id="ic4",
        family_id=CANONICAL_FAMILY_ID,
        track_id="individual_contributor",
        label="IC4",
        rank=4,
        scope="Cross-team domain with multi-quarter bets.",
        autonomy="Sets sequencing and says no inside the domain.",
        impact="Material business or reliability outcomes beyond one team.",
        leadership="Coaches others and runs a technical or craft agenda.",
        people_management="No people-management responsibility.",
    ),
    LevelDefinition(
        id="ic5",
        family_id=CANONICAL_FAMILY_ID,
        track_id="individual_contributor",
        label="IC5",
        rank=5,
        scope="Company-wide substrate, system, or craft standard.",
        autonomy="Default decision-maker; others require sign-off.",
        impact="Organization-wide; can pause launches or set contracts others follow.",
        leadership="Direction-setting through RFCs, critiques, or mandatory standards.",
        people_management="No people-management responsibility.",
    ),
    LevelDefinition(
        id="m1",
        family_id=CANONICAL_FAMILY_ID,
        track_id="people_manager",
        label="M1",
        rank=1,
        scope="A single team of individual contributors.",
        autonomy="Decides staffing and sequencing for that team; architecture remains shared with a technical lead.",
        impact="Accountable for that team's health, delivery, and performance outcomes.",
        leadership="First-line people leadership: coaching, 1:1s, and team operating cadence.",
        people_management="Hires, coaches, and writes performance reviews for IC direct reports. Does not manage other managers.",
    ),
    LevelDefinition(
        id="m2",
        family_id=CANONICAL_FAMILY_ID,
        track_id="people_manager",
        label="M2",
        rank=2,
        scope="Multiple teams, or a team of managers, within a function.",
        autonomy="Sequences work and staffing across those teams; sets manager goals.",
        impact="Accountable for a multi-team slice of delivery and organizational health.",
        leadership="Develops managers; runs skip-levels; represents the group in planning.",
        people_management="Manages managers or several teams. Owns hiring plans and calibration across that group.",
    ),
    LevelDefinition(
        id="m3",
        family_id=CANONICAL_FAMILY_ID,
        track_id="people_manager",
        label="M3",
        rank=3,
        scope="A function or multi-team organization (for example an entire craft or department).",
        autonomy="Sets people strategy, org shape, and leadership roster for the function.",
        impact="Function-wide talent, culture, and delivery outcomes.",
        leadership="Leads through a management layer; partners with executive peers.",
        people_management="Accountable for managers-of-managers and org-wide people decisions inside the function.",
    ),
)

FAMILY_LEXICONS: dict[str, tuple[Lexeme, ...]] = {
    "engineering": (
        Lexeme(r"\bbackend services?\b", 1.4),
        Lexeme(r"\bbackend apis?\b", 1.1),
        Lexeme(r"\breact\b", 1.2),
        Lexeme(r"\bpull requests?\b", 1.1),
        Lexeme(r"\bon-call\b", 1.3),
        Lexeme(r"\bcodebase\b", 1.0),
        Lexeme(r"\brepository\b", 0.8),
        Lexeme(r"\bphp\b", 1.0),
        Lexeme(r"\bjquery\b", 1.0),
        Lexeme(r"\bjavascript\b", 1.0),
        Lexeme(r"\bcss\b", 0.8),
        Lexeme(r"\bkubernetes\b", 1.2),
        Lexeme(r"\bservice mesh\b", 1.1),
        Lexeme(r"\bci/?cd\b|\bci templates?\b", 1.3),
        Lexeme(r"\bproduction (?:service|debugging|http|payments|scoring)\b", 1.3),
        Lexeme(r"\bapi contracts?\b", 1.1),
        Lexeme(r"\bobservability\b", 1.1),
        Lexeme(r"\btest coverage\b|\bintegration tests?\b", 1.1),
        Lexeme(r"\binfrastructure\b", 1.1),
        Lexeme(r"\bcluster\b", 1.0),
        Lexeme(r"\brunbooks?\b", 1.1),
        Lexeme(r"\berror-budget\b|\bslos?\b", 1.2),
        Lexeme(r"\bincident (?:response|command)\b", 1.1),
        Lexeme(r"\bautomated tests?\b", 1.2),
        Lexeme(r"\btest harness(?:es)?\b|\btest doubles?\b", 1.2),
        Lexeme(r"\bgolden[- ]path\b|\binner-source\b|\bstarter repositories\b", 0.7),
        Lexeme(r"\binterface services\b|\bfhir\b|\behr integration\b", 1.2),
        Lexeme(r"\bwidget (?:package|repository|codebase)\b|\bstatic asset\b", 1.1),
        Lexeme(r"\bimplement and (?:maintain|operate)\b|\boperate backend\b", 1.2),
        Lexeme(r"\bplatform (?:standards|engineering|contracts)\b", 1.0),
        Lexeme(r"\bproof-of-concept\b|\bworking prototype code\b|\bprototype mappings\b", 1.2),
        Lexeme(r"\bintegration patterns\b|\binterface requirements\b", 1.1),
        Lexeme(r"\bstaff (?:ic|engineer)\b|\bworkspace apis?\b", 1.1),
        Lexeme(r"\bweb (?:features|applications)\b", 1.0),
    ),
    "product": (
        Lexeme(r"\broadmap\b", 1.4),
        Lexeme(r"\bproblem briefs?\b", 1.5),
        Lexeme(r"\bacceptance criteria\b", 1.3),
        Lexeme(r"\bproduct (?:surface|area|outcomes?|direction)\b", 1.4),
        Lexeme(r"\bdiscovery\b", 1.2),
        Lexeme(r"\bprioritize\b|\bprioritisation\b|\bprioritization\b", 1.0),
        Lexeme(r"\bbacklog\b", 0.8),
        Lexeme(r"\bquarterly .+ roadmap\b|\bmulti-quarter\b", 1.1),
        Lexeme(r"\bown(?:s|ing)? outcomes\b", 1.2),
        Lexeme(r"\bproduct exception\b", 1.2),
    ),
    "design": (
        Lexeme(r"\bwireframes?\b", 1.5),
        Lexeme(r"\busability (?:sessions?|testing)?\b", 1.3),
        Lexeme(r"\bhigh-fidelity\b|\bdesign rationale\b", 1.3),
        Lexeme(r"\bdesign system\b|\bcomponent library\b|\bdesign tokens?\b", 1.4),
        Lexeme(r"\bproduct design\b|\binteraction design\b", 1.3),
        Lexeme(r"\baccessibility baselines\b|\bcritiques?\b", 1.1),
        Lexeme(r"\bproduce flows\b|\bresearch onboarding\b", 1.2),
    ),
    "data": (
        Lexeme(r"\bwarehouse\b|\bpipelines?\b|\bingestion\b", 1.4),
        Lexeme(r"\bcohort(?:s| definitions)?\b|\bquality measures?\b", 1.4),
        Lexeme(r"\bexperiment(?:s|al design)?\b|\branking and matching models\b", 1.3),
        Lexeme(r"\bdata contracts?\b|\banalytic datasets?\b|\bmarts?\b", 1.3),
        Lexeme(r"\bnotebooks?\b|\bscoring jobs\b|\bapplied statistics\b", 1.2),
        Lexeme(r"\binformatics\b|\bmeasure logic\b|\bgrain\b", 1.2),
        Lexeme(r"\bfeature(?:s)? for (?:analysts|data scientists)\b", 1.0),
    ),
    "security": (
        Lexeme(r"\bthreat-?model\b", 1.5),
        Lexeme(r"\bapplication security\b|\bvulnerabilit(?:y|ies)\b", 1.5),
        Lexeme(r"\bsecure-?sdlc\b|\bsecret detection\b|\bdependency scanning\b", 1.3),
        Lexeme(r"\bexploitabilit(?:y|ies)\b|\bpenetration tests?\b", 1.2),
        Lexeme(r"\bphi\b|\bbreak-glass\b|\brisk acceptance\b", 1.2),
        Lexeme(r"\bsecurity reviews?\b|\bremediate findings\b", 1.3),
    ),
    "customer_success": (
        Lexeme(r"\bnamed (?:enterprise )?accounts?\b|\bbook of (?:named )?enterprise\b|\bbook of business\b", 1.5),
        Lexeme(r"\brenewal(?:s| risk)?\b", 1.4),
        Lexeme(r"\badoption\b|\bsuccess plans?\b", 1.3),
        Lexeme(r"\bquarterly (?:business )?reviews?\b|\bexecutive business reviews?\b", 1.2),
        Lexeme(r"\bcustomer relationships? after sale\b|\bpost-sale\b", 1.2),
        Lexeme(r"\bearly customer success\b|\bcustomer success managers\b", 1.3),
        Lexeme(r"\bthrough onboarding until\b|\binherit the account\b", 1.2),
        Lexeme(r"\bchurn\b|\bexpansion signals?\b", 1.0),
    ),
    "implementation": (
        Lexeme(r"\bgo-live\b", 1.6),
        Lexeme(r"\bhypercare\b", 1.5),
        Lexeme(r"\bimplementation workplans?\b|\bimplementation projects?\b", 1.4),
        Lexeme(r"\bconfigure (?:and launch|site-specific)\b", 1.4),
        Lexeme(r"\bend-user training\b|\btraining schedules?\b|\btraining rooms\b", 1.3),
        Lexeme(r"\bcommand center\b|\bcutover\b", 1.3),
        Lexeme(r"\bhealth-system sites?\b|\bcustomer sites?\b", 1.2),
        Lexeme(r"\bhandover to customer success\b|\bhand a stable site\b", 1.2),
    ),
    "operations": (
        Lexeme(r"\bstaffing grids?\b", 1.5),
        Lexeme(r"\boutreach queues?\b|\bqueue backlogs?\b", 1.4),
        Lexeme(r"\boperations floor\b|\bcare-delivery operations\b", 1.5),
        Lexeme(r"\bshift mix\b|\bweekend coverage\b|\bovertime\b", 1.3),
        Lexeme(r"\boperational metrics\b|\btime-to-outreach\b", 1.2),
        Lexeme(r"\bclinical operations associates\b", 1.3),
    ),
    "people": (
        Lexeme(r"\bemployee-?relations cases\b|\bhandle employee-relations\b", 1.5),
        Lexeme(r"\bworkforce plans?\b|\bworkforce planning\b", 1.4),
        Lexeme(r"\brecruit(?:ing|er|ment)\b|\brequisitions?\b|\bcandidates?\b", 1.3),
        Lexeme(r"\bhr business partner\b|\bpeople programs\b|\btalent acquisition\b", 1.4),
        Lexeme(r"\bcalibration support\b", 1.2),
        Lexeme(r"\bhiring managers\b|\bats\b|\boffer logistics\b", 1.2),
        Lexeme(r"\borg design\b|\bspan of control\b", 1.1),
    ),
    "finance": (
        Lexeme(r"\bvariance (?:versus|vs\.?|against) plan\b|\bforecast updates?\b", 1.5),
        Lexeme(r"\boperating plan\b|\bannual plan\b|\bbottoms-up\b", 1.4),
        Lexeme(r"\bfinancial-?modeling\b|\bfp&a\b", 1.5),
        Lexeme(r"\bbudget holders?\b|\bheadcount cost\b", 1.2),
        Lexeme(r"\bquarterly business review\b", 1.1),
        Lexeme(r"\bplanning, forecasting\b|\bcorporate finance\b", 1.3),
    ),
}

# Unsupported rival: commercial/pre-sales work that is not a catalog family.
SALES_RIVAL_LEXICON: tuple[Lexeme, ...] = (
    Lexeme(r"\bsales cycles?\b", 1.5),
    Lexeme(r"\baccount executives?\b", 1.3),
    Lexeme(r"\bpre-sale\b|\bpre-sales\b", 1.4),
    Lexeme(r"\bproposal\b|\btechnical win\b", 1.1),
    Lexeme(r"\bwin and then land\b|\bcomplex .+ deals\b", 1.3),
)

# Roles that sit outside the supported architecture if they dominate.
OUTSIDE_ARCHITECTURE_LEXICON: tuple[Lexeme, ...] = (
    Lexeme(r"\bscientific exchange\b", 1.6),
    Lexeme(r"\bmedical-?affairs\b", 1.5),
    Lexeme(r"\bcardiologists?\b|\bcardiology\b", 1.3),
    Lexeme(r"\boff-label\b|\bsunshine-act\b|\banti-kickback\b", 1.4),
    Lexeme(r"\bkey opinion leader\b|\b\bkol\b", 1.3),
    Lexeme(r"\binvestigator-initiated\b|\bobservational studies\b", 1.3),
    Lexeme(r"\bconferences? and meetups?\b|\blivestreams?\b", 1.4),
    Lexeme(r"\bpublic discord\b|\bcommunity engagement\b", 1.4),
    Lexeme(r"\bswag copy\b|\bdemo booth\b|\bnewsletter and social\b", 1.4),
    Lexeme(r"\breach, content output\b|\btravel frequently\b", 1.3),
    Lexeme(r"\bexternal developer-community\b|\bdevelopers who do not work\b", 1.4),
    Lexeme(r"\bfield medical\b|\bmedical information\b", 1.3),
)

PEOPLE_MANAGER_POSITIVE: tuple[Lexeme, ...] = (
    Lexeme(r"\bdirect reports\b", 1.6),
    Lexeme(r"\bpeople-management role\b|\bpeople management role\b", 1.8),
    Lexeme(r"\bmanager of record\b", 1.8),
    Lexeme(r"\bperformance reviews?\b|\bperformance ratings?\b", 1.5),
    Lexeme(r"\bhiring, onboarding, and performance\b|\bhire, unassign, coach\b", 1.6),
    Lexeme(r"\bhiring, scheduling, and performance\b|\bhire, coach, discipline\b", 1.6),
    Lexeme(r"\bweekly 1:1s\b|\brun 1:1s\b", 1.4),
    Lexeme(r"\bteam of (?:six|six to eight|six to ten|seven|eight|nine|ten)\b", 1.3),
    Lexeme(r"\bstaffing plans\b|\bstaffing grids\b", 1.1),
)

PEOPLE_MANAGER_NEGATIVE: tuple[Lexeme, ...] = (
    Lexeme(r"\bno direct reports\b", 1.8),
    Lexeme(r"\bdoes not include people management\b", 2.0),
    Lexeme(r"\byou do not hire\b|\bdo not hire\b", 1.4),
    Lexeme(r"\bnot include people management\b", 1.8),
    Lexeme(r"\bthey do not report to you\b|\bnone of those people report\b", 1.5),
    Lexeme(r"\byou do not manage\b|\bdo not manage engineers\b", 1.4),
    Lexeme(r"\bno performance-review ownership\b|\bdo not write their reviews\b", 1.3),
    Lexeme(r"\bpeer-to-peer\b", 1.1),
    Lexeme(r"\bmentorship is not part of the role\b", 1.2),
)

M2_LEXICON: tuple[Lexeme, ...] = (
    Lexeme(r"\bmultiple teams\b", 1.6),
    Lexeme(r"\bseveral teams\b", 1.5),
    Lexeme(r"\bmanages? managers\b|\bmanager of managers\b", 1.8),
    Lexeme(r"\bmanagers as direct reports\b|\bother managers report\b", 1.7),
    Lexeme(r"\bskip-levels?\b", 1.2),
    Lexeme(r"\bacross those teams\b|\bstaffing across\b", 1.3),
)

M3_LEXICON: tuple[Lexeme, ...] = (
    Lexeme(r"\bentire (?:engineering |product |clinical )?organization\b", 1.7),
    Lexeme(r"\bfunction-wide\b|\bfunctional leadership\b", 1.6),
    Lexeme(r"\bmultiple departments\b", 1.5),
    Lexeme(r"\borg-wide people decisions\b", 1.5),
    Lexeme(r"\bmanagers-of-managers\b", 1.6),
    Lexeme(r"\bleadership roster for the function\b", 1.4),
)

SCOPE_HIGH: tuple[Lexeme, ...] = (
    Lexeme(r"\bcompany-wide\b", 1.6),
    Lexeme(r"\bevery (?:engineering team|product that)\b", 1.5),
    Lexeme(r"\bacross all\b|\bentire .+ platform\b", 1.5),
    Lexeme(r"\baffect how every\b|\borg-wide\b|\bmulti-year technical strategy\b", 1.4),
    Lexeme(r"\bclinical cloud substrate\b", 1.3),
)
SCOPE_MID: tuple[Lexeme, ...] = (
    Lexeme(r"\btwo to three services\b|\bnamed (?:accounts|programs|product)\b", 1.2),
    Lexeme(r"\bproduct area\b|\bproduct surfaces?\b|\bbook of\b", 1.1),
    Lexeme(r"\bseveral product lines\b|\bcross-product\b|\bcross-team\b", 1.2),
    Lexeme(r"\bnamed implementation projects\b|\bnamed enterprise\b", 1.1),
)
SCOPE_LOW: tuple[Lexeme, ...] = (
    Lexeme(r"\bone application\b|\bsingle (?:small )?tool\b|\bsingle product surface\b", 1.5),
    Lexeme(r"\bforty people\b|\bone- or two-day ticket\b|\bshort tickets\b", 1.4),
    Lexeme(r"\bsingle patient-portal page\b|\bwidget(?:s)? render\b", 1.5),
    Lexeme(r"\bticket scope is usually days\b|\bthis one application\b", 1.4),
    Lexeme(r"\balready-built internal application\b|\balready-shipped widget\b", 1.3),
)

AUTONOMY_HIGH: tuple[Lexeme, ...] = (
    Lexeme(r"\bdefault decision-maker\b", 1.7),
    Lexeme(r"\bwide latitude\b", 1.5),
    Lexeme(r"\btechnical sign-off\b|\bcan freeze a deploy\b|\bcan block a release\b", 1.5),
    Lexeme(r"\bothers are expected to follow\b|\bmandatory for product ui\b", 1.4),
    Lexeme(r"\byou choose sequencing\b|\byou decide who is on the team\b", 1.3),
)
AUTONOMY_LOW: tuple[Lexeme, ...] = (
    Lexeme(r"\barchitectural choices are already made\b", 1.6),
    Lexeme(r"\bfollow the (?:current|existing)\b|\bwork arrives as short tickets\b", 1.4),
    Lexeme(r"\balready decided by more senior\b|\bexisting checklist\b", 1.4),
    Lexeme(r"\bdo not introduce a new framework\b|\bdo not introduce new services\b", 1.3),
        Lexeme(r"\byou do not set\b|\bdo not set platform architecture\b", 1.5),
)

COMPLEXITY_HIGH: tuple[Lexeme, ...] = (
    Lexeme(r"\bmulti-tenant\b|\bpci\b|\bledger\b|\bfailover\b", 1.4),
    Lexeme(r"\bmulti-year\b|\bsystemic reliability\b|\bcontrol-plane\b", 1.3),
    Lexeme(r"\bthreat-?model\b|\berror budgets?\b|\bregion failover\b", 1.3),
)
COMPLEXITY_LOW: tuple[Lexeme, ...] = (
    Lexeme(r"\bdropdown options\b|\bemail templates\b|\bcopy, colors\b", 1.5),
    Lexeme(r"\brestart the slack\b|\bstaging spreadsheet\b|\blayout bugs\b", 1.4),
    Lexeme(r"\bbasic (?:javascript|html|familiarity)\b", 1.2),
)

IMPACT_HIGH: tuple[Lexeme, ...] = (
    Lexeme(r"\bcompany-wide (?:revenue )?impact\b|\brevenue-critical\b", 1.6),
    Lexeme(r"\bevery engineering team\b|\bpause product asks\b|\bstop a launch\b", 1.4),
    Lexeme(r"\bclinical-critical\b|\bchart access is down\b", 1.4),
    Lexeme(r"\bacross every .+\b|\bui across every\b", 1.3),
)
IMPACT_LOW: tuple[Lexeme, ...] = (
    Lexeme(r"\bforty people\b|\bfacilities group\b|\boffice operations\b", 1.4),
    Lexeme(r"\bnot used by clinical charting\b|\blocally scoped\b", 1.3),
    Lexeme(r"\bsingle patient-portal page\b", 1.4),
)

LEADERSHIP_HIGH: tuple[Lexeme, ...] = (
    Lexeme(r"\bpublish rfcs\b|\bexpected to follow unless\b", 1.5),
    Lexeme(r"\bset the (?:technical|multi-year|product) (?:direction|vision|strategy)\b", 1.4),
    Lexeme(r"\bdesign authority\b|\bmandatory for product ui\b", 1.4),
    Lexeme(r"\bcoach senior engineers\b|\bcoach product designers\b", 1.3),
)
LEADERSHIP_LOW: tuple[Lexeme, ...] = (
    Lexeme(r"\bno expectation that you mentor\b|\bmentorship is not part\b", 1.5),
    Lexeme(r"\bnot a technical authority\b|\bmay answer a colleague\b", 1.4),
    Lexeme(r"\bnot expected to run projects for other engineers\b", 1.3),
)

TITLE_SENIORITY_CLAIM = re.compile(
    r"\b(senior|staff|principal|distinguished|fellow)\b",
    re.IGNORECASE,
)
TITLE_MANAGER_CLAIM = re.compile(
    r"\b(engineering manager|people manager|director|vice president|head of)\b",
    re.IGNORECASE,
)
# Junior IC labels used only after evidence-based level inference.
TITLE_JUNIOR_IC_LEVELS = frozenset({"IC1", "IC2"})
# High-scope IC labels used only after evidence-based level inference.
TITLE_HIGH_SCOPE_IC_LEVELS = frozenset({"IC4", "IC5"})

FAMILY_ASSIGN_MIN = 2.0
FAMILY_HYBRID_RATIO = 0.58
FAMILY_HYBRID_ABS = 2.0
OUTSIDE_ASSIGN_MIN = 3.0
TRACK_MANAGER_MIN = 1.8
MANAGEMENT_M2_MIN = 2.0
MANAGEMENT_M3_MIN = 2.2

COMPILED_FAMILY_LEXICONS = {
    family_id: compile_lexemes(lexemes) for family_id, lexemes in FAMILY_LEXICONS.items()
}
COMPILED_SALES_RIVAL = compile_lexemes(SALES_RIVAL_LEXICON)
COMPILED_OUTSIDE = compile_lexemes(OUTSIDE_ARCHITECTURE_LEXICON)
COMPILED_PM_POSITIVE = compile_lexemes(PEOPLE_MANAGER_POSITIVE)
COMPILED_PM_NEGATIVE = compile_lexemes(PEOPLE_MANAGER_NEGATIVE)
COMPILED_M2 = compile_lexemes(M2_LEXICON)
COMPILED_M3 = compile_lexemes(M3_LEXICON)
COMPILED_SCOPE_HIGH = compile_lexemes(SCOPE_HIGH)
COMPILED_SCOPE_MID = compile_lexemes(SCOPE_MID)
COMPILED_SCOPE_LOW = compile_lexemes(SCOPE_LOW)
COMPILED_AUTONOMY_HIGH = compile_lexemes(AUTONOMY_HIGH)
COMPILED_AUTONOMY_LOW = compile_lexemes(AUTONOMY_LOW)
COMPILED_COMPLEXITY_HIGH = compile_lexemes(COMPLEXITY_HIGH)
COMPILED_COMPLEXITY_LOW = compile_lexemes(COMPLEXITY_LOW)
COMPILED_IMPACT_HIGH = compile_lexemes(IMPACT_HIGH)
COMPILED_IMPACT_LOW = compile_lexemes(IMPACT_LOW)
COMPILED_LEADERSHIP_HIGH = compile_lexemes(LEADERSHIP_HIGH)
COMPILED_LEADERSHIP_LOW = compile_lexemes(LEADERSHIP_LOW)

LEVEL_BY_LABEL = {item.label: item for item in LEVEL_DEFINITIONS}
FAMILY_BY_ID = {item.id: item for item in JOB_FAMILIES}


SCOPE_SPLIT_CUES = (
    re.compile(
        r"\b(used by|limited to|own |owns |across|company-wide|named|every|single|one application|"
        r"widget|ticket scope|forty|impact|product lines|services used)\b",
        re.IGNORECASE,
    ),
)
AUTONOMY_SPLIT_CUES = (
    re.compile(
        r"\b(decide|you choose|latitude|escalate|approval|sign-off|cannot|implementation details|"
        r"already made|already decided|follow|tickets|wide latitude|decision-maker|freeze|"
        r"block a release|do not assign|headcount|performance ratings)\b",
        re.IGNORECASE,
    ),
)
COMPLEXITY_CUES = (
    re.compile(
        r"\b(complex|edge cases?|architecture|failure|invariant|multi-tenant|pci|ledger|"
        r"failover|systemic|threat-model|error budget|migration)\b",
        re.IGNORECASE,
    ),
)
IMPACT_CUES = (
    re.compile(
        r"\b(impact|used by|company-wide|every|revenue|affect|across every|pause|stop a launch)\b",
        re.IGNORECASE,
    ),
)
PEOPLE_MGMT_CUES = (
    re.compile(
        r"\b(direct reports|hiring|performance review|1:1|people management|manager of record|"
        r"people-management|unassign|discipline|staffing)\b",
        re.IGNORECASE,
    ),
)
LEADERSHIP_CUES = (
    re.compile(
        r"\b(mentor|coach|influence|technical consensus|rfc|critique|pair|lead a small project|"
        r"technical agenda|authority|not a technical)\b",
        re.IGNORECASE,
    ),
)
DECISION_CUES = (
    re.compile(
        r"\b(decide|sign-off|cannot|you choose|escalate|approval|default decision|"
        r"block a release|freeze a deploy|say no)\b",
        re.IGNORECASE,
    ),
)
