VORTEX — HELP & ABOUT FEATURES ONLY

Read and understand the entire VORTEX application and existing codebase before making any changes.

IMPORTANT SCOPE RESTRICTION

For this task, I need you to implement ONLY TWO FEATURES:

1. A comprehensive Help button/page/panel.
2. A comprehensive About button/page/panel.

Do not modify, refactor, replace, redesign, or otherwise alter any other functionality.

This is a real application. Existing functionality must remain exactly as it currently works.

---

1. FIRST — AUDIT THE EXISTING APPLICATION

Before coding:

- Inspect the entire repository.
- Understand the existing frontend/UI architecture.
- Identify the current navigation/menu/settings structure.
- Determine the most appropriate location for Help and About.
- Understand the existing styling/design system.
- Identify how dialogs, modals, pages, panels, routing, and navigation are currently implemented.
- Check existing tests related to the UI.

Do not immediately start changing code.

The goal is to integrate Help and About naturally into the existing VORTEX interface rather than introducing an unrelated UI design.

---

2. HELP FEATURE

Add a clearly visible Help button.

The Help interface should provide a detailed, practical explanation of how to use VORTEX.

It should explain the application to both beginners and experienced users.

Help should explain at least:

Getting Started

Explain:

- what VORTEX is;
- what it is designed to do;
- how to start using it;
- how the main interface works;
- how to submit a natural-language request;
- how VORTEX interprets requests.

Natural-Language Interaction

Explain that users can communicate with VORTEX using ordinary English.

Provide examples such as:

«"Check my system health."»

«"Find what is consuming CPU."»

«"Check whether a service is running."»

«"Analyze this authorized target."»

Clearly explain the difference between asking for information and requesting actual execution.

---

3. EXPLAIN REAL COMMAND EXECUTION

This is extremely important.

Clearly tell users that VORTEX is a real operational application, not merely a chatbot that gives hypothetical commands.

Explain that when an operation is authorized and permitted, VORTEX can execute actual commands and tools on the system through its controlled execution architecture.

Explain that results are based on observed execution results rather than fabricated responses.

Do NOT exaggerate capabilities.

Do NOT claim a feature exists if it does not actually exist.

Use the application's actual architecture as the source of truth.

---

4. EXPLAIN VORTEX'S SAFETY ARCHITECTURE

The Help section should explain, in understandable language, the important protection mechanisms already present in the application.

Where applicable, explain:

- Planner;
- Orchestration;
- Agent Council;
- Guardian;
- risk policies;
- engagements;
- scope controls;
- execution authority;
- tool registry;
- observed evidence;
- verification;
- task engine;
- STOP ALL;
- audit logging;
- offline mode;
- privacy mode;
- lab mode;
- sandbox capabilities.

Do not invent technical capabilities.

Read the actual implementation and describe what is genuinely available.

---

5. EXPLAIN TOOL AVAILABILITY

Explain that VORTEX does not pretend that tools are installed when they are not.

If a required tool is missing, VORTEX should report it as unavailable rather than fabricate successful execution.

Explain the meaning of statuses such as:

- Available;
- Unavailable;
- Missing;
- Not implemented;
- Requires dependency;
- Requires authorization;
- Requires engagement/scope.

Use the application's actual terminology where possible.

---

6. CYBERSECURITY USAGE WARNING

The Help section must contain a prominent authorized-use warning.

Explain clearly:

«VORTEX is intended for authorized cybersecurity testing, Linux administration, research, education, and controlled laboratory environments.»

Tell users:

«Only test systems, networks, applications, accounts, files, and infrastructure that you own or have explicit permission to assess.»

Explain that unauthorized access, scanning, exploitation, credential attacks, or interference with third-party systems may be illegal and harmful.

Do not provide instructions for bypassing VORTEX's authorization or safety mechanisms.

---

7. HELP — TROUBLESHOOTING

Include a useful troubleshooting section covering the actual application's common situations.

Where applicable explain:

"A tool says UNAVAILABLE"

Explain how the user can check dependencies/tool availability.

"A command did not execute"

Explain that the user should inspect the reported error, permissions, scope, and policy.

"An AI agent is unavailable"

Explain that VORTEX honestly reports unavailable agents rather than pretending they responded.

"A task is still running"

Explain the task/session controls available in the actual application.

"I need to stop everything"

Explain the STOP ALL functionality if it exists in the current implementation.

"The application reports an error"

Explain where users can find relevant diagnostic information.

Do not invent troubleshooting commands. Use commands that actually exist in the application.

---

8. HELP — COMMAND/FEATURE REFERENCE

Where appropriate, include a concise reference to the application's actual CLI commands and major features.

Only document commands that have been verified against the current codebase.

For example, if still valid:

./vortex --help
./vortex doctor --json
./vortex health --json
./vortex tools
./vortex agents --json
./vortex deps --json
./vortex sandbox --json
./vortex db integrity

Do not document commands that do not actually work.

---

9. HELP — SECURITY TERMINOLOGY

Include a simple explanation of important VORTEX terminology, such as:

- Agent;
- Agent Council;
- Orchestration;
- Planner;
- Guardian;
- Risk Policy;
- Engagement;
- Scope;
- Tool;
- Execution;
- Evidence;
- Verification;
- Task;
- Session;
- Sandbox;
- Audit;
- Offline Mode;
- Privacy Mode;
- Lab Mode.

Keep explanations understandable.

---

10. ABOUT FEATURE

Add a clearly visible About button.

The About section should explain:

VORTEX

Verified Orchestration, Reasoning, Testing, Execution & eXperience

Describe VORTEX as a:

Linux-native, AI-assisted authorized cybersecurity and Linux operations workbench.

Use the application's actual capabilities rather than marketing claims.

---

11. DEVELOPER INFORMATION

The About section should identify the developer as:

Francis Fweta

Describe him accurately as:

Cybersecurity Specialist and technology professional.

Do not invent employment history, awards, qualifications, certifications, or achievements that are not already verified in the application/repository.

The user specifically wants the About section to mention professional IT certifications/training including:

- CCNA;
- CompTIA Security+;
- and other IT-related certifications/training.

Where appropriate, mention that these include training/certification obtained through eSkills Academy in collaboration with CompTIA.

However, do not fabricate certification numbers, dates, grades, or other details.

---

12. LICENSE INFORMATION

The About section must explain the actual VORTEX software license.

IMPORTANT:

Do not guess the license.

Inspect the repository for:

- LICENSE;
- package metadata;
- NOTICE;
- README;
- dependency licensing information.

Use the actual project's license.

If the application is distributed under a specific open-source license, clearly state it.

Also explain that VORTEX incorporates or interacts with third-party open-source software where applicable and that those components retain their respective licenses.

Provide appropriate attribution based on the repository's actual NOTICE/license files.

Do not falsely claim that every dependency uses the same license as VORTEX.

---

13. ABOUT — OPEN-SOURCE / FREE SOFTWARE

Where factually correct, explain the project's commitment to free/open-source tooling.

Do NOT claim that every optional tool or AI model is free/open source unless verified.

Clearly distinguish:

- VORTEX itself;
- bundled dependencies;
- optional tools;
- external AI agents/models;
- system packages.

If a dependency is unavailable or optional, say so.

---

14. ABOUT — REAL APPLICATION WARNING

Place a prominent warning in the About section.

It should communicate the following meaning:

«IMPORTANT: VORTEX is a real application. It can execute real commands and interact with real systems when authorized and permitted by its security architecture. It is not a simulation or toy hacking application.»

Then clearly state:

«Only use VORTEX against systems, networks, applications, accounts, and data that you own or have explicit authorization to test or operate.»

Also explain:

«Unauthorized access, scanning, exploitation, credential attacks, or disruption of systems may violate laws, policies, or the rights of others.»

Keep the warning professional rather than sensational.

---

15. ABOUT — VERSION INFORMATION

If the application already has version information, display the actual version.

If there is an existing versioning mechanism, use it.

Do not create a second conflicting version system.

If a version is not currently available, do not invent one merely for the About screen.

---

16. ABOUT — SYSTEM INFORMATION

Where appropriate, display information already available from the application, such as:

- VORTEX version;
- platform;
- runtime;
- build information.

Only expose information that is already safely available.

Do not expose:

- passwords;
- tokens;
- API keys;
- private credentials;
- sensitive filesystem information.

---

17. UI/UX REQUIREMENTS

The Help and About interfaces must:

- match the existing VORTEX design;
- use the existing UI components where possible;
- be responsive;
- be readable;
- support scrolling for detailed content;
- work on the existing supported screen sizes;
- not interfere with the terminal;
- not interfere with agent execution;
- not interfere with tasks;
- not interfere with sessions;
- not interfere with the STOP ALL mechanism;
- not create unnecessary background processes.

Prefer a modal/panel/page consistent with the existing application architecture.

Do not introduce a completely new UI framework just for Help/About.

---

18. ACCESSIBILITY

Make Help and About reasonably accessible.

Ensure:

- buttons have clear labels;
- keyboard navigation works where the existing UI supports it;
- text has adequate readability;
- dialogs/panels can be closed normally;
- focus behavior is sensible;
- long content can be scrolled.

---

19. DO NOT CHANGE OTHER FEATURES

This is a strict requirement.

Do NOT modify:

- command execution;
- Guardian;
- Agent Council;
- orchestration;
- task engine;
- database;
- memory;
- tool adapters;
- security controls;
- scope enforcement;
- engagement system;
- reports;
- authentication;
- terminal;
- PTY;
- cancellation;
- STOP ALL;
- sandbox;
- AI models;
- MCP;
- networking;
- existing CLI behavior.

Unless a tiny change is absolutely necessary to integrate the Help/About UI, leave these systems untouched.

If an unrelated bug is discovered:

DO NOT fix it as part of this task.

Document it separately rather than expanding the scope.

---

20. TESTING

After implementation:

Test Help

Verify:

- Help button appears;
- Help opens;
- content renders;
- content is readable;
- scrolling works;
- closing works;
- keyboard interaction works where applicable.

Test About

Verify:

- About button appears;
- About opens;
- developer information is displayed;
- license information is accurate;
- cybersecurity warning appears;
- version information is accurate if available;
- content renders correctly;
- closing works.

---

21. REGRESSION TESTING

Because this is a real application, test existing functionality after adding Help/About.

At minimum verify that:

- application starts;
- existing navigation works;
- terminal works;
- natural-language requests still work;
- planning still works;
- Guardian still works;
- tool detection still works;
- tasks still work;
- existing dialogs work;
- STOP ALL still works;
- existing CLI commands remain unaffected.

Run the existing automated test suite.

Run frontend tests/lint/build where applicable.

Do not declare success if existing tests fail because of the changes.

---

22. CODE QUALITY

Keep the implementation minimal.

Do not introduce unnecessary dependencies.

Prefer existing components/utilities.

Avoid duplicated styles/components.

Do not add large libraries merely to render static Help/About content.

Keep the implementation maintainable.

---

23. FINAL VERIFICATION

Before finishing:

1. Inspect every changed file.
2. Run tests.
3. Run lint/build checks where applicable.
4. Open the actual application.
5. Click Help.
6. Navigate through the entire Help content.
7. Close Help.
8. Click About.
9. Navigate through the entire About content.
10. Close About.
11. Verify existing functionality still works.
12. Check Git diff.
13. Confirm that only files necessary for Help/About were modified.

---

24. README / DOCUMENTATION

Because Help and About are now user-facing functionality, update the documentation only where appropriate.

Do not rewrite the entire README.

Add a concise reference that:

- Help is available inside the application;
- About provides information about VORTEX, its developer, licensing, and authorized-use requirements.

If the application's existing documentation already contains equivalent information, avoid unnecessary duplication.

---

25. FINAL REPORT

At the end, report:

Implemented

- Help button;
- detailed Help content;
- About button;
- About information;
- developer information;
- license information;
- authorized-use warning.

Tests

Report actual results.

Files changed

List every changed file.

Existing functionality

Confirm what was regression-tested.

Unrelated issues

If you discovered unrelated problems, list them separately without modifying them.

---

FINAL INSTRUCTION

Focus ONLY on Help and About.

Do not turn this task into a general VORTEX refactor.

Do not add new cybersecurity tools.

Do not modify the AI architecture.

Do not modify command execution.

Do not modify the Guardian.

Do not modify the Agent Council.

Do not modify the task engine.

Do not modify the security model.

Do not modify existing working functionality.

The objective is simple:

«Add an excellent, detailed Help experience and an accurate, professional About experience to the existing VORTEX application while leaving everything else untouched.»

After implementing them, test them thoroughly and perform regression testing to ensure that the rest of the real application continues to operate exactly as before.
