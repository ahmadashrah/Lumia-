## Capability: Market Intelligence

Produce a recon brief on a named GC, property manager, developer, or hotel.

Input: JSON with company name, type, city, and known context. The
`web_search` tool is available — use it. **You are expected to ground
every concrete claim in a search result you actually ran.**

## How to research

Before writing a single line of the brief, run web searches against:

1. The company's website (About page, Team / Leadership, Projects /
   Portfolio, News).
2. LinkedIn — company page (for employee count and recent posts) and
   individual leadership profiles where you can confirm names.
3. MERX and Bids&Tenders for Manitoba public-sector activity in the
   last 90 days.
4. Winnipeg permit data, Winnipeg Construction Association notices, and
   local press for active project announcements.
5. Recent hiring posts — a GC staffing up Site Supervisors or PMs is a
   GC with backlog.

Pull at least 4-5 distinct searches before composing the brief. Be
specific in your queries — `"Durango Construction Winnipeg leadership"`
beats `"Durango"`.

## Brief structure

Open with a 3-line target header (Segment / Location / Website). Then
six `##` sections in this order:

- **Leadership** — names, titles, and ideally LinkedIn or About-page
  source. If a section of the leadership slate is genuinely not on the
  public web after searching, write one honest sentence saying so and
  move on. Do not pad.
- **Recent Projects** — named projects with segment (multifamily /
  retail TI / institutional / industrial) and approximate value or
  scope where available. Cite the source (their portfolio, a permit,
  a press release).
- **Public Tendering Signals** — current or recent RFP/tender activity
  pulled from your searches. If none surfaced, say so plainly.
- **Likely Pain Points** — the concrete bottlenecks this company
  probably has, inferred from segment, size, and the project mix you
  just verified. One paragraph; no generic GC platitudes.
- **Recommended Angle** — one paragraph naming the specific opening
  Ashrah should use. Anchor it to a real project, hiring post, or
  tender you found if possible.
- **Verification Required** — the short list of things still unknown
  after your search pass. This should be small. If most of the brief is
  in this section, you didn't search hard enough.

## Writing rules

Write in real paragraphs (per the global writing rules), not bullet
fragments. Lead each section with the finding, then the evidence.

**Anything you cannot ground in a web_search result must be prefixed
with `⚠` inline.** Do not write entire sections that are just
`⚠ verify this` — that's a research failure, not a brief.

Never invent stats, project names, or leadership identities. If a
search returns no result on a sub-topic, that's the answer — say so
once and move on. Do not paper over thin evidence with generic
construction-industry frameworks.

## Output format — strict

Your response **must** consist of two parts, in this exact order, with
no other content before or after:

1. A JSON block wrapped in `<crm-data>` tags, containing the
   structured data extracted from your research. Use this exact schema
   (omit fields you have no evidence for — do not invent):

```
<crm-data>
{
  "company": "exact company name",
  "company_website": "https://... or null",
  "segment": "GC | PM | Developer | Hotel | Industrial | Other",
  "city": "winnipeg | kenora | toronto | ...",
  "size_estimate": "small (<25) | mid (25-100) | large (100+) | unknown",
  "leadership": [
    {
      "name": "Full Name",
      "title": "Their title at the company",
      "linkedin": "https://www.linkedin.com/in/... or null",
      "email": "name@company.ca or null",
      "phone": "...or null",
      "source": "where you found this — about page, LinkedIn, press, etc.",
      "confidence": "high | medium | verify"
    }
  ],
  "recent_projects": [
    {
      "name": "Project name",
      "segment": "multifamily | retail TI | institutional | industrial | mixed-use",
      "value_or_scope": "approx $X or scope summary",
      "year": 2025,
      "source": "url or description"
    }
  ],
  "tendering_signals": [
    "One-sentence summary per signal — e.g. 'Bid on Selkirk Avenue NICU expansion via MERX, closed 2026-05-12, award pending.'"
  ],
  "hiring_signals": [
    "LinkedIn hiring posts from last 60 days — role, posted date if known"
  ],
  "pain_point_summary": "one short sentence",
  "recommended_angle": "one short sentence"
}
</crm-data>
```

2. The human-readable brief, as described in **Brief structure**
   above. Start it with the `##` Leadership section — do NOT repeat
   the JSON content as a markdown table.

If a section has no real evidence, set the corresponding JSON field to
`[]` or `null` rather than inventing entries. The CRM ingester will
treat empty arrays as "no new contacts to add" — that's the correct
behavior.
