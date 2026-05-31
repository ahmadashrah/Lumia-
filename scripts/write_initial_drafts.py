"""Hand-drafted initial cold-outreach emails for the BD tracker (Apr 28, 2026).

v3 — pain-point led. Each draft opens with the pain (chasing, surface damage,
surprise slips, reputation risk) and turns to Ashrah's answer (Lumia chat,
6-day forecast, professional cleaning with no surface damage, on-time
delivery framed as their reputation protection). Personalization anchors
from each company's website are preserved.

Run: ./bin/python scripts/write_initial_drafts.py
"""

import json
from datetime import datetime
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parent.parent / "lio" / "data" / "outreach_drafts" / "2026-04-28"
OUT_DIR.mkdir(parents=True, exist_ok=True)

DRAFTS = [
    # ----- Property Managers -----
    {
        "id": "ash-management-group-inc-neda-uddin",
        "to_name": "Neda Uddin",
        "to_email": "nuddin@ashmanagementgroup.com",
        "company": "Ash Management Group",
        "segment": "PM",
        "angle_used": "Pain: chasing painters / Lumia ask",
        "subject": "Stop chasing your painting subs",
        "body": (
            "Hi Neda,\n\n"
            "ASH manages 96+ properties — The Stables, Lofts on Alexander, Prymak Place. "
            "Most painting subs make your PMs chase for status. Calls, missed updates, "
            "budget bleeds.\n\n"
            "Ashrah Painting works differently. Lumia (our ops layer) sends your PM a "
            "daily 5:30 PM site report automatically — and your PM can also ask Lumia "
            "about a unit anytime and get a current answer. No phone tag.\n\n"
            "Worth 10 minutes to walk you through it?"
        ),
        "cta": "Worth 10 minutes to walk you through it?",
        "signals_used": "96+ Manitoba properties, named buildings (The Stables, Lofts on Alexander, Prymak Place).",
        "needs_review_flags": [],
    },
    {
        "id": "ash-management-group-inc-mark-uddin",
        "to_name": "Mark Uddin",
        "to_email": "markuddin@ashmanagementgroup.com",
        "company": "Ash Management Group",
        "segment": "PM",
        "angle_used": "Pain: dented doors at turnover",
        "subject": "Suite turnovers without dented doors",
        "body": (
            "Hi Mark,\n\n"
            "Quick one — with 81 properties in Winnipeg, you've seen what most painting "
            "subs leave behind on a turnover: paint scuffs, dented doors, a punch list "
            "your team has to chase before the next tenant moves in.\n\n"
            "Ashrah Painting cleans professionally as part of every job. No surface "
            "damage on walls, doors, or finished trim. The unit is move-in ready, not "
            "trade-cleanup ready.\n\n"
            "Open to a 10-minute call this week?"
        ),
        "cta": "Open to a 10-minute call this week?",
        "signals_used": "81 Winnipeg properties (multifamily portfolio implies turnover frequency).",
        "needs_review_flags": [
            "Mark and Neda are both at ASH — stagger sends 3-5 days apart so it doesn't read as a blast."
        ],
    },

    # ----- General Contractors -----
    {
        "id": "alair-homes-colin-gagnon",
        "to_name": "Colin Gagnon",
        "to_email": "collin.gagnon@alairhomes.com",
        "company": "Alair Homes",
        "segment": "GC",
        "angle_used": "Pain: PM chase / dented finishes",
        "subject": "Painting that doesn't leave a punch list",
        "body": (
            "Hi Colin,\n\n"
            "Alair runs the franchise model nationally but your Winnipeg jobs still wear "
            "the same painting-sub problems: PM chasing for status, dings on freshly hung "
            "doors at handoff, schedule slips you find out about too late.\n\n"
            "Ashrah Painting fixes all three. Lumia sends auto status to your PM (and "
            "answers questions when asked), 6-day delay forecasting, professional cleaning "
            "with zero surface damage.\n\n"
            "Could I drop our company resume?"
        ),
        "cta": "Could I drop our company resume?",
        "signals_used": "Alair franchise model, Winnipeg location.",
        "needs_review_flags": [
            "Email spelled 'collin' (two L's) — confirm before send."
        ],
    },
    {
        "id": "red-river-solutions-austin-bailly",
        "to_name": "Austin Bailly",
        "to_email": "abailly@rrsgp.ca",
        "company": "Red River Solutions",
        "segment": "GC",
        "angle_used": "Capacity (qualified) — fit-risk flagged",
        "subject": "Painting capacity for Aecon's Manitoba sites",
        "body": (
            "Hi Austin,\n\n"
            "I know RRSGP's flagship is the North End sewage plant — different scope from "
            "where Ashrah usually plays. But Aecon's Manitoba footprint includes buildings "
            "with finishing crews, where painting subs going dark on PMs is a real cost.\n\n"
            "Ashrah runs Lumia: auto site reports plus a chat your PM can ask anytime. Plus "
            "6-day delay forecasting and professional cleaning at handoff.\n\n"
            "Worth 10 minutes to find out if there's overlap, or should I close the loop?"
        ),
        "cta": "Worth 10 minutes to find out if there's overlap, or should I close the loop?",
        "signals_used": "RRSGP = Aecon/Oscar Renda JV on $272M City of Winnipeg NEWPCC sewage plant.",
        "needs_review_flags": [
            "Fit risk: their primary work is wastewater infrastructure. Decide if pursuing ancillary buildings is worth the slot, or de-prioritize this contact."
        ],
    },
    {
        "id": "cic-inc-nikki-santos",
        "to_name": "Nikki Santos",
        "to_email": "nikkis@cic-inc.ca",
        "company": "CIC Inc.",
        "segment": "GC",
        "angle_used": "Pain: restaurant TI schedule slip = lost opening",
        "subject": "Restaurant openings don't survive paint slips",
        "body": (
            "Hi Nikki,\n\n"
            "CIC's been doing restaurant buildouts in Winnipeg for 30+ years. You know the "
            "exact failure mode: painting goes dark for a day, the FF&E install slips, the "
            "soft opening blows, the client's reputation takes the hit before they've sold a "
            "single meal.\n\n"
            "Ashrah Painting flags slips six days out, sends a daily status auto to your PM "
            "(or they can ask Lumia anytime), and finishes with professional cleaning — no "
            "scuffs on the new fixtures.\n\n"
            "Want me to send our company resume?"
        ),
        "cta": "Want me to send our company resume?",
        "signals_used": "CIC = 30+ years Winnipeg GC, restaurant transformations + commercial reno + industrial.",
        "needs_review_flags": [],
    },
    {
        "id": "tractus-projects-chad-horrill",
        "to_name": "Chad Horrill",
        "to_email": "chad@tractusprojects.com",
        "company": "Tractus Projects",
        "segment": "GC",
        "angle_used": "Pain: opening dates / reputation",
        "subject": "Painting that protects your opening dates",
        "body": (
            "Hi Chad,\n\n"
            "Tractus's portfolio — Planet Fitness Polo Park, the McDonald's locations, La "
            "Roca, Millennium Library — lives or dies on opening dates. When painting blows "
            "the schedule or hands over a punch list, your client loses face, not the "
            "painting sub.\n\n"
            "Ashrah works differently. Lumia sends auto status (and answers when your PM "
            "asks), forecasts slips six days out, finishes with professional cleaning. No "
            "dings on new fixtures.\n\n"
            "Coffee at King Edward in the next two weeks?"
        ),
        "cta": "Coffee at King Edward in the next two weeks?",
        "signals_used": "Tractus HQ at 835 King Edward; portfolio includes Planet Fitness Polo Park, McDonald's, La Roca, Millennium Library.",
        "needs_review_flags": [],
    },
    {
        "id": "tractus-projects-lisa-fedorchuk",
        "to_name": "Lisa Fedorchuk",
        "to_email": "lisa@tractusprojects.com",
        "company": "Tractus Projects",
        "segment": "GC",
        "angle_used": "Estimator: AI bid in 24h, 13% lower",
        "subject": "24-hour painting bids for your TI sequence",
        "body": (
            "Hi Lisa,\n\n"
            "Tractus's team page calls out estimating, scheduling, and procurement as your "
            "fortes — you handle the bid AND the schedule. Slow painting subs hurt you on "
            "both ends.\n\n"
            "Lumi (our AI estimating agent) returns a 95%-detailed bid in 24 hours, at least "
            "13% lower than human-estimated subs (we don't carry the overhead). Plus Lumia "
            "auto-status during execution and 6-day delay forecasting so you don't get "
            "surprised.\n\n"
            "Worth adding us to your painting bid list?"
        ),
        "cta": "Worth adding us to your painting bid list?",
        "signals_used": "Tractus TI portfolio (Planet Fitness, McDonald's, La Roca). Lisa's team-page bio explicitly cites estimating.",
        "needs_review_flags": [
            "Email guessed at lisa@tractusprojects.com (not in tracker). VERIFY before send.",
            "Three Tractus contacts — stagger sends across 7+ days."
        ],
    },
    {
        "id": "tractus-projects-joe-palette",
        "to_name": "Joe Palette",
        "to_email": "joe@tractusprojects.com",
        "company": "Tractus Projects",
        "segment": "GC",
        "angle_used": "Pain: punch-list at handoff",
        "subject": "Painting subs that hand over a punch list",
        "body": (
            "Hi Joe,\n\n"
            "Tractus's TI book has a tight trade sequence. The painting sub usually decides "
            "whether handoff is clean — or whether your PM walks through dings on doors, "
            "scuffs on baseboards, drop cloths to clear.\n\n"
            "Ashrah Painting includes professional cleaning as part of every job. Zero "
            "surface damage on walls, doors, finished trim. Your trade sequence isn't blocked "
            "by punch list cleanup.\n\n"
            "Want our company resume?"
        ),
        "cta": "Want our company resume?",
        "signals_used": "Tractus retail/restaurant TI focus.",
        "needs_review_flags": [
            "Email guessed at joe@tractusprojects.com — VERIFY.",
            "Stagger from Chad and Lisa."
        ],
    },
    {
        "id": "blue-lake-construction-ronnie-jamilla",
        "to_name": "Ronnie Jamilla",
        "to_email": "ronnie.jamilla@bluelakeconst.com",
        "company": "Blue Lake Construction",
        "segment": "GC",
        "angle_used": "Pain: schedule risk / no surprises",
        "subject": "Painting sub with 6-day delay warning",
        "body": (
            "Hi Ronnie,\n\n"
            "Complex commercial reno = lots of moving parts, and painting is usually where "
            "schedule risk hides until it's too late. The day-of slip costs you trade "
            "re-sequencing AND a client conversation you didn't want to have.\n\n"
            "Ashrah Painting forecasts slips six days out. Lumia auto-reports daily and "
            "answers your PM's questions when asked. Pro cleaning at handoff with no surface "
            "damage.\n\n"
            "Worth 15 minutes for a quick intro?"
        ),
        "cta": "Worth 15 minutes for a quick intro?",
        "signals_used": "Blue Lake = commercial renos, civil works, large-scale.",
        "needs_review_flags": [],
    },
    {
        "id": "bobsled-construction-james-melendez",
        "to_name": "James Melendez",
        "to_email": "james@bob-sled.ca",
        "company": "Bobsled Construction",
        "segment": "GC",
        "angle_used": "Pain: surface damage at handoff",
        "subject": "Painting that doesn't dent your doors",
        "body": (
            "Hi James,\n\n"
            "Bobsled's commercial TI work — Niche Technology and the like — is where paint "
            "damage on freshly hung doors and finished trim costs you the most. Punch list "
            "items, change orders, client conversations.\n\n"
            "Ashrah Painting includes professional cleaning at handoff. No dings on walls, "
            "doors, or finished surfaces. Lumia auto-reports daily and your PM can ask it "
            "where we are anytime.\n\n"
            "We're a few minutes from your Sherbrook office. Coffee this week?"
        ),
        "cta": "Coffee this week?",
        "signals_used": "Bobsled at 194 Sherbrook St., Winnipeg; portfolio includes Niche Technology TI (2016) + custom residential.",
        "needs_review_flags": [],
    },
    {
        "id": "bobsled-construction-vikneswaran-thirumalai",
        "to_name": "Vikneswaran Thirumalai",
        "to_email": "vik@bob-sled.ca",
        "company": "Bobsled Construction",
        "segment": "GC",
        "angle_used": "Pain: PM chasing for status",
        "subject": "Stop your PM from chasing painters",
        "body": (
            "Hi Vikneswaran,\n\n"
            "Quick intro — Ashrah Painting, commercial finishing in Winnipeg.\n\n"
            "Most painting subs make your PM chase for status. Lumia (our ops layer) auto-"
            "sends a daily site report at 5:30 PM AND lets your PM ask 'where are you on "
            "[unit]?' anytime — and answers. No more phone tag. Plus 6-day delay forecasting "
            "and pro cleaning at handoff.\n\n"
            "Worth a 10-minute call?"
        ),
        "cta": "Worth a 10-minute call?",
        "signals_used": "Bobsled commercial TI portfolio.",
        "needs_review_flags": [
            "Email guessed at vik@bob-sled.ca — VERIFY (could be vikneswaran@ or v.thirumalai@).",
            "Stagger from James — same firm."
        ],
    },
    {
        "id": "bree-dan-construction-kevin-burton",
        "to_name": "Kevin Burton",
        "to_email": "kburton@breedan.ca",
        "company": "Bree-Dan Construction",
        "segment": "GC",
        "angle_used": "Pain: GC's word to developer",
        "subject": "Painting that doesn't burn your reputation",
        "body": (
            "Hi Kevin,\n\n"
            "Bree-Dan has 30+ years of commercial across MB/SK/AB. Painting is usually the "
            "trade that decides whether your word to the developer holds — when it slips, "
            "it's your reputation that takes the hit, not the painting sub's.\n\n"
            "Ashrah Painting forecasts slips six days in advance. Lumia auto-status to your "
            "PM (or they can ask anytime). Pro cleaning at handoff with no surface damage. "
            "On-time delivery is the promise.\n\n"
            "Worth 15 minutes?"
        ),
        "cta": "Worth 15 minutes?",
        "signals_used": "Bree-Dan = 30+ yrs commercial, MB/SK/AB clients. Kevin = Red River College Carpenter grad.",
        "needs_review_flags": [],
    },
    {
        "id": "cgi-constructors-chris-lacasse",
        "to_name": "Chris Lacasse",
        "to_email": "chris.lacasse@cgigc.com",
        "company": "CGI Constructors",
        "segment": "GC",
        "angle_used": "Pain: scaling subs without scaling chaos",
        "subject": "Painting subs that scale with your office",
        "body": (
            "Hi Chris,\n\n"
            "CGI's Winnipeg office is growing — saw the Anastasia Politikina hire. As you "
            "scale Manitoba volume, the painting subs that work at one site start failing at "
            "five — your PMs end up chasing crews across multiple jobs.\n\n"
            "Ashrah scales differently. Lumia auto-reports per site and answers PM questions "
            "on demand. Six-day delay forecasting per job. Crew availability and structured "
            "training keep finish quality consistent across concurrent sites.\n\n"
            "Want our company resume?"
        ),
        "cta": "Want our company resume?",
        "signals_used": "CGI = Toronto HQ, $100M annual backlog, active Winnipeg office, recent staff growth (Anastasia Politikina).",
        "needs_review_flags": [],
    },
    {
        "id": "canotech-consultants-graeme-fardoe",
        "to_name": "Graeme Fardoe",
        "to_email": "graeme@canotech.net",
        "company": "Canotech Consultants",
        "segment": "GC",
        "angle_used": "Pain: reputation across multiple sectors",
        "subject": "Painting that protects your reputation",
        "body": (
            "Hi Graeme,\n\n"
            "Canotech's been Winnipeg-rooted since '88, third generation, and you handle "
            "commercial, industrial, and institutional clients across Manitoba. Reputation "
            "compounds in that range — and a painting sub that goes dark on one PM is one "
            "client referral lost.\n\n"
            "Ashrah Painting holds the schedule. Lumia auto-reports daily plus answers your "
            "PM on demand. Six-day delay forecasting. Pro cleaning at handoff with no "
            "surface damage.\n\n"
            "Coffee?"
        ),
        "cta": "Coffee?",
        "signals_used": "Canotech founded 1988, 3rd-gen family-run, Winnipeg + Northern MB + Arctic, CentrePort partner. Graeme = Managing Partner.",
        "needs_review_flags": [],
    },
    {
        "id": "conprocanada-saher-kilda",
        "to_name": "Saher Kilda",
        "to_email": "saher@conprocanada.ca",
        "company": "Con-Pro Canada",
        "segment": "GC",
        "angle_used": "Pain: high-profile work needs flawless handoff",
        "subject": "Painting that protects your reputation",
        "body": (
            "Hi Saher,\n\n"
            "Con-Pro's portfolio is loud — Starbucks Corydon (one of Canada's largest), "
            "College Jeanne-Sauvé, East Elmwood LEED Gold. On work that visible, a painting "
            "sub leaving a punch list is a client conversation you really don't want.\n\n"
            "Ashrah Painting flags slips six days out, Lumia keeps your PM informed (and "
            "answers questions on demand), and pro cleaning at handoff means zero surface "
            "damage.\n\n"
            "Want a 15-minute intro?"
        ),
        "cta": "Want a 15-minute intro?",
        "signals_used": "Con-Pro = since 1969, Winnipeg HQ, 2,500+ projects, Starbucks Corydon, College Jeanne-Sauvé, East Elmwood LEED Gold.",
        "needs_review_flags": [],
    },
    {
        "id": "contempora-steel-douglas",
        "to_name": "Douglas",
        "to_email": "douglas@contemporasteel.com",
        "company": "Contempora Steel Builders",
        "segment": "GC",
        "angle_used": "Pain: schedule discipline / opening date",
        "subject": "Painting that doesn't slip your opening dates",
        "body": (
            "Hi Douglas,\n\n"
            "Contempora's design-build steel — auto dealerships, Bison Transport, Jade "
            "Transport — runs on schedule discipline. The painting sub is usually where the "
            "client's opening date either holds or slips. Bad news arriving day-of costs you "
            "the relationship.\n\n"
            "Ashrah Painting forecasts slips six days in advance. Lumia auto-reports plus "
            "answers your PM's questions on demand. Pro cleaning at handoff with no surface "
            "damage.\n\n"
            "Worth a call?"
        ),
        "cta": "Worth a call?",
        "signals_used": "Contempora = 45+ yr Winnipeg design-build steel, auto dealerships (West Coast Auto), Bison Transport, Jade Transport.",
        "needs_review_flags": [
            "Last name missing — confirm full name before send."
        ],
    },
    {
        "id": "fabca-greg-fiorentino",
        "to_name": "Greg Fiorentino",
        "to_email": "Greg@fabca.ca",
        "company": "FABCA Construction",
        "segment": "GC",
        "angle_used": "Pain: big-box openings / volume",
        "subject": "Painting subs that scale with your retail book",
        "body": (
            "Hi Greg,\n\n"
            "FABCA's retail portfolio — No Frills, Walmart, Home Depot, Canadian Tire, "
            "Shoppers — runs on volume and tight openings. Painting subs that work fine "
            "on one site start dropping the ball on five. Your PMs end up chasing crews "
            "across the province.\n\n"
            "Ashrah scales without that. Lumia auto-reports per site and answers PM "
            "questions on demand. Six-day delay forecasting per job. Pro cleaning at handoff "
            "with zero surface damage.\n\n"
            "Want our company resume?"
        ),
        "cta": "Want our company resume?",
        "signals_used": "FABCA = retail-heavy GC: No Frills, Shoppers Drug Mart, Home Depot, Canadian Tire, Walmart.",
        "needs_review_flags": [],
    },
    {
        "id": "fabca-fabio-fiorentino",
        "to_name": "Fabio Fiorentino",
        "to_email": "fabio@fabca.ca",
        "company": "FABCA Construction",
        "segment": "GC",
        "angle_used": "Pain: punch list at retail handoff",
        "subject": "Retail handoffs without paint scuffs",
        "body": (
            "Hi Fabio,\n\n"
            "Big-box retail TI has zero tolerance for a painting sub that hands over a "
            "punch list at the walk — scuffs on new fixtures, drop cloths to clear, dings "
            "on freshly painted walls when stocking starts.\n\n"
            "Ashrah Painting includes professional cleaning at handoff. No surface damage. "
            "Lumia keeps your PM informed and answers their questions on demand.\n\n"
            "Worth 15 minutes?"
        ),
        "cta": "Worth 15 minutes?",
        "signals_used": "FABCA retail TI portfolio.",
        "needs_review_flags": [
            "Email guessed at fabio@fabca.ca — VERIFY.",
            "Three FABCA contacts — stagger sends 5+ days apart."
        ],
    },
    {
        "id": "fabca-colin-richards",
        "to_name": "Colin Richards",
        "to_email": "colin@fabca.ca",
        "company": "FABCA Construction",
        "segment": "GC",
        "angle_used": "Estimator: AI bid in 24h, 13% lower + RRC alumni hook",
        "subject": "Painting bids in 24 hours for FABCA",
        "body": (
            "Hi Colin,\n\n"
            "BTCM credential — same Winnipeg trades-college pipeline our crews come "
            "through. Quick intro.\n\n"
            "FABCA's retail TI book is volume-heavy. Painting subs slow your bid book down "
            "with week-long turnarounds and bloated estimator-overhead numbers. Ashrah's AI "
            "estimator returns a 95%-detailed bid in 24 hours, at least 13% lower than "
            "human-estimated subs. Plus Lumia auto-status during execution.\n\n"
            "Want us on FABCA's painting bid list?"
        ),
        "cta": "Want us on FABCA's painting bid list?",
        "signals_used": "FABCA TI sequence. Colin = BTCM credential (likely RRC alum).",
        "needs_review_flags": [
            "Email guessed at colin@fabca.ca — VERIFY.",
            "Stagger from Greg and Fabio.",
            "BTCM credential suggests Red River College alumni angle — Ahmad can lean on shared-pipeline if it lands."
        ],
    },
    {
        "id": "form-structures-steve",
        "to_name": "Steve",
        "to_email": "sw@formstructuresweastren.ca",
        "company": "Form Structures Western",
        "segment": "GC",
        "angle_used": "Pain: chasing painters / no surface damage",
        "subject": "Commercial paint sub that doesn't go dark",
        "body": (
            "Hi Steve,\n\n"
            "Quick intro — Ashrah Painting, Winnipeg-based commercial.\n\n"
            "Most painting subs make your PM chase. Status calls, missed updates, dings on "
            "finished surfaces at handoff. We do it differently: Lumia auto-reports daily "
            "plus answers your PM on demand. Six-day delay forecasting. Pro cleaning at "
            "handoff with no surface damage.\n\n"
            "Open to a 10-minute call?"
        ),
        "cta": "Open to a 10-minute call?",
        "signals_used": "None — site unreachable, web search inconclusive.",
        "needs_review_flags": [
            "Email domain has typo ('weastren' vs. 'western') — verify domain before send.",
            "Last name missing.",
            "Generic anchor — consider deferring until we have actual signals on this company."
        ],
    },
    {
        "id": "gardon-construction-shane-johnson",
        "to_name": "Shane Johnson",
        "to_email": "sjohnson@gardonconstruction.com",
        "company": "Gardon Construction",
        "segment": "GC",
        "angle_used": "Estimator: AI bid in 24h, 13% lower",
        "subject": "Painting bids in 24 hours for Gardon",
        "body": (
            "Hi Shane,\n\n"
            "Gardon's range — MEC, Prairie Mountain CU, Seven Oaks PAC — means your bid "
            "book hits a lot of spec types. Most painting subs slow that down with "
            "week-long turnarounds and bloated estimator-overhead numbers.\n\n"
            "Lumi (our AI estimating agent) returns a 95%-detailed bid in 24 hours, at "
            "least 13% lower than human-estimated subs. Plus Lumia auto-status during the "
            "job and pro cleanup at handoff with no surface damage.\n\n"
            "Want us added to Gardon's painting bid list?"
        ),
        "cta": "Want us added to Gardon's painting bid list?",
        "signals_used": "Gardon = ~40 yrs Manitoba/Western Canada; MEC, Prairie Mountain CU, Seven Oaks PAC; COR + Gold Seal.",
        "needs_review_flags": [],
    },
    {
        "id": "gateway-construction-wayne-fehr",
        "to_name": "Wayne Fehr",
        "to_email": "wayne@gatewayconstruction.ca",
        "company": "Gateway Construction & Engineering",
        "segment": "GC",
        "angle_used": "Estimator: AI bid in 24h, 13% lower",
        "subject": "Painting bids in 24 hours for Gateway",
        "body": (
            "Hi Wayne,\n\n"
            "50 years at Gateway means you've bid a lot of multifamily, institutional, and "
            "commercial. Painting subs bidding slow and bloated don't help your numbers — "
            "or your bid book.\n\n"
            "Lumi (our AI estimating agent) returns a 95%-detailed bid in 24 hours, at "
            "least 13% lower than human-estimated subs (we don't carry that overhead). "
            "Plus Lumia auto-status during the job and pro cleaning at handoff with no "
            "surface damage.\n\n"
            "Worth adding us to Gateway's painting bid list?"
        ),
        "cta": "Worth adding us to Gateway's painting bid list?",
        "signals_used": "Gateway = 50 years, 434 Archibald St., commercial/multifamily/institutional.",
        "needs_review_flags": [],
    },
    {
        "id": "harris-builders-bryan-harris",
        "to_name": "Bryan Harris",
        "to_email": "bryan@harrisbuilders.ca",
        "company": "Harris Builders",
        "segment": "GC",
        "angle_used": "Pain: high-end handoff / surface damage",
        "subject": "High-end finishes without handoff damage",
        "body": (
            "Hi Bryan,\n\n"
            "Harris's portfolio across River Heights, Tuxedo, and Wellington Modern is "
            "high-end residential — finish quality and a clean handoff are the whole job. "
            "A painting sub leaving dings on doors or scuffs on baseboards undoes the rest "
            "of the build.\n\n"
            "Ashrah Painting includes professional cleaning at handoff. No surface damage. "
            "Lumia keeps your PM informed and answers their questions on demand.\n\n"
            "Coffee at 520 Academy?"
        ),
        "cta": "Coffee at 520 Academy?",
        "signals_used": "Harris HQ at 520 Academy Rd; portfolio = Wellington Modern multifamily, V Residence, Charleswood/Henderson/Crescentwood custom.",
        "needs_review_flags": [],
    },
    {
        "id": "jilmark-construction-john-froese",
        "to_name": "John Froese",
        "to_email": "john@jilmark.com",
        "company": "Jilmark Construction",
        "segment": "GC",
        "angle_used": "Pain: schedule risk across diverse spec",
        "subject": "Painting that doesn't surprise your schedule",
        "body": (
            "Hi John,\n\n"
            "Jilmark's range — heritage like Fortune Macdonald, Pollard Banknote, "
            "multifamily, medical — means each project's trade sequence is different. "
            "Painting is usually where the schedule either holds or surprises you the day "
            "of.\n\n"
            "Ashrah Painting forecasts slips six days in advance. Lumia auto-status daily "
            "plus answers your PM on demand. Pro cleaning at handoff with no surface damage. "
            "Worth 15 minutes?"
        ),
        "cta": "Worth 15 minutes?",
        "signals_used": "Jilmark = since 2001, Winnipeg, heritage (Fortune Macdonald), Pollard Banknote, multifamily, medical.",
        "needs_review_flags": [],
    },
    {
        "id": "kenmare-developments-kyle-kostenuk",
        "to_name": "Kyle Kostenuk",
        "to_email": "kyle@kenmaredevelopments.com",
        "company": "Kenmare Developments",
        "segment": "GC",
        "angle_used": "Pain: scaling without losing PM bandwidth",
        "subject": "Paint sub that scales with your portfolio",
        "body": (
            "Hi Kyle,\n\n"
            "Kenmare's delivered 350+ residential units — Leola Village, Granite Hill, "
            "infill across Manitoba and Ontario. As you build out the in-house construction "
            "division, painting subs that work fine at three units start eating PM hours at "
            "thirty. Status calls, surprise slips, dings on finished doors at turnover.\n\n"
            "Ashrah scales without that. Lumia auto-reports plus answers your PM on demand. "
            "Six-day delay forecasting. Pro cleaning at every handoff with no surface "
            "damage. Coffee at Corydon sometime?"
        ),
        "cta": "Coffee at Corydon sometime?",
        "signals_used": "Kenmare = President/CEO Kyle Kostenuk, 350+ residential units, Leola Village, Granite Hill, MB+ON, in-house GC build-out at 668 Corydon Ave.",
        "needs_review_flags": [
            "Highest-priority target on this list — Kyle is the CEO, multifamily-heavy, scaling."
        ],
    },
    {
        "id": "ld-builders-todd-hamilton",
        "to_name": "Todd Hamilton",
        "to_email": "thamilton@ldbuilders.ca",
        "company": "LD Builders",
        "segment": "GC",
        "angle_used": "Pain: range / consistency across spec types",
        "subject": "Painting sub for multifamily + commercial",
        "body": (
            "Hi Todd,\n\n"
            "LD's mix — 193 commercial, 137 residential, multifamily portfolios like Amber "
            "Gates, Innsbruck Village, Ivy Trails — covers spec types most painting subs "
            "drift across. PM ends up chasing crews on one job while another goes dark.\n\n"
            "Ashrah Painting doesn't drift. Lumia auto-reports per site plus answers PM "
            "questions on demand. Six-day delay forecasting. Pro cleaning at handoff with "
            "no surface damage.\n\n"
            "Worth 15 minutes?"
        ),
        "cta": "Worth 15 minutes?",
        "signals_used": "LD = 45+ yrs, 193 commercial + 137 residential projects, Amber Gates, Innsbruck Village, Ivy Trails, founded by Larry Dyck.",
        "needs_review_flags": [],
    },

    # ----- Tier-1 estimator drafts (from estimator research, 2026-04-28) -----
    {
        "id": "bird-construction-group-jason-miller",
        "to_name": "Jason Miller",
        "to_email": "",
        "company": "Bird Construction Group",
        "segment": "GC",
        "angle_used": "Estimator: AI bid 24h, 13% lower + RRC alumni hook",
        "subject": "Painting bids in 24 hours, AI-driven",
        "body": (
            "Hi Jason,\n\n"
            "Quick intro — Ashrah Painting, Winnipeg commercial. Saw you're estimating at "
            "Bird and you came up through Red River College — same trades pipeline our "
            "crews come through.\n\n"
            "Most painting subs take a week to bid and come back bloated with estimator "
            "overhead. Lumi (our AI estimating agent) returns a 95%-detailed bid in 24 hours, at least "
            "13% lower than human-estimated subs. Plus Lumia auto-status during the job "
            "and pro cleanup at handoff with no surface damage.\n\n"
            "Want us added to Bird's painting bid list?"
        ),
        "cta": "Want us added to Bird's painting bid list?",
        "signals_used": "Jason Miller = Estimator at Bird Construction Winnipeg, Red River College alum.",
        "needs_review_flags": [
            "No public email — start with LinkedIn message or call Bird Winnipeg switchboard for direct line."
        ],
    },
    {
        "id": "bird-construction-group-umar-sharif",
        "to_name": "Umar Sharif",
        "to_email": "",
        "company": "Bird Construction Group",
        "segment": "GC",
        "angle_used": "Estimator manager: AI bid 24h, 13% lower",
        "subject": "Faster, lower painting bids for Bird",
        "body": (
            "Hi Umar,\n\n"
            "You run estimating at Bird Winnipeg — you decide who's on the bid list. Most "
            "painting subs take a week to come back, and the numbers carry estimator "
            "overhead.\n\n"
            "Lumi (our AI estimating agent) returns a 95%-detailed bid in 24 hours, at "
            "least 13% lower because we don't carry that overhead. Lumia auto-status "
            "during the job. Pro cleaning at handoff with no surface damage.\n\n"
            "Worth adding us to your bid list?"
        ),
        "cta": "Worth adding us to your bid list?",
        "signals_used": "Umar Sharif = Senior Manager, Estimating at Bird Construction Winnipeg.",
        "needs_review_flags": [
            "No public email — start with LinkedIn or call Bird Winnipeg switchboard.",
            "Stagger from Jason Miller — same firm."
        ],
    },
    {
        "id": "bockstael-construction-limited-brad-harder",
        "to_name": "Brad Harder",
        "to_email": "",
        "company": "Bockstael Construction Limited",
        "segment": "GC",
        "angle_used": "Estimator: ex-Kiewit / AI bid 24h, 13% lower",
        "subject": "Painting bids in 24 hours, 13% lower",
        "body": (
            "Hi Brad,\n\n"
            "Coming up through Kiewit you've seen exactly what estimator overhead does to "
            "sub bids — slow turnarounds, bloated numbers. Bockstael's preconstruction is "
            "where that pain shows up first.\n\n"
            "Lumi (our AI estimating agent) returns a 95%-detailed bid in 24 hours, at least "
            "13% lower than human-estimated competing subs. Plus Lumia auto-status during "
            "the job and pro cleanup with no surface damage.\n\n"
            "Worth adding us to Bockstael's painting bid list?"
        ),
        "cta": "Worth adding us to Bockstael's painting bid list?",
        "signals_used": "Brad Harder = Manager, Preconstruction at Bockstael (110-yr Manitoba builder), ex-Kiewit estimator/lead estimator path.",
        "needs_review_flags": [
            "No public email — try via Bockstael switchboard 204-233-7135 or LinkedIn."
        ],
    },
    {
        "id": "con-pro-canada-pritesh-shah",
        "to_name": "Pritesh Shah",
        "to_email": "pritesh@conpro.mb.ca",
        "company": "Con-Pro Industries Canada Ltd.",
        "segment": "GC",
        "angle_used": "Estimator: 14-yr tenure / AI bid 24h, 13% lower",
        "subject": "24-hour painting bids, 13% lower",
        "body": (
            "Hi Pritesh,\n\n"
            "14 years as Chief Estimator at Con-Pro means you've seen every painting sub "
            "come, go, and come back with a bloated bid a week late. Starbucks Corydon and "
            "East Elmwood LEED Gold caliber doesn't tolerate either.\n\n"
            "Lumi (our AI estimating agent) returns a 95%-detailed bid in 24 hours, at least "
            "13% lower than human-estimated subs. Lumia auto-status during the job. Pro "
            "cleaning at handoff with no surface damage.\n\n"
            "Want us added to Con-Pro's painting bid list?"
        ),
        "cta": "Want us added to Con-Pro's painting bid list?",
        "signals_used": "Pritesh Shah = Chief Estimator at Con-Pro since 2012 (~14 yrs). Email pattern @conpro.mb.ca (NOT conprocanada.ca).",
        "needs_review_flags": [
            "Email pattern guessed at pritesh@conpro.mb.ca — could be pshah@. VERIFY before send."
        ],
    },
    {
        "id": "contempora-steel-builders-andrew-coleman",
        "to_name": "Andrew Coleman",
        "to_email": "andrew@contemporasteel.com",
        "company": "Contempora Steel Builders",
        "segment": "GC",
        "angle_used": "Estimator: RRC alumni hook + AI bid 24h, 13% lower",
        "subject": "Painting bids in 24 hours, AI-driven",
        "body": (
            "Hi Andrew,\n\n"
            "Red River College BTech — same Winnipeg trades pipeline our crews come "
            "through. Quick intro on Ashrah Painting.\n\n"
            "Pre-construction at Contempora — West Coast Auto, Bison Transport, Jade "
            "Transport — lives or dies on bid speed and bid accuracy. Most painting "
            "subs miss on both. Lumi (our AI estimating agent) returns a 95%-detailed bid in 24 hours, "
            "at least 13% lower than human-estimated subs. Lumia auto-status on the job, "
            "pro cleanup with no surface damage.\n\n"
            "Worth adding us to Contempora's bid list?"
        ),
        "cta": "Worth adding us to Contempora's bid list?",
        "signals_used": "Andrew Coleman = Director Pre-Construction at Contempora Steel, RRC BTech alum, ex-Graham Construction PM.",
        "needs_review_flags": [
            "Email guessed at andrew@contemporasteel.com — could be acoleman@. VERIFY."
        ],
    },
    {
        "id": "stand-tall-contracting-jason-zarrillo",
        "to_name": "Jason Zarrillo",
        "to_email": "",
        "company": "Stand Tall Contracting",
        "segment": "GC",
        "angle_used": "CEO/Estimator: AI bid 24h, 13% lower",
        "subject": "Painting bids in 24 hours for your jobs",
        "body": (
            "Hi Jason,\n\n"
            "Stand Tall's portfolio — Manitoba Hydro office reno, Best Buy, Southeast "
            "Collegiate, IKEA maintenance — covers commercial fit-up that bleeds money "
            "fast when a painting sub goes dark. And you handle estimating yourself, so "
            "every slow sub bid is hours off your week.\n\n"
            "Lumi (our AI estimating agent) returns a 95%-detailed bid in 24 hours, at "
            "least 13% lower than human-estimated subs. Lumia auto-status during the job. "
            "Pro cleaning at handoff with no surface damage.\n\n"
            "Want us on your next painting bid?"
        ),
        "cta": "Want us on your next painting bid?",
        "signals_used": "Jason Zarrillo = CEO of Stand Tall Contracting, customer reviews confirm he personally site-estimates.",
        "needs_review_flags": [
            "No public email — start with LinkedIn message."
        ],
    },
    {
        "id": "thomas-design-builders-jeff-miller",
        "to_name": "Jeff Miller",
        "to_email": "",
        "company": "Thomas Design Builders Ltd",
        "segment": "GC",
        "angle_used": "Owner+Estimator: RRC alumni hook + AI bid 24h, 13% lower",
        "subject": "Painting bids that don't slow your bid book",
        "body": (
            "Hi Jeff,\n\n"
            "Red River College Design & Construction Tech '99 — same pipeline our crews "
            "come through. Quick intro.\n\n"
            "TDB's run is real — 650+ projects, $500M+ across Western Canada, work like "
            "Smart Park, MCI Performing Arts Centre, the Millennium Centre. On that volume "
            "of design-build, slow painting subs are a tax on every bid.\n\n"
            "Lumi (our AI estimating agent) returns a 95%-detailed bid in 24 hours, at "
            "least 13% lower than human-estimated subs. Lumia auto-status during execution. "
            "Pro cleanup at handoff with no surface damage.\n\n"
            "Coffee?"
        ),
        "cta": "Coffee?",
        "signals_used": "Jeff Miller = President / Owner Thomas Design Builders, Red River College Design & Construction Tech '99 grad, C.E.T. credential, 24+ yrs at TDB.",
        "needs_review_flags": [
            "No public email — start with LinkedIn or 204-500-1213.",
            "Strongest shared-alumni hook on the list — Red River College + same year as many of our crew leads."
        ],
    },
    {
        "id": "valdek-construction-matt-adamiec",
        "to_name": "Matt Adamiec",
        "to_email": "",
        "company": "Valdek Construction Inc",
        "segment": "GC",
        "angle_used": "Owner+Estimator: RRC alumni + AI bid 24h, 13% lower",
        "subject": "Painting sub built like a tech company",
        "body": (
            "Hi Matt,\n\n"
            "Red River College Civil Eng + KGS Group — you'd recognize what we're trying "
            "to build at Ashrah. Quick intro.\n\n"
            "Ashrah Painting runs like a tech company. Lumi (our AI estimating agent) returns a 95%-detailed"
            "bid in 24 hours, at least 13% lower than human-estimated subs. Lumia ops "
            "layer keeps the PM informed and answers questions on demand. Pro cleanup at "
            "handoff with no surface damage.\n\n"
            "Coffee?"
        ),
        "cta": "Coffee?",
        "signals_used": "Matt Adamiec = Founder/Owner Valdek, Red River College Civil Engineering Diploma grad, ex-KGS Group.",
        "needs_review_flags": [
            "No public email — start with LinkedIn.",
            "OUT OF ICP — Valdek is mostly residential basement/kitchen/custom-home work (Houzz, Facebook portfolio confirms). Commercial painting pitch is a stretch. De-prioritize unless they expand into commercial.",
        ],
    },
    {
        "id": "winnipeg-building-decorating-dale-frandsen",
        "to_name": "Dale Frandsen",
        "to_email": "",
        "company": "Winnipeg Building & Decorating Ltd. (WBD)",
        "segment": "GC",
        "angle_used": "Estimator: AI bid 24h, 13% lower",
        "subject": "24-hour painting bids for your bid book",
        "body": (
            "Hi Dale,\n\n"
            "WBD's 70-year run means you bid a LOT of insurance restoration and commercial "
            "reno. The painting line item is usually where bids come back slow and bloated "
            "— not your problem to fix, but it slows your whole bid book.\n\n"
            "Lumi (our AI estimating agent) returns a 95%-detailed bid in 24 hours, at "
            "least 13% lower than human-estimated subs. Lumia auto-status on the job. "
            "Pro cleaning at handoff with no surface damage.\n\n"
            "Worth adding us to WBD's painting bid list?"
        ),
        "cta": "Worth adding us to WBD's painting bid list?",
        "signals_used": "Dale Frandsen = Senior Estimator at WBD (70+ yrs Winnipeg). Email pattern likely @wbdmb.ca or @pgbldg.com / @wpgbldg.com.",
        "needs_review_flags": [
            "Email domain unclear — research surfaced @pgbldg.com / @wpgbldg.com pattern in addition to wbdmb.ca. VERIFY before send.",
            "Three WBD estimators — stagger sends (Dale first as senior)."
        ],
    },
    {
        "id": "winnipeg-building-decorating-matthew-keys",
        "to_name": "Matthew Keys",
        "to_email": "",
        "company": "Winnipeg Building & Decorating Ltd. (WBD)",
        "segment": "GC",
        "angle_used": "PM-Estimator hybrid: AI bid + Lumia execution",
        "subject": "Faster painting bids you can also run",
        "body": (
            "Hi Matthew,\n\n"
            "PM-Estimator hybrid is a tough seat — you bid the work and you run it. Slow "
            "sub bids hurt you twice: once at bid, again when execution drags.\n\n"
            "Ashrah Painting solves both. Lumi (our AI estimating agent) returns a 95%-detailed bid in 24 hours, at "
            "least 13% lower. Lumia ops layer during execution: auto-status, ask-Lumia "
            "chat, 6-day delay forecasting. Pro cleaning at handoff with no surface damage.\n\n"
            "Worth adding us to your bid list?"
        ),
        "cta": "Worth adding us to your bid list?",
        "signals_used": "Matthew Keys = Project Managing Estimator at WBD (hybrid bid+execute role).",
        "needs_review_flags": [
            "Email domain unclear — verify via WBD switchboard.",
            "Stagger 5+ days from Dale and Darci-lee — same firm."
        ],
    },
    # ===== Cold drafts added 2026-04-29 (manual_contacts.json) =====
    {
        "id": "westland-construction-craig-hildebrandt",
        "to_name": "Craig",
        "to_email": "craighildebrandt@westlandltd.net",
        "company": "Westland Construction",
        "segment": "GC",
        "angle_used": "Cold owner: range across spec types + reputation",
        "subject": "Painting that protects Westland's name",
        "body": (
            "Hi Craig,\n\n"
            "Westland's been at it 40+ years across commercial, industrial, institutional — "
            "including hydroelectric support work. Range like that punishes painting subs "
            "whose finish drifts between spec types, and your name is on every one of "
            "those projects.\n\n"
            "Ashrah Painting holds the schedule. Lumi (our AI estimating agent) returns "
            "a 95%-detailed bid in 24 hours, at least 13% lower than human-estimated subs. "
            "Lumia auto-status during execution. Pro cleaning at handoff with no surface "
            "damage.\n\n"
            "Worth 15 minutes for a quick intro?"
        ),
        "cta": "Worth 15 minutes for a quick intro?",
        "signals_used": "Westland = 40+ yrs commercial/industrial/institutional/hydro, Unit 1-475 Dovercourt Dr.",
        "needs_review_flags": [],
    },
    {
        "id": "durango-construction-keith-manary",
        "to_name": "Keith",
        "to_email": "keith@durangoconstruction.ca",
        "company": "Durango Construction",
        "segment": "GC",
        "angle_used": "Cold: chasing pain + Lumia + Lumi",
        "subject": "Commercial paint sub for Manitoba",
        "body": (
            "Hi Keith,\n\n"
            "Quick intro — Lio at Ashrah Painting, Winnipeg commercial.\n\n"
            "Most painting subs make your PM chase for status. Calls, missed updates, "
            "dings on finished surfaces at handoff. We do it differently: Lumia auto-"
            "reports daily plus answers your PM on demand. Lumi (our AI estimator) "
            "returns 95%-detailed bids in 24 hours, at least 13% lower than human-"
            "estimated subs.\n\n"
            "Worth 10 minutes to walk you through it?"
        ),
        "cta": "Worth 10 minutes to walk you through it?",
        "signals_used": "No public signals on Durango — generic cold open.",
        "needs_review_flags": [],
    },
    {
        "id": "bonafide-construction-jeff-herlick",
        "to_name": "Jeff",
        "to_email": "jeff@bonafidecs.ca",
        "company": "Bonafide Construction Solutions Ltd",
        "segment": "GC",
        "angle_used": "Cold owner: name on the line",
        "subject": "Painting that doesn't burn your name",
        "body": (
            "Hi Jeff,\n\n"
            "Bonafide's run carries your name. When painting drags or hands over a punch "
            "list, the developer's call is to you, not the painting sub.\n\n"
            "Ashrah Painting holds the schedule. Lumi (our AI estimating agent) returns "
            "a 95%-detailed bid in 24 hours, at least 13% lower than human-estimated subs. "
            "Lumia keeps your PM informed during the job. Pro cleaning at handoff with no "
            "surface damage.\n\n"
            "Worth 15 minutes?"
        ),
        "cta": "Worth 15 minutes?",
        "signals_used": "Bonafide = Jeff Herlick = Owner (likely son of founder per earlier research).",
        "needs_review_flags": [],
    },
    {
        "id": "bonafide-construction-steve-macy",
        "to_name": "Steve",
        "to_email": "steve@bonafidecs.ca",
        "company": "Bonafide Construction Solutions Ltd",
        "segment": "GC",
        "angle_used": "Cold estimator: AI bid 24h, 13% lower",
        "subject": "24-hour painting bids, 13% lower",
        "body": (
            "Hi Steve,\n\n"
            "Quick intro — Lio at Ashrah Painting in Winnipeg.\n\n"
            "You estimate for Bonafide, so you have seen what most painting subs do to a "
            "bid book: a week to come back, the number bloated with estimator overhead. "
            "Your PM is asking why your bid is high.\n\n"
            "Lumi (our AI estimating agent) returns a 95%-detailed bid in 24 hours, at "
            "least 13% lower than human-estimated subs (we don't carry the overhead). Plus "
            "Lumia auto-status during the job and pro cleanup at handoff with no surface "
            "damage.\n\n"
            "Want us added to Bonafide's painting bid list?"
        ),
        "cta": "Want us added to Bonafide's painting bid list?",
        "signals_used": "Steve Macy = Estimator at Bonafide. Pitch Lumi directly.",
        "needs_review_flags": [
            "Stagger 5+ days from Jeff Herlick (same firm — Bonafide).",
        ],
    },
    {
        "id": "tractus-projects-jaret-horbatiuk",
        "to_name": "Jaret",
        "to_email": "jaret@tractusprojects.com",
        "company": "Tractus Projects",
        "segment": "GC",
        "angle_used": "Cold owner: protect named-client reputation",
        "subject": "Painting that protects Tractus's name",
        "body": (
            "Hi Jaret,\n\n"
            "Tractus's portfolio — Planet Fitness Polo Park, the McDonald's locations, "
            "La Roca, Millennium Library — has loud client names. Painting subs that miss "
            "schedules or hand over punch lists put your reputation in the room with theirs.\n\n"
            "Ashrah Painting holds the schedule. Lumi (our AI estimating agent) returns "
            "a 95%-detailed bid in 24 hours, at least 13% lower than human-estimated subs. "
            "Lumia auto-status during execution. Pro cleaning at handoff with no surface "
            "damage.\n\n"
            "Coffee at King Edward sometime?"
        ),
        "cta": "Coffee at King Edward sometime?",
        "signals_used": "Jaret Horbatiuk = Owner of Tractus. Existing Tractus contacts (Chad, Lisa, Joe) are also in queue.",
        "needs_review_flags": [
            "Stagger 7+ days from existing Tractus contacts (Chad, Lisa, Joe). Owner pitch should land last to give them time to internally surface our name first.",
        ],
    },
    {
        "id": "pcl-special-projects-ryland-carriere",
        "to_name": "Ryland",
        "to_email": "rdcarriere@pcl.com",
        "company": "PCL Special Projects",
        "segment": "GC",
        "angle_used": "Cold: SP book = small commercial reno fit",
        "subject": "Painting sub for PCL Special Projects",
        "body": (
            "Hi Ryland,\n\n"
            "PCL's Special Projects book runs on tight commercial reno turnarounds. "
            "Painting is usually where smaller jobs either hold the schedule or eat the "
            "margin — chasing crews, dings on finished surfaces at handoff, slow bids.\n\n"
            "Ashrah Painting fixes all three. Lumi (our AI estimating agent) returns "
            "95%-detailed bids in 24 hours, at least 13% lower than human-estimated subs. "
            "Lumia keeps your PM informed during the job. Pro cleaning with no surface "
            "damage.\n\n"
            "Want us added to PCL Special Projects' painting bid list?"
        ),
        "cta": "Want us added to PCL Special Projects' painting bid list?",
        "signals_used": "PCL Special Projects = small-format commercial reno; Ryland Carriere = SP Manager Winnipeg.",
        "needs_review_flags": [],
    },
    {
        "id": "pretium-projects-justin-bova",
        "to_name": "Justin",
        "to_email": "justin@buildvalue.ca",
        "company": "Pretium Projects",
        "segment": "GC",
        "angle_used": "Cold: VE positioning",
        "subject": "Painting that holds your value engineering",
        "body": (
            "Hi Justin,\n\n"
            "buildvalue.ca tells me Pretium thinks about value engineering carefully. "
            "Painting subs are usually where that thinking gets undone — bloated bids, "
            "slow turnarounds, surface damage on freshly finished work.\n\n"
            "Ashrah Painting runs different. Lumi (our AI estimating agent) returns "
            "95%-detailed bids in 24 hours, at least 13% lower than human-estimated subs. "
            "Lumia keeps your PM informed during execution. Pro cleaning at handoff with "
            "no surface damage.\n\n"
            "Worth 15 minutes for a quick intro?"
        ),
        "cta": "Worth 15 minutes for a quick intro?",
        "signals_used": "Justin Bova = Owner of Pretium Projects. Domain buildvalue.ca = VE positioning.",
        "needs_review_flags": [],
    },

    # ===== Warm drafts added 2026-04-29 (mention Ahmad / past work) =====
    {
        "id": "bockstael-construction-mario-bento",
        "to_name": "Mario",
        "to_email": "mbento@bockstael.com",
        "company": "Bockstael Construction Limited",
        "segment": "GC",
        "angle_used": "Warm estimator: relationship + Lumi update",
        "subject": "Reconnecting — Ashrah Painting",
        "body": (
            "Hi Mario,\n\n"
            "Lio at Ashrah Painting — Ahmad asked me to reach out. We've worked with "
            "Bockstael on past jobs and he wanted me to make sure we stay top of mind on "
            "your bid list.\n\n"
            "A heads-up on what's new since we last bid: Lumi (our AI estimating agent) "
            "now returns 95%-detailed bids in 24 hours, at least 13% lower than human-"
            "estimated subs. Once awarded, Lumia auto-status to your PM daily. Same crews, "
            "same finish quality, faster bids.\n\n"
            "If you have commercial paint scope coming up, I'd love to be back on the bid "
            "list."
        ),
        "cta": "I'd love to be back on the bid list.",
        "signals_used": "Mario Bento = Estimator at Bockstael. Past relationship — Ahmad named.",
        "needs_review_flags": [],
    },
    {
        "id": "bockstael-construction-dan-bockstael",
        "to_name": "Dan",
        "to_email": "dbockstael@bockstael.com",
        "company": "Bockstael Construction Limited",
        "segment": "GC",
        "angle_used": "Warm owner: relationship + scaling",
        "subject": "Catching up — Ashrah Painting",
        "body": (
            "Hi Dan,\n\n"
            "Lio at Ashrah Painting — Ahmad asked me to reach out. We've worked with "
            "Bockstael on past jobs and he wanted to keep us on your radar as we scale "
            "our crew through 2026.\n\n"
            "What's new on our side: Lumi (our AI estimating agent) returns 95%-detailed "
            "bids in 24 hours, at least 13% lower than human-estimated subs. Lumia ops "
            "layer keeps your PM informed during execution with daily auto-status. Same "
            "paint quality, faster bids, fewer surprises.\n\n"
            "Coffee sometime?"
        ),
        "cta": "Coffee sometime?",
        "signals_used": "Dan Bockstael = Owner. Bockstael 110-yr Manitoba builder.",
        "needs_review_flags": [
            "Stagger 5+ days from Mario Bento (same firm).",
        ],
    },
    {
        "id": "concord-projects-marc-b",
        "to_name": "Marc",
        "to_email": "marcb@concordprojects.com",
        "company": "Concord Projects",
        "segment": "GC",
        "angle_used": "Warm estimator: relationship + Lumi update",
        "subject": "Catching up from Ashrah Painting",
        "body": (
            "Hi Marc,\n\n"
            "Lio at Ashrah Painting — Ahmad asked me to reach out. We've worked with "
            "Concord on past jobs.\n\n"
            "A heads-up on what's new: Lumi (our AI estimator) returns 95%-detailed bids "
            "in 24 hours, at least 13% lower than human-estimated subs. Lumia auto-status "
            "during execution. Pro cleaning at handoff with no surface damage.\n\n"
            "If you have commercial paint scope coming up, I'd love to be on the bid list."
        ),
        "cta": "I'd love to be on the bid list.",
        "signals_used": "Marc B = Estimator at Concord Projects. Past relationship.",
        "needs_review_flags": [],
    },
    {
        "id": "concord-projects-nik",
        "to_name": "Nik",
        "to_email": "Nik@concordprojects.com",
        "company": "Concord Projects",
        "segment": "GC",
        "angle_used": "Warm: relationship + Lumi/Lumia update",
        "subject": "Reconnecting — Ashrah Painting",
        "body": (
            "Hi Nik,\n\n"
            "Lio at Ashrah Painting — Ahmad asked me to reach out. We've worked with "
            "Concord on past jobs and he wanted to keep us on your radar.\n\n"
            "Quick update: Lumi (our AI estimator) now returns 95%-detailed bids in 24 "
            "hours, at least 13% lower than human-estimated subs. Plus Lumia auto-status "
            "during execution and pro cleanup at handoff.\n\n"
            "Worth grabbing coffee sometime?"
        ),
        "cta": "Worth grabbing coffee sometime?",
        "signals_used": "Nik = first name only on tracker. Past relationship.",
        "needs_review_flags": [
            "First name only — confirm full name before send.",
            "Stagger 5+ days from Marc B (same firm — Concord).",
        ],
    },
    {
        "id": "graham-construction-greg-richards",
        "to_name": "Greg",
        "to_email": "Greg.Richards@graham.ca",
        "company": "Graham Construction",
        "segment": "GC",
        "angle_used": "Warm PM Manager: relationship + Lumia ops",
        "subject": "Catching up — Ashrah Painting",
        "body": (
            "Hi Greg,\n\n"
            "Lio at Ashrah Painting — Ahmad asked me to reach out. We've worked with "
            "Graham on past jobs.\n\n"
            "A heads-up on what's new since we last ran together: Lumia ops layer now "
            "sends your PM a daily 5:30 PM site report automatically AND lets your PM ask "
            "\"where are you on [unit]?\" anytime. Plus 6-day delay forecasting so you "
            "don't get surprised. Pro cleaning at handoff with no surface damage.\n\n"
            "Worth 15 minutes to walk through it?"
        ),
        "cta": "Worth 15 minutes to walk through it?",
        "signals_used": "Greg Richards = PM Manager at Graham (operations side). Past relationship.",
        "needs_review_flags": [],
    },
    {
        "id": "graham-construction-liberty-bustos",
        "to_name": "Liberty",
        "to_email": "Winnipegbids@graham.ca",
        "company": "Graham Construction",
        "segment": "GC",
        "angle_used": "Warm estimator: relationship + Lumi pitch",
        "subject": "Reconnecting — Ashrah Painting",
        "body": (
            "Hi Liberty,\n\n"
            "Lio at Ashrah Painting — Ahmad asked me to reach out. We've worked with "
            "Graham on past jobs and he wanted us to stay top of mind on your bid list.\n\n"
            "What's new on our side: Lumi (our AI estimator) returns 95%-detailed bids in "
            "24 hours, at least 13% lower than human-estimated subs (we don't carry that "
            "overhead). Lumia auto-status during the job. Pro cleaning at handoff with no "
            "surface damage.\n\n"
            "If you have commercial paint scope coming up, I'd love to be back on the bid "
            "list."
        ),
        "cta": "I'd love to be back on the bid list.",
        "signals_used": "Liberty Bustos = Estimator at Graham, reads Winnipegbids@ alias.",
        "needs_review_flags": [
            "Email is a generic Winnipeg-bids alias — multiple estimators may read it. Address by name to direct it.",
            "Stagger 5+ days from Greg Richards (same firm).",
        ],
    },
    {
        "id": "j5-construction-rucil-evangelista",
        "to_name": "Rucil",
        "to_email": "Rucilj5const@gmail.com",
        "company": "J5 Construction",
        "segment": "GC",
        "angle_used": "Warm: relationship + Lumi/Lumia update",
        "subject": "Catching up — Ashrah Painting",
        "body": (
            "Hi Rucil,\n\n"
            "Lio at Ashrah Painting — Ahmad asked me to reach out. We've worked with J5 "
            "on past jobs and he wanted to keep us on your radar as we scale our painting "
            "crew through 2026.\n\n"
            "What's new: Lumi (our AI estimator) returns 95%-detailed bids in 24 hours, "
            "at least 13% lower than human-estimated subs. Lumia auto-status during "
            "execution. Pro cleaning at handoff with no surface damage.\n\n"
            "If you have commercial paint scope coming up, I'd love to be on the bid list."
        ),
        "cta": "I'd love to be on the bid list.",
        "signals_used": "Rucil Evangelista at J5. Gmail address — small shop. Past relationship.",
        "needs_review_flags": [],
    },

    {
        "id": "winnipeg-building-decorating-darci-lee-tessier",
        "to_name": "Darci-lee Tessier",
        "to_email": "",
        "company": "Winnipeg Building & Decorating Ltd. (WBD)",
        "segment": "GC",
        "angle_used": "Junior estimator: low-pressure intro + AI bid",
        "subject": "Painting bids in 24 hours",
        "body": (
            "Hi Darci-lee,\n\n"
            "Quick intro — Ashrah Painting, Winnipeg commercial. Most painting subs make "
            "estimating slow: week-long turnarounds, bloated numbers.\n\n"
            "Lumi (our AI estimating agent) returns a 95%-detailed bid in 24 hours, at least 13% lower "
            "than human-estimated subs. Plus Lumia auto-status during the job and pro "
            "cleaning at handoff with no surface damage.\n\n"
            "Want us added to WBD's painting bid list?"
        ),
        "cta": "Want us added to WBD's painting bid list?",
        "signals_used": "Darci-lee Tessier = Project Assistant & Estimator at WBD (junior role, most receptive to new sub relationships).",
        "needs_review_flags": [
            "Email domain unclear — verify via WBD switchboard.",
            "Stagger 5+ days from Dale and Matthew."
        ],
    },
]


def main() -> None:
    summary_rows = []
    for d in DRAFTS:
        record = {
            "drafted_at": datetime.now().isoformat(),
            "drafted_for_mission": "60-day BD outreach (2026-04-28 → 2026-06-27)",
            **d,
        }
        path = OUT_DIR / f"{d['id']}.json"
        path.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
        summary_rows.append({
            "id": d["id"],
            "to": f"{d['to_name']} <{d['to_email']}>",
            "company": d["company"],
            "segment": d["segment"],
            "angle": d["angle_used"],
            "subject": d["subject"],
            "body_words": len(d["body"].split()),
            "flags": len(d["needs_review_flags"]),
        })

    (OUT_DIR / "_summary.json").write_text(
        json.dumps(summary_rows, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    print(f"Wrote {len(DRAFTS)} drafts to {OUT_DIR}")
    print(f"\n{'SEG':3}  {'COMPANY':32}  {'TO':22}  {'ANGLE':40}  {'WORDS':>5}  FLAGS  SUBJECT")
    print("-" * 170)
    for r in summary_rows:
        print(f"{r['segment']:3}  {r['company'][:32]:32}  {r['to'].split('<')[0].strip()[:22]:22}  "
              f"{r['angle'][:40]:40}  {r['body_words']:>5}  {r['flags']:>5}  {r['subject']}")


if __name__ == "__main__":
    main()
