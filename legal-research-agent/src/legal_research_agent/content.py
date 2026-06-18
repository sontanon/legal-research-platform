"""Mock legal content generator.

Returns plausible-but-simulated legal analysis on the enforceability of
non-compete agreements in U.S. states. A keyword checker routes California/CA
and New York/NY to jurisdiction-specific output; anything else gets a general
reasonableness-standard response. Output depth scales with effort tier.

THIS IS NOT REAL LEGAL ADVICE. Every report carries an explicit disclaimer.
"""

from __future__ import annotations

import random

from .schemas import (
    Citation,
    Effort,
    Jurisdiction,
    LegalReport,
    ReportSection,
)

DISCLAIMER = (
    "MOCK/SIMULATED OUTPUT FOR INTEGRATION TESTING ONLY. This is not legal "
    "advice, was not produced by an attorney, and must not be relied upon. "
    "Citations are fabricated. Consult a licensed lawyer for any real matter."
)


def detect_jurisdiction(query: str) -> Jurisdiction:
    q = query.lower()
    if " california" in q or " calif" in q or re_word(q, "ca"):
        return Jurisdiction.california
    if " new york" in q or " nyc" in q or re_word(q, "ny"):
        return Jurisdiction.new_york
    return Jurisdiction.general


def re_word(text: str, word: str) -> bool:
    import re
    return bool(re.search(rf"\b{re.escape(word)}\b", text))


def _ca_citations() -> list[Citation]:
    return [
        Citation(title="Cal. Bus. & Prof. Code § 16600", url="https://leginfo.legislature.ca.gov/faces/codes_displaySection.xhtml?lawCode=BPC&sectionNum=16600", type="statute"),
        Citation(title="Edwards v. Arthur Andersen LLP (2008) 44 Cal.4th 937", url="https://example.com/mock/edwards-v-arthur-andersen", type="case"),
    ]


def _ny_citations() -> list[Citation]:
    return [
        Citation(title="N.Y. Gen. Oblig. Law § 5-321", url="https://example.com/mock/ny-gen-oblig-5-321", type="statute"),
        Citation(title="NY Non-Compete Ban (S3102A, eff. 2025)", url="https://example.com/mock/ny-noncompete-ban", type="statute"),
        Citation(title="BDO USA v. DCG (2018)", url="https://example.com/mock/bdo-v-dcg", type="case"),
    ]


def _general_citations() -> list[Citation]:
    return [
        Citation(title="Restatement (Second) of Contracts § 188", url="https://example.com/mock/restatement-188", type="secondary"),
        Citation(title="Reasonableness standard (state-specific)", url="https://example.com/mock/reasonableness-standard", type="secondary"),
    ]


def build_report(job_id: str, query: str, effort: Effort, jurisdiction: Jurisdiction) -> LegalReport:
    if jurisdiction == Jurisdiction.california:
        return _california(job_id, query, effort)
    if jurisdiction == Jurisdiction.new_york:
        return _new_york(job_id, query, effort)
    return _general(job_id, query, effort)


def _california(job_id: str, query: str, effort: Effort) -> LegalReport:
    summary = (
        "## Non-competes in California\n\n"
        "California broadly **voids** non-compete agreements under Bus. & Prof. "
        "Code § 16600, with narrow exceptions (sale of a business interest, "
        "dissolution, and trade-secret protection). A general employee non-compete "
        "is almost certainly unenforceable."
    )
    risk = 8  # low enforceability risk for the employer
    citations = _ca_citations()
    sections: list[ReportSection] = []
    if effort in (Effort.standard, Effort.deep):
        sections.append(ReportSection(
            title="Statutory framework",
            body_markdown=(
                "Section 16600 voids restraints on lawful trade or employment "
                "unless they fall within §§ 16601–16607 (e.g., sale-of-business). "
                "Independent-contractor and employee restraints are treated alike."
            ),
        ))
        sections.append(ReportSection(
            title="Case law posture",
            body_markdown=(
                "*Edwards v. Arthur Andersen* (2008) confirmed that a restraint "
                "on an employee's ability to work for a competitor is void even "
                "if narrowly tailored. Narrow-tailoring does not save a non-compete "
                "in California the way it can in other states."
            ),
        ))
    if effort == Effort.deep:
        sections.append(ReportSection(
            title="Exceptions and edge cases",
            body_markdown=(
                "1. **Sale of business** (§ 16601): buyer-side non-competes tied to "
                "a substantial ownership sale may be enforceable.\n"
                "2. **Trade secrets / Uniform Trade Secrets Act**: post-employment "
                "restrictions grounded in trade-secret protection survive, but are "
                "not 'non-competes' as such.\n"
                "3. **Out-of-state choice of law**: California courts generally "
                "refuse to enforce another state's law choosing to uphold a "
                "non-compete against a California resident (*Application Group v. "
                "Hunter* line of reasoning).\n"
                "4. **Section 16600.5** (recent amendments) narrows certain "
                "employee-related restrictions further."
            ),
        ))
        sections.append(ReportSection(
            title="Practical recommendations",
            body_markdown=(
                "- Do not rely on a garden-variety employee non-compete in California.\n"
                "- Use NDAs + trade-secret agreements instead.\n"
                "- For acquisitions, scope sale-of-business covenants narrowly to the "
                "geography/line of business actually sold.\n"
                "- Expect choice-of-law and forum-selection clauses to be disregarded "
                "for California residents."
            ),
        ))
    return LegalReport(
        job_id=job_id, query=query, effort=Effort.quick if effort == Effort.quick else effort,
        jurisdiction=Jurisdiction.california,
        summary_markdown=summary,
        risk_score=risk,
        citations=citations,
        sections=sections,
        disclaimer=DISCLAIMER,
    )


def _new_york(job_id: str, query: str, effort: Effort) -> LegalReport:
    summary = (
        "## Non-competes in New York\n\n"
        "New York historically applied a **reasonableness** test "
        "(duration, geography, scope, legitimate business interest, not unduly "
        "burdensome). A recent statute banning most non-competes (effective ~2025) "
        "has changed the landscape, with exceptions for sale-of-business and "
        "certain high- earners. Enforceability now depends heavily on worker "
        "compensation and the statutory carve-outs."
    )
    risk = 55  # moderate / shifting
    citations = _ny_citations()
    sections: list[ReportSection] = []
    if effort in (Effort.standard, Effort.deep):
        sections.append(ReportSection(
            title="Common-law reasonableness test",
            body_markdown=(
                "Pre-statute, NY courts weighed: (1) legitimate protectable "
                "interest, (2) reasonable duration, (3) reasonable geography, "
                "(4) no undue hardship, (5) not against public interest. "
                "NY Gen. Oblig. Law § 5-321 voids non-competes in certain "
                "professions (broadcasting, etc.)."
            ),
        ))
        sections.append(ReportSection(
            title="Recent statutory ban",
            body_markdown=(
                "The 2023/2025 legislation bars non-competes for most employees "
                "below a compensation threshold, with sale-of-business and "
                "dissolution exceptions. Enforcement of the ban has been "
                "litigated; the practical posture is in flux."
            ),
        ))
    if effort == Effort.deep:
        sections.append(ReportSection(
            title="Compensation thresholds and carve-outs",
            body_markdown=(
                "- Employees below the statutory compensation cutoff: non-compete "
                "is void.\n"
                "- Sale-of-business covenants (§ 16601-analog): may survive.\n"
                "- High-earner carve-outs: limited and narrowly construed.\n"
                "- Non-solicitation and NDAs are generally treated separately from "
                "non-competes but are still subject to reasonableness review."
            ),
        ))
        sections.append(ReportSection(
            title="Practical recommendations",
            body_markdown=(
                "- For rank-and-file workers: assume a non-compete is unenforceable.\n"
                "- For sale-of-business contexts: scope narrowly and tie to the sale.\n"
                "- Prefer non-solicitation + trade-secret agreements.\n"
                "- Monitor the ongoing litigation around the ban's effective scope."
            ),
        ))
    return LegalReport(
        job_id=job_id, query=query, effort=Effort.quick if effort == Effort.quick else effort,
        jurisdiction=Jurisdiction.new_york,
        summary_markdown=summary,
        risk_score=risk,
        citations=citations,
        sections=sections,
        disclaimer=DISCLAIMER,
    )


def _general(job_id: str, query: str, effort: Effort) -> LegalReport:
    summary = (
        "## Non-competes — general (multi-state) view\n\n"
        "Outside California and New York, most U.S. states apply a "
        "**reasonableness** standard (duration, geographic scope, line of work, "
        "legitimate business interest). Enforceability varies widely: some states "
        "(e.g., North Dakota, Oklahoma) largely ban them; others enforce them "
        "subject to judicial blue-penciling. A jurisdiction-specific analysis is "
        "recommended."
    )
    # pick a random-ish state to vary the output a little
    risk = random.choice([35, 50, 60, 70])
    citations = _general_citations()
    sections: list[ReportSection] = []
    if effort in (Effort.standard, Effort.deep):
        sections.append(ReportSection(
            title="Reasonableness factors",
            body_markdown=(
                "Courts typically weigh: (1) legitimate protectable interest "
                "(trade secrets, goodwill, specialized training), (2) reasonable "
                "duration (often 1–2 years), (3) reasonable geography, (4) scope, "
                "(5) public interest, and (6) undue hardship on the employee."
            ),
        ))
    if effort == Effort.deep:
        sections.append(ReportSection(
            title="State-by-state posture (sampled)",
            body_markdown=(
                "- **Ban states**: CA, ND, OK, and (largely) DC.\n"
                "- **Strong reasonableness states**: TX, FL, GA (with blue-pencil).\n"
                "- **Moderate**: IL, MA, PA, NJ, OH.\n"
                "- **Recent reforms**: CO, IL, WA, OR have introduced income "
                "thresholds above which non-competes are permitted.\n"
                "Confirm the specific jurisdiction before relying on any of these."
            ),
        ))
        sections.append(ReportSection(
            title="Practical recommendations",
            body_markdown=(
                "- Identify the governing-state law first.\n"
                "- Keep duration ≤ 1–2 years and geography to where the employee "
                "actually worked.\n"
                "- Consider non-solicitation + NDA as less-restricted alternatives.\n"
                "- Include a blue-pencil / reformation clause where enforceable."
            ),
        ))
    return LegalReport(
        job_id=job_id, query=query, effort=Effort.quick if effort == Effort.quick else effort,
        jurisdiction=Jurisdiction.general,
        summary_markdown=summary,
        risk_score=risk,
        citations=citations,
        sections=sections,
        disclaimer=DISCLAIMER,
    )
