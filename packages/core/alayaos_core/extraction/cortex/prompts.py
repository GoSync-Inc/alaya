"""Canonical few-shot examples for the Cortex classifier system prompt.

This block is appended to the classifier system prompt to pad the total prompt
above Haiku 4.5's 4096-token cache eligibility minimum (with margin — target is
len(assembled_prompt) // 4 >= 4200, i.e. >= 16800 chars total).

Rules for editing this file:
- Content must be deterministic: no datetime.now(), no os.environ, no random.
- Must cover all 13 core entity types and a representative sample of predicates.
- Domain mix: meeting transcripts, Slack messages, document paragraphs.
- After any edit, verify: len(assembled_prompt) // 4 >= 4200.
"""

CANONICAL_EXAMPLES_BLOCK = """
================================================================================
CANONICAL CLASSIFICATION EXAMPLES
================================================================================

The following examples show how to score workplace text across all domains.
Study each chunk and the expected classification rationale before scoring.

--------------------------------------------------------------------------------
EXAMPLE 1 — Meeting transcript (project + decision)
--------------------------------------------------------------------------------
Chunk:
  "We reviewed the Q2 roadmap in today's sprint planning. Maria confirmed that
   the authentication module will be delivered by June 15th. The team agreed to
   deprioritize the reporting dashboard to keep the deadline. James will own the
   auth milestone going forward."

Entity types present:
  - meeting (sprint planning session)
  - project (Q2 roadmap, authentication module, reporting dashboard)
  - person (Maria, James)
  - task (deliver authentication module)
  - decision (deprioritize reporting dashboard)

Predicates present:
  - deadline: June 15th for authentication module
  - owner: James owns the auth milestone
  - status: reporting dashboard deprioritized
  - decision: team agreed to deprioritize dashboard

Expected scores:
  project: 0.85 — roadmap, milestone, sprint planning
  decision: 0.80 — explicit team agreement, deprioritization choice
  people: 0.60 — Maria, James assigned/mentioned
  strategic: 0.30 — Q2 roadmap has light strategic flavour
  engineering: 0.20 — authentication module is technical
  risk: 0.10 — implicit deadline pressure
  knowledge: 0.0
  customer: 0.0
  smalltalk: 0.0

--------------------------------------------------------------------------------
EXAMPLE 2 — Slack message (smalltalk + people)
--------------------------------------------------------------------------------
Chunk:
  "Hey everyone! 🎉 Just wanted to say congrats to Sarah on her promotion to
   Senior Engineer. She's been crushing it this past year. Let's grab lunch
   Friday to celebrate!"

Entity types present:
  - person (Sarah)
  - event (team lunch)

Predicates present:
  - title: Senior Engineer (new role for Sarah)
  - role: promotion

Expected scores:
  smalltalk: 0.85 — casual celebration, social event
  people: 0.70 — promotion, org structure change
  project: 0.0
  decision: 0.10 — promotion implies a decision was made
  strategic: 0.0
  risk: 0.0
  engineering: 0.10 — Senior Engineer role is technical
  knowledge: 0.0
  customer: 0.0

Note: smalltalk >= 0.8 but people = 0.70 >= 0.4, so this IS crystal (mixed signal).

--------------------------------------------------------------------------------
EXAMPLE 3 — Document paragraph (knowledge + engineering)
--------------------------------------------------------------------------------
Chunk:
  "## API Rate Limiting
   All endpoints enforce a default rate limit of 100 requests per minute per
   API key. Clients that exceed this limit receive a 429 Too Many Requests
   response. To request a higher limit, submit a support ticket with your
   use case. Retry logic should implement exponential backoff starting at 1
   second with a maximum of 32 seconds."

Entity types present:
  - document (API documentation)
  - tool (API, support ticket system)
  - process (rate limiting, retry logic)

Predicates present:
  - description: rate limit policy described

Expected scores:
  knowledge: 0.90 — how-to documentation, best practices
  engineering: 0.80 — API, HTTP status codes, backoff algorithm
  customer: 0.30 — developers/clients as end-users
  project: 0.0
  decision: 0.0
  strategic: 0.0
  risk: 0.10 — implicit risk of exceeding limits
  people: 0.0
  smalltalk: 0.0

--------------------------------------------------------------------------------
EXAMPLE 4 — Slack message (risk + project)
--------------------------------------------------------------------------------
Chunk:
  "FYI the staging deployment is completely blocked right now. The Postgres
   migration script failed halfway and left the schema in a broken state.
   I'm rolling back but we won't be able to deploy the v2.3 release today.
   Will update once staging is stable again."

Entity types present:
  - tool (Postgres, deployment pipeline)
  - project (v2.3 release)
  - task (rollback, stabilize staging)

Predicates present:
  - status: staging is blocked, rollback in progress
  - blocked_by: v2.3 release blocked by migration failure
  - deadline: implicit — today's release target missed

Expected scores:
  risk: 0.95 — blocker, broken state, explicit incident
  engineering: 0.85 — Postgres, schema migration, deployment
  project: 0.70 — release schedule impacted
  decision: 0.20 — rollback decision mentioned
  knowledge: 0.0
  strategic: 0.0
  customer: 0.0
  people: 0.0
  smalltalk: 0.0

--------------------------------------------------------------------------------
EXAMPLE 5 — Meeting transcript (strategic + decision)
--------------------------------------------------------------------------------
Chunk:
  "The board reviewed the annual OKR progress. We are at 62% on our North Star
   metric — reaching 10,000 active enterprise customers by year end. After
   discussion, the leadership team decided to increase the sales headcount in
   EMEA by 20% in Q3 to accelerate growth. The North Star deadline remains
   December 31st."

Entity types present:
  - north_star (10,000 active enterprise customers)
  - goal (OKR metric at 62%)
  - meeting (board meeting)
  - decision (increase EMEA headcount)
  - team (leadership team, EMEA sales)

Predicates present:
  - deadline: December 31st for North Star
  - status: 62% OKR progress
  - decision: increase EMEA headcount 20%
  - member_of: leadership team made the decision

Expected scores:
  strategic: 0.95 — OKR, North Star, board-level discussion
  decision: 0.85 — explicit leadership decision
  people: 0.50 — headcount, team structure
  project: 0.30 — Q3 initiative framing
  customer: 0.40 — enterprise customer target
  risk: 0.10 — implicit risk of missing North Star
  knowledge: 0.0
  engineering: 0.0
  smalltalk: 0.0

--------------------------------------------------------------------------------
EXAMPLE 6 — Document paragraph (knowledge + process)
--------------------------------------------------------------------------------
Chunk:
  "## Onboarding Checklist for New Engineers
   1. Complete IT security training within 48 hours of start date.
   2. Request access to GitHub, AWS, and Jira via the IT portal.
   3. Schedule 1:1s with your team lead and three senior engineers in week 1.
   4. Read the Engineering Handbook (Notion link in #eng-resources).
   5. Set up your local development environment using the setup script in the
      onboarding repository."

Entity types present:
  - document (Engineering Handbook, onboarding repo)
  - process (onboarding checklist)
  - tool (GitHub, AWS, Jira, Notion, IT portal)
  - person (new engineers, team lead)

Predicates present:
  - deadline: 48 hours for security training
  - member_of: new engineer joins team
  - reports_to: 1:1 with team lead

Expected scores:
  knowledge: 0.92 — checklist, how-to, best practices
  engineering: 0.60 — dev environment, GitHub, AWS
  people: 0.40 — onboarding, 1:1s, team lead
  process: 0.75 — structured checklist workflow
  project: 0.10 — setup tasks
  decision: 0.0
  strategic: 0.0
  customer: 0.0
  risk: 0.10 — implicit risk of missing training deadline
  smalltalk: 0.0

--------------------------------------------------------------------------------
EXAMPLE 7 — Slack message (pure smalltalk — NOT crystal)
--------------------------------------------------------------------------------
Chunk:
  "Morning everyone! Hope you all had a great weekend. I finally watched that
   show everyone was talking about — totally worth the hype. Anyone up for
   coffee at 10?"

Entity types present:
  None of the 13 core types — this is casual social chat.

Predicates present:
  None of the 21 core predicates.

Expected scores:
  smalltalk: 0.98 — pure casual conversation
  people: 0.10 — "everyone" mentioned loosely
  project: 0.0
  decision: 0.0
  strategic: 0.0
  risk: 0.0
  engineering: 0.0
  knowledge: 0.0
  customer: 0.0

Note: smalltalk = 0.98 >= 0.8 AND max_non_smalltalk = 0.10 < 0.4 → NOT crystal. Skip.

--------------------------------------------------------------------------------
EXAMPLE 8 — Meeting transcript (engineering + risk)
--------------------------------------------------------------------------------
Chunk:
  "In today's architecture review we discussed migrating the monolith to a
   microservices architecture over the next six months. The main concern is
   data consistency across service boundaries — we'll need distributed
   transactions or an event-sourcing approach. The team agreed to prototype
   both approaches in a dedicated spike project before committing."

Entity types present:
  - meeting (architecture review)
  - project (migration project, spike project)
  - process (event-sourcing, distributed transactions)
  - decision (prototype before committing)
  - topic (microservices architecture)

Predicates present:
  - deadline: six months for migration
  - decision: prototype both approaches first
  - status: planning phase
  - depends_on: decision depends on spike results

Expected scores:
  engineering: 0.92 — microservices, architecture, distributed transactions
  risk: 0.70 — data consistency concern, explicit risk mention
  decision: 0.65 — explicit team decision to prototype
  project: 0.60 — migration project, spike project
  strategic: 0.30 — six-month horizon, architectural commitment
  knowledge: 0.20 — architecture patterns discussed
  people: 0.0
  customer: 0.0
  smalltalk: 0.0

--------------------------------------------------------------------------------
EXAMPLE 9 — Document paragraph (customer + strategic)
--------------------------------------------------------------------------------
Chunk:
  "Customer Satisfaction Report — Q1 2024
   Net Promoter Score dropped from 72 to 58 this quarter, driven primarily by
   support response time degradation. Enterprise customers in the APAC region
   reported an average ticket resolution time of 48 hours versus our SLA target
   of 8 hours. The CX team has proposed hiring three additional support
   engineers and implementing an AI-assisted triage system."

Entity types present:
  - document (Q1 satisfaction report)
  - team (CX team)
  - goal (NPS target, SLA target)
  - decision (proposed hiring, AI triage)
  - person (enterprise customers, APAC region)

Predicates present:
  - status: NPS dropped from 72 to 58
  - deadline: 8-hour SLA target (missed)
  - decision: hire three engineers, implement AI triage
  - priority: high — SLA breach

Expected scores:
  customer: 0.92 — NPS, SLA, customer satisfaction report
  strategic: 0.65 — quarterly review, organizational decision
  risk: 0.70 — SLA breach, NPS decline
  people: 0.40 — hiring proposal, CX team
  decision: 0.60 — proposed remediation steps
  engineering: 0.20 — AI triage system
  project: 0.20 — hiring initiative
  knowledge: 0.10 — report documents findings
  smalltalk: 0.0

--------------------------------------------------------------------------------
EXAMPLE 10 — Slack message (project + people)
--------------------------------------------------------------------------------
Chunk:
  "Update on Project Phoenix: we closed the Series A term sheet today. The
   product team is officially growing — we're adding 4 engineers and 1 PM
   starting next month. Anna will lead the new backend squad. Kickoff meeting
   is scheduled for Monday."

Entity types present:
  - project (Project Phoenix)
  - person (Anna)
  - meeting (kickoff meeting)
  - team (backend squad)
  - decision (hiring approved, Anna leads squad)
  - event (kickoff meeting Monday)

Predicates present:
  - owner: Anna leads backend squad
  - member_of: 4 engineers + 1 PM join project
  - deadline: kickoff Monday, team starts next month
  - status: Series A closed
  - decision: Anna leads new squad

Expected scores:
  project: 0.88 — project update, milestone
  people: 0.80 — team expansion, Anna's leadership
  decision: 0.65 — structural decisions made
  strategic: 0.50 — Series A, organizational growth
  engineering: 0.20 — backend squad is technical
  risk: 0.0
  knowledge: 0.0
  customer: 0.10 — implicit — Series A tied to growth/customers
  smalltalk: 0.05 — minor casual tone

--------------------------------------------------------------------------------
EXAMPLE 11 — Document paragraph (process + engineering)
--------------------------------------------------------------------------------
Chunk:
  "## Incident Response Runbook — P0 Severity
   When a P0 incident is declared:
   1. Page the on-call engineer via PagerDuty immediately.
   2. Create an incident channel in Slack (#inc-YYYYMMDD-short-description).
   3. Assign an Incident Commander (IC) within 5 minutes.
   4. Begin a blameless postmortem document within 24 hours of resolution.
   5. Update the status page (status.example.com) with a customer-facing message.
   6. Escalate to VP Engineering if not resolved within 60 minutes."

Entity types present:
  - process (incident response runbook)
  - document (runbook, postmortem)
  - tool (PagerDuty, Slack, status page)
  - person (IC, on-call engineer, VP Engineering)
  - event (P0 incident)

Predicates present:
  - deadline: 5 min for IC, 60 min for escalation, 24 hours for postmortem
  - owner: Incident Commander owns resolution
  - reports_to: IC reports to VP Engineering on escalation
  - role: Incident Commander

Expected scores:
  knowledge: 0.88 — runbook, process documentation
  engineering: 0.75 — on-call, incident management, technical escalation
  risk: 0.70 — P0 incident is highest risk level
  process: 0.80 — detailed step-by-step workflow
  people: 0.30 — roles assigned
  project: 0.10 — incident as a mini-project
  decision: 0.15 — escalation decision tree
  strategic: 0.0
  customer: 0.20 — status page update for customers
  smalltalk: 0.0

--------------------------------------------------------------------------------
EXAMPLE 12 — Meeting transcript (decision + strategic)
--------------------------------------------------------------------------------
Chunk:
  "We held the quarterly business review with the executive team. The key
   decision coming out of this session: we will sunset the legacy v1 API on
   September 30th and require all partners to migrate to v2 by that date.
   Marketing will send deprecation notices by end of this week. The strategic
   rationale is reducing infrastructure cost by 30% and focusing engineering
   bandwidth on the new platform."

Entity types present:
  - meeting (quarterly business review)
  - decision (sunset v1 API, migration deadline)
  - project (v2 API migration, new platform)
  - document (deprecation notices)
  - tool (v1 API, v2 API)
  - team (executive team, marketing, engineering)

Predicates present:
  - deadline: September 30th for API sunset
  - deadline: end of week for deprecation notices
  - decision: sunset v1 API
  - status: v2 becomes required
  - budget: 30% infrastructure cost reduction target

Expected scores:
  decision: 0.92 — explicit executive decision with named date
  strategic: 0.85 — business rationale, long-term platform direction
  project: 0.65 — migration project, new platform
  engineering: 0.55 — API versioning, infrastructure
  risk: 0.40 — partner migration risk, tight deadline
  customer: 0.30 — partner impact, deprecation notices
  knowledge: 0.10 — decision documented for reference
  people: 0.0
  smalltalk: 0.0

--------------------------------------------------------------------------------
EXAMPLE 13 — Slack message (people + decision)
--------------------------------------------------------------------------------
Chunk:
  "Just got the news — David Chen is leaving the company. His last day is
   Friday. He's been an incredible contributor to the data platform for three
   years. We'll start the backfill search immediately. Interim: Tom Nguyen
   will cover his responsibilities until we hire."

Entity types present:
  - person (David Chen, Tom Nguyen)
  - team (data platform team)
  - decision (immediate backfill, Tom covers interim)
  - project (data platform)

Predicates present:
  - status: David Chen leaving
  - deadline: last day Friday
  - role: Tom Nguyen covers interim responsibilities
  - reports_to: implicit org structure change

Expected scores:
  people: 0.92 — departure, backfill, org change
  decision: 0.70 — interim coverage, backfill decision made
  risk: 0.60 — key person dependency, knowledge transfer risk
  project: 0.30 — data platform continuity
  strategic: 0.20 — talent management has strategic impact
  engineering: 0.20 — data platform is technical
  knowledge: 0.10 — implicit knowledge transfer concern
  customer: 0.0
  smalltalk: 0.15 — tribute/appreciation tone

--------------------------------------------------------------------------------
EXAMPLE 14 — Document paragraph (goal + strategic)
--------------------------------------------------------------------------------
Chunk:
  "FY2025 North Star: Become the default AI memory layer for enterprise teams.
   Key results:
   - 500 enterprise workspaces by Q4 (currently 87)
   - 95% of active workspaces with weekly extraction runs (currently 61%)
   - Net Revenue Retention > 120% (currently 108%)
   The primary strategic bets are: (1) MCP-native integrations with the top 10
   enterprise tools, (2) SOC-2 Type II certification by Q2, and (3) expanding
   the partner ecosystem to 25 certified connectors by year end."

Entity types present:
  - north_star (AI memory layer for enterprise teams)
  - goal (500 workspaces, 95% weekly extraction, NRR > 120%)
  - project (MCP integrations, SOC-2 certification, connector ecosystem)
  - document (FY2025 strategy doc)

Predicates present:
  - deadline: Q4 for workspace target, Q2 for SOC-2, year end for connectors
  - status: current vs target metrics
  - description: north_star described
  - priority: three strategic bets listed

Expected scores:
  strategic: 0.97 — North Star, OKRs, FY plan, strategic bets
  project: 0.60 — named initiatives
  engineering: 0.35 — MCP, certifications, connectors are technical
  customer: 0.40 — enterprise workspace targets
  decision: 0.30 — strategic bets represent choices
  risk: 0.15 — gap between current and target metrics
  knowledge: 0.10 — documented for the org
  people: 0.0
  smalltalk: 0.0

--------------------------------------------------------------------------------
EXAMPLE 15 — Slack message (task + project)
--------------------------------------------------------------------------------
Chunk:
  "Quick task update: I've finished the PR for the vector search refactor
   (#1247). It's ready for review — @alice @bob please take a look when you
   get a chance. Targeting merge by Wednesday so we can close the sprint on
   time. There's one open question about the embedding dimension — tagged it
   in the PR comments."

Entity types present:
  - task (PR review, vector search refactor)
  - project (sprint)
  - person (alice, bob)
  - topic (embedding dimension question)

Predicates present:
  - status: PR ready for review
  - deadline: merge by Wednesday
  - owner: alice and bob are reviewers
  - depends_on: sprint close depends on this merge

Expected scores:
  project: 0.82 — sprint, PR, milestone tracking
  engineering: 0.80 — PR, vector search, refactor, embedding
  decision: 0.20 — open question about embedding dimension
  people: 0.30 — alice and bob tagged
  risk: 0.15 — blocking sprint close
  knowledge: 0.10 — technical question documented
  strategic: 0.0
  customer: 0.0
  smalltalk: 0.05 — casual "when you get a chance" phrasing

================================================================================
END OF CANONICAL EXAMPLES
================================================================================
"""
