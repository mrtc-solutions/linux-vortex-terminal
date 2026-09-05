# VORTEX TERMINAL — INTELLIGENT TERMINAL, OSINT, GIS, SATELLITE, ASSET INTELLIGENCE AND RESULTS WORKSPACE

## CRITICAL FIRST DIRECTIVE

DO NOT IMPLEMENT ANYTHING FROM THIS PROMPT IMMEDIATELY.

FIRST, FULLY UNDERSTAND THE EXISTING VORTEX APPLICATION.

This is an extension of an existing Vortex application.

You MUST treat the existing application as the source of truth.

Before modifying anything:

1. Read the entire repository.
2. Understand the architecture.
3. Understand the frontend.
4. Understand the backend.
5. Understand the terminal.
6. Understand the local AI architecture.
7. Understand the Vortex Agent.
8. Understand the orchestration layer.
9. Understand the Results Window.
10. Understand the Analysis Window.
11. Understand the conversation system.
12. Understand conversation history.
13. Understand the existing popup system.
14. Understand security-tool integrations.
15. Understand report generation.
16. Understand VPN/Secure Network Mode.
17. Understand installation scripts.
18. Understand launchers.
19. Understand Linux/Windows/mobile components.
20. Understand the existing database/storage/session architecture.
21. Understand how devices, targets, sessions and findings are currently represented.

DO NOT MODIFY THE APPLICATION DURING THIS INITIAL AUDIT.

Produce an internal feature/dependency map first.

Only after understanding the application should implementation begin.

---

# 1. PRIMARY OBJECTIVE

Expand the existing Vortex Terminal into an intelligent operational workspace.

The terminal should become more than:

COMMAND → OUTPUT

It should become:

USER
↓
VORTEX TERMINAL
↓
LOCAL AI UNDERSTANDING
↓
TASK CLASSIFICATION
↓
TOOL/AGENT SELECTION
↓
AUTHORIZED EXECUTION
↓
REAL EVIDENCE
↓
ANALYSIS
↓
VERIFICATION
↓
RESULTS
↓
CONVERSATION
↓
REPORT

The terminal should work together with the rest of Vortex rather than becoming a separate application.

---

# 2. DO NOT CHANGE THE EXISTING ARCHITECTURE UNNECESSARILY

The objective is NOT to rebuild Vortex.

Preserve:

* existing terminal
* existing GUI
* existing local AI
* existing agent
* existing orchestration
* existing conversation
* existing results window
* existing analysis window
* existing popup
* existing report system
* existing VPN/network functionality
* existing installation system

Only extend them where necessary.

If something already exists:

TEST IT.

If it works:

PRESERVE IT.

If it partially works:

COMPLETE IT.

If it is broken:

DEBUG IT.

If something is missing:

IMPLEMENT IT.

---

# 3. LOCAL AI MUST POWER THE TERMINAL

Use the existing Vortex Local AI architecture.

The terminal should rely heavily on:

* Ollama
* local LLMs
* Vortex Agent
* model routing
* multi-model reasoning
* fuzzy/confidence evaluation

The local models should assist with:

* command explanation
* command suggestions
* command-output interpretation
* troubleshooting
* tool selection
* OSINT analysis
* GIS analysis
* satellite-data interpretation
* security findings
* report generation
* natural-language conversation

Do not introduce cloud LLM dependencies.

---

# 4. INTELLIGENT TERMINAL COPILOT

Add an intelligent terminal assistant.

The user can type natural language such as:

"Show me network interfaces."

"Analyze this scan."

"Find information about this domain."

"Explain this error."

"Show me the geographic information associated with this authorized asset."

"Analyze the satellite imagery available for this area."

"Generate a report from this assessment."

The local AI should determine what the user means.

It may propose a command/tool.

The user should be able to review it before execution where appropriate.

---

# 5. COMMAND EXPLANATION

For every command where useful, provide:

* command
* purpose
* parameters
* expected behavior
* actual output
* interpretation
* possible next step

Example:

COMMAND:
nmap ...

AI EXPLANATION:

Purpose:
...

Actual result:
...

Interpretation:
...

Do not invent output.

---

# 6. COMMAND HISTORY

Enhance the terminal history system.

Store locally:

* timestamp
* command
* user request
* actual output
* exit code
* selected tool
* AI interpretation
* associated session
* associated authorized target
* findings

Allow:

SEARCH

FILTER

REOPEN

REUSE

EXPORT

The user should be able to revisit previous terminal work.

---

# 7. DEVICE/TARGET SESSION WORKSPACE

Create a concept of:

## VORTEX SESSION

A session represents an authorized assessment or investigation.

A session may contain:

* target
* target type
* authorization status
* commands
* tool output
* findings
* screenshots
* AI analysis
* network information
* GIS information
* satellite information
* reports
* conversation history
* timestamps

Do not automatically assume that every IP address, domain, device or phone number is authorized.

Provide an explicit authorization/assessment context.

---

# 8. RESULTS POPUP

Integrate the existing Results Popup.

Every major terminal operation should be capable of producing:

## OPEN RESULTS

button.

When selected, display a rich results window containing:

* operation
* target
* timestamp
* tool used
* raw output
* structured results
* AI analysis
* confidence
* verification
* findings
* recommendations

The popup should support:

* maximize
* minimize
* resize
* close
* scroll
* copy
* export

Do not duplicate information unnecessarily.

---

# 9. RESULTS POPUP ACTIONS

Depending on the result type, provide contextual buttons such as:

### Explain

Ask the local LLM to explain the result.

### Analyze

Perform deeper local analysis.

### Verify

Run an appropriate verification step where authorized.

### Compare

Compare results from multiple tools/models.

### Report

Generate a report.

### Save

Save evidence to the current session.

### Export

Export the result.

Only display actions that are appropriate to the specific result.

---

# 10. CONVERSATION HISTORY

Integrate terminal activity with the existing Vortex conversation history.

A session should preserve:

USER QUESTION

↓

AI RESPONSE

↓

COMMAND

↓

TOOL

↓

OUTPUT

↓

AI INTERPRETATION

↓

RESULT

↓

FOLLOW-UP

This should allow the user to return to a previous assessment/session and continue working with the existing context.

---

# 11. IMPORTANT SESSION PRINCIPLE

Do NOT interpret session history as persistent unauthorized access.

A Vortex session should preserve:

* evidence
* logs
* findings
* conversation
* configuration
* authorized assessment context

It must NOT automatically preserve unauthorized credentials, authentication secrets or covert access mechanisms.

---

# 12. OSINT WORKSPACE

Add an optional:

## VORTEX OSINT

workspace.

It should support lawful/public-source intelligence gathering.

Potential categories:

* domain information
* DNS information
* WHOIS/RDAP where available
* IP information
* ASN information
* certificate information
* public DNS records
* public web information
* public repositories
* public documents
* public metadata
* public geospatial information
* public breach notifications where legally accessible
* threat-intelligence feeds

Use open-source tools where appropriate.

Before adding GitHub projects:

CHECK:

* repository activity
* license
* dependencies
* security
* installation requirements
* maintenance
* compatibility
* whether the project is actually useful

Do not blindly clone projects.

---

# 13. GIS INTELLIGENCE

Add:

## VORTEX GEOINT / GIS

where technically appropriate.

Potential capabilities:

* map display
* coordinates
* reverse geocoding
* geocoding
* distance calculation
* route visualization
* geographic boundaries
* layers
* markers
* asset locations
* network infrastructure locations where publicly available
* temporal layers
* exported GeoJSON/KML/CSV

The GIS subsystem should integrate with the Results Window.

Example:

RESULT:

Authorized asset

↓

MAP

↓

MARKER

↓

DETAILS

↓

AI EXPLANATION

---

# 14. SATELLITE INTELLIGENCE

Explore integration with legitimate open satellite/geospatial data sources.

Potential functionality:

* satellite imagery visualization
* historical imagery where legally available
* land-cover information
* vegetation information
* change detection
* geographic overlays
* coordinates
* image metadata
* temporal comparison
* authorized asset/site analysis

Prioritize genuinely open/free datasets and open-source tooling.

Do not assume that "open-source software" means "free satellite imagery."

Differentiate:

OPEN-SOURCE SOFTWARE

from

FREE/OPEN DATA

from

COMMERCIAL DATA.

---

# 15. SATELLITE CHANGE DETECTION

Where appropriate, provide:

## CHANGE DETECTION

Example:

IMAGE A
+
IMAGE B

↓

LOCAL ANALYSIS

↓

CHANGES IDENTIFIED

↓

MAP/IMAGE RESULT

↓

NATURAL-LANGUAGE EXPLANATION

The system must clearly identify uncertainty.

Do not allow the AI to confidently claim that a specific object/person/event exists when imagery does not support that conclusion.

---

# 16. GEOLOCATION INTELLIGENCE

For authorized assets and public information, support:

* coordinates
* map positioning
* geographic metadata
* IP geolocation where appropriate
* network geolocation estimates
* public infrastructure locations
* satellite imagery context

Clearly distinguish:

EXACT LOCATION

from

ESTIMATED LOCATION

from

APPROXIMATE LOCATION.

Never present an IP geolocation estimate as a precise physical location.

---

# 17. MOBILE DEVICE / TELECOM INTELLIGENCE

Do NOT implement covert phone tracking.

Do NOT implement:

* OTP interception
* authentication-code interception
* SIM takeover
* call interception
* unauthorized location tracking
* credential theft
* covert surveillance

Instead, support legitimate device-security and authorized telecom diagnostics.

Potential features:

* own-device inventory
* authorized device discovery
* Android debugging where explicitly authorized
* device information
* battery/network diagnostics
* Wi-Fi information
* Bluetooth inventory
* SIM/device configuration information where legitimately accessible
* connectivity diagnostics
* mobile application security testing in controlled environments
* authorized mobile penetration-testing workflows

---

# 18. AUTHENTICATION SECURITY TESTING

Vortex may assist with analyzing authentication mechanisms in authorized environments.

It can:

* explain OTP architecture
* identify authentication flows
* analyze logs
* test rate limiting in a controlled environment
* assess MFA implementation
* identify insecure authentication configuration
* recommend stronger controls

It must NOT capture or steal real users' OTPs or authentication tokens.

For testing, use:

* test accounts
* test OTPs
* controlled environments
* mock authentication systems

---

# 19. DEVICE SECURITY WORKSPACE

Create:

## VORTEX DEVICE INTELLIGENCE

For devices the user owns or is authorized to assess.

Display:

* OS
* hostname
* IP
* interfaces
* services
* software
* ports
* security status
* vulnerabilities
* logs
* device metadata
* last assessment
* findings

Where technically possible, allow the device to be represented as an asset in the GIS workspace.

---

# 20. ASSET GRAPH

Consider implementing:

## VORTEX ASSET GRAPH

Represent:

DEVICE

DOMAIN

IP

NETWORK

SERVICE

USER-OWNED ASSET

LOCATION

VULNERABILITY

APPLICATION

SESSION

as connected nodes.

Example:

DOMAIN
↓
IP
↓
SERVER
↓
PORT
↓
SERVICE
↓
VULNERABILITY

The local LLM can explain relationships in natural language.

---

# 21. NETWORK TOPOLOGY

Add an optional:

## NETWORK MAP

Visualize authorized network assets.

Show:

* devices
* routers
* servers
* services
* connections
* subnets
* ports

The map must be based on actual discovered information.

Do not invent connections.

---

# 22. TOOL DISCOVERY

Arena should investigate appropriate free/open-source projects that can enhance Vortex.

Potential categories:

* GIS
* satellite imagery
* OSINT
* network discovery
* vulnerability assessment
* digital forensics
* Linux diagnostics
* mobile security testing
* asset management
* visualization
* threat intelligence

For every candidate:

CHECK:

1. GitHub repository
2. license
3. maintenance
4. dependencies
5. security
6. compatibility
7. resource requirements
8. offline capability
9. whether it can run on my hardware
10. whether integration is actually worthwhile

Do not add a tool merely because it exists.

---

# 23. TOOL ADAPTER ARCHITECTURE

Do not hard-code every external tool into the terminal.

Create a modular adapter concept:

VORTEX

↓

TOOL REGISTRY

↓

TOOL ADAPTER

↓

TOOL

↓

RAW OUTPUT

↓

NORMALIZER

↓

EVIDENCE

This makes future tool integration easier.

---

# 24. TOOL REGISTRY

Each tool should have metadata:

* name
* version
* purpose
* operating systems
* installation method
* executable path
* license
* capabilities
* dependencies
* input format
* output format
* resource requirements
* authorization requirements

---

# 25. LOCAL AI TOOL SELECTION

The local AI should assist in selecting tools.

Example:

USER:

"I want to understand the services running on my authorized server."

Vortex:

Recommended tool:
Nmap

Reason:
Service discovery.

Then:

EXECUTE

↓

RESULT

↓

AI ANALYSIS

---

# 26. MULTI-TOOL VERIFICATION

For important findings:

TOOL A

↓

RESULT

*

TOOL B

↓

RESULT

↓

VORTEX

↓

COMPARE

↓

LOCAL LLM

↓

FUZZY CONFIDENCE

↓

FINAL RESULT

Do not rely entirely on a single AI response.

---

# 27. EVIDENCE STORE

Create or extend a local evidence system.

Store:

* raw command output
* structured output
* screenshots
* logs
* timestamps
* tool versions
* model analyses
* verification status
* hashes where appropriate

The evidence store should be the source used for reporting.

---

# 28. EVIDENCE INTEGRITY

Where appropriate, calculate hashes for collected evidence.

Example:

Evidence file

↓

SHA-256

↓

Stored with evidence metadata

This allows later verification that evidence has not changed.

---

# 29. AI ANALYSIS OF EVIDENCE

The local LLM receives:

ACTUAL EVIDENCE

not imaginary data.

It can produce:

* explanation
* summary
* interpretation
* potential issue
* confidence
* recommendation

The final result should identify whether something is:

CONFIRMED

LIKELY

POSSIBLE

UNCONFIRMED

---

# 30. FUZZY LOGIC

Use the existing Vortex fuzzy/weighted decision system.

For important findings consider:

* evidence quality
* tool agreement
* model agreement
* model reliability
* verification
* uncertainty
* contradictions

The AI should NOT simply select the answer with the highest confidence claim.

---

# 31. NATURAL-LANGUAGE RESULTS

Every major operation should be explainable in normal language.

Example:

Raw output:

[technical output]

Vortex:

"The operation completed successfully. The system returned..."

The user can then ask:

"Explain that."

"Why?"

"What should I do next?"

"Generate a report."

The local LLM should answer naturally.

---

# 32. REPORT GENERATION

From any completed assessment/session:

Provide:

## GENERATE REPORT

The report should use:

* actual evidence
* verified findings
* timestamps
* tool information
* AI analysis
* confidence
* remediation

Possible reports:

* technical report
* executive summary
* security assessment
* network assessment
* OSINT report
* GIS report
* satellite-analysis report
* device-security report

---

# 33. ONE-CLICK RESULTS WORKFLOW

A typical operation should support:

RUN

↓

RESULTS

↓

OPEN RESULTS

↓

ANALYZE

↓

VERIFY

↓

ASK AI

↓

SAVE EVIDENCE

↓

GENERATE REPORT

This should be a coherent Vortex workflow.

---

# 34. TERMINAL COMMAND PALETTE

Consider adding a command palette.

Examples:

`/scan`

`/analyze`

`/explain`

`/osint`

`/gis`

`/satellite`

`/network`

`/device`

`/report`

`/history`

`/session`

`/evidence`

`/ai`

These are convenience commands, not replacements for the normal Linux shell.

---

# 35. AI COMMAND MODE

Allow:

Natural language:

"Analyze the current system."

Vortex determines:

TASK

↓

TOOLS

↓

COMMANDS

↓

EXECUTION

↓

RESULTS

The user should be able to see what is being done.

Do not hide significant actions from the user.

---

# 36. TERMINAL SAFETY

Before potentially consequential operations:

show:

COMMAND

PURPOSE

TARGET

EXPECTED EFFECT

Then allow:

EXECUTE

or

CANCEL

For harmless commands, avoid unnecessary interruptions.

---

# 37. TARGET AUTHORIZATION

For security operations, maintain:

TARGET

AUTHORIZATION STATUS

SCOPE

SESSION

TIME

USER

The system should distinguish:

AUTHORIZED

from

UNKNOWN

from

NOT AUTHORIZED.

Do not automatically treat an IP address/domain/device as authorized.

---

# 38. SESSION REOPENING

When the user returns to a previous authorized session:

OPEN SESSION

↓

LOAD:

* conversation
* evidence
* results
* reports
* tool history
* GIS layers
* findings

The user can continue analysis.

However, previous evidence must not be confused with current live state.

Clearly display:

HISTORICAL

or

LIVE

where appropriate.

---

# 39. LIVE VS HISTORICAL DATA

Every result should indicate:

LIVE

or

HISTORICAL

and preferably:

TIMESTAMP

SOURCE

TOOL

VERSION

This is especially important for:

* network data
* geolocation
* satellite imagery
* OSINT
* vulnerability information

---

# 40. MOBILE APPLICATION

Where mobile Vortex supports the feature:

provide a mobile-friendly view of:

* sessions
* results
* reports
* maps
* asset inventory
* conversation
* AI analysis

Do not assume Android/iOS can execute every Linux security tool locally.

Where mobile cannot execute a capability:

clearly distinguish:

LOCAL MOBILE

from

DESKTOP/LINUX EXECUTION.

---

# 41. RESOURCE AWARENESS

The primary machine has:

8 GB RAM
4 CPU processors
no discrete GPU

Therefore:

Do not run large numbers of tools and LLMs simultaneously.

Use:

* queues
* worker limits
* model scheduling
* caching
* sequential execution
* fallback models

GIS/satellite processing can also be resource intensive.

Use lightweight processing by default.

---

# 42. OFFLINE FUNCTIONALITY

After installation, preserve local functionality without Internet where possible.

Offline:

✓ terminal

✓ local LLM

✓ local analysis

✓ previous evidence

✓ reports

✓ local GIS data

✓ installed tools

Online-only functions should clearly display:

INTERNET REQUIRED

---

# 43. GITHUB TOOL RESEARCH

Before integrating any new GitHub project:

inspect:

* repository
* README
* LICENSE
* releases
* dependencies
* open issues
* recent commits
* installation procedure
* supported OS
* resource requirements
* security concerns

Do not automatically trust a GitHub repository simply because it is popular.

Do not integrate abandoned or suspicious projects without justification.

---

# 44. OPEN-SOURCE LICENSING

For every external project:

record:

PROJECT

LICENSE

VERSION

SOURCE

INTEGRATION METHOD

Keep required attribution and license information.

Do not remove another project's copyright/license notices.

Do not present third-party code as entirely original Vortex code.

---

# 45. INSTALLATION MANAGER

If new tools are added, integrate them into the existing Vortex dependency manager.

Flow:

CHECK

↓

ALREADY INSTALLED?

YES
→ VERIFY

NO
→ INSTALL

↓

VERIFY

↓

REGISTER

↓

TEST

Do not download unnecessary duplicates.

---

# 46. TOOL HEALTH

Create:

## VORTEX TOOL HEALTH

Example:

Git
✓

Ollama
✓

Nmap
✓

GIS Engine
✓

OSINT Tool
✓

Satellite Data Provider
✓

Python
✓

Docker
✓

If unavailable:

show the exact problem.

---

# 47. TERMINAL DASHBOARD

Consider adding a lightweight information panel:

SYSTEM

CPU
RAM
DISK
NETWORK

AI

MODEL
RAM
STATUS
LATENCY

SESSION

TARGET
STATUS
DURATION

TOOLS

AVAILABLE
FAILED
UPDATING

VPN

CONNECTED
STATUS

This must not interfere with the existing terminal.

---

# 48. RESULTS SEARCH

Allow the user to search previous results by:

* session
* target
* date
* tool
* finding
* severity
* location
* keyword

---

# 49. CROSS-LAYER SEARCH

A powerful feature:

## VORTEX GLOBAL SEARCH

Search across:

* terminal history
* conversation
* evidence
* findings
* reports
* sessions
* assets
* GIS data
* tool results

Example:

Search:

`192.168.1.20`

Vortex returns all authorized sessions/results where that asset appeared.

---

# 50. AI MEMORY

Do not create uncontrolled permanent AI memory.

Instead maintain structured local context:

* current session
* previous relevant evidence
* user request
* tool output
* findings

Allow the user to clear session data.

---

# 51. PRIVACY

Keep sensitive data local whenever possible.

Do not automatically upload:

* terminal output
* source code
* credentials
* authentication data
* private reports
* network information
* device information

to external services.

---

# 52. NO SECRET COLLECTION

Never build functionality whose purpose is to collect:

* passwords
* OTPs
* authentication tokens
* private keys
* session cookies

from people or systems without authorization.

For security testing, use controlled test credentials/tokens.

---

# 53. RESULTS POPUP + CONVERSATION INTEGRATION

The Results Popup should include:

## ASK VORTEX AI

The user can click it and ask:

"What does this mean?"

"Is this serious?"

"Explain the evidence."

"Compare these results."

"Generate a report."

The local LLM receives the relevant evidence automatically.

---

# 54. REPORT BUTTON EVERYWHERE

Where technically appropriate, add:

## GENERATE REPORT

to:

* scan results
* network results
* OSINT results
* GIS results
* satellite results
* device assessments
* session summaries

Do not generate separate unrelated report systems.

Use one Vortex reporting engine.

---

# 55. VORTEX INTELLIGENCE PIPELINE

The final architecture should resemble:

USER

↓

VORTEX TERMINAL / GUI

↓

CONVERSATION

↓

TASK CLASSIFIER

↓

LOCAL MODEL ROUTER

↓

VORTEX AGENT

↓

TOOL SELECTION

↓

AUTHORIZED EXECUTION

↓

EVIDENCE

↓

RESULTS WINDOW

↓

LOCAL LLM ANALYSIS

↓

MULTI-MODEL VERIFICATION

↓

FUZZY CONFIDENCE

↓

FINAL SYNTHESIS

↓

CONVERSATION

*

REPORT

*

SESSION HISTORY

*

GIS/ASSET VISUALIZATION

---

# 56. DO NOT MAKE THE TERMINAL DANGEROUS BY DEFAULT

The objective is an intelligent authorized security workstation.

Do not implement:

* OTP theft
* covert phone tracking
* credential theft
* unauthorized persistence
* unauthorized access
* interception of communications
* covert surveillance

Instead provide legitimate equivalents for:

* owned devices
* authorized targets
* controlled labs
* security assessments
* defensive investigations
* public OSINT
* GIS
* satellite analysis
* network diagnostics
* device security

---

# 57. TESTING

After implementation:

BUILD

↓

INSTALL

↓

LAUNCH

↓

TEST

↓

DEBUG

↓

REBUILD

↓

RETEST

Test:

✓ terminal

✓ command execution

✓ command analysis

✓ local AI

✓ model routing

✓ agent

✓ tool registry

✓ OSINT

✓ GIS

✓ satellite integration

✓ asset management

✓ results popup

✓ conversation history

✓ evidence store

✓ report generation

✓ network visualization

✓ session reopening

✓ installation

✓ launchers

✓ existing functionality

---

# 58. FAILURE TESTING

Test:

* Ollama unavailable
* model unavailable
* tool unavailable
* network unavailable
* GIS provider unavailable
* satellite data unavailable
* malformed tool output
* low RAM
* insufficient disk
* invalid target
* unauthorized target
* interrupted command
* failed command
* timeout

Vortex must fail gracefully.

---

# 59. SANDBOX VALIDATION

After implementation, actually install and run the application in the available sandbox.

Do not merely inspect source code.

Use controlled/safe test data and targets.

Verify the actual behavior.

---

# 60. FINAL 10/10 VALIDATION

Create a test matrix.

Do NOT fabricate results.

A test can only be marked:

PASS

if it was actually tested successfully.

If a platform-specific capability cannot be tested in the sandbox:

mark:

NOT TESTABLE IN SANDBOX

Do not mark it PASS.

For failures:

IDENTIFY

↓

FIX

↓

REBUILD

↓

RETEST

↓

REGRESSION TEST

---

# 61. FINAL AUDIT REPORT

At completion provide:

1. Existing architecture discovered
2. Existing features preserved
3. Existing features repaired
4. New features added
5. Tools integrated
6. GitHub projects considered
7. Licenses checked
8. Ollama status
9. Local model status
10. Terminal enhancements
11. OSINT capabilities
12. GIS capabilities
13. Satellite capabilities
14. Asset intelligence
15. Results popup
16. Conversation integration
17. Evidence system
18. Report generation
19. Session history
20. Network visualization
21. Security controls
22. Installation status
23. Linux testing
24. Windows testing
25. Mobile testing where possible
26. Bugs discovered
27. Bugs fixed
28. Tests performed
29. Tests passed
30. Tests not testable
31. Remaining limitations

---

# 62. FINAL PRINCIPLE

Do not build a collection of unrelated tools.

Build:

# ONE VORTEX INTELLIGENCE WORKSPACE

The terminal is the operational center.

The local LLM is the reasoning layer.

The Vortex Agent is the orchestrator.

Security/GIS/OSINT/satellite tools provide actual data.

The evidence store preserves reality.

The Results Window displays technical results.

The conversation layer explains them naturally.

The fuzzy engine evaluates competing conclusions.

The reporting engine turns verified evidence into reports.

The session system preserves the user's legitimate work.

The GIS layer provides geographic context.

The asset graph connects everything.

The entire system should feel like one coherent application.

MOST IMPORTANT:

FIRST UNDERSTAND THE EXISTING VORTEX APPLICATION.

THEN PLAN.

THEN IMPLEMENT.

THEN INSTALL.

THEN TEST.

THEN DEBUG.

THEN REGRESSION TEST.

DO NOT BREAK EXISTING FUNCTIONALITY.

DO NOT FABRICATE TEST RESULTS.

DO NOT CLAIM SUCCESS WITHOUT ACTUAL VALIDATION.

Only declare the implementation complete when the requested functionality has genuinely been implemented and tested as far as the available environment permits.
