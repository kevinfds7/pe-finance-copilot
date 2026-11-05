# Responsible AI notes

**Scope.** The assistant answers questions about synthetic fund data. It does not give investment advice and cannot modify data.

**Human in the loop.** Corrections are proposals. A reviewer approves or rejects each one; approval records the decision but does not write to the data in this demo, because source-system changes belong with the data owner.

**Grounding.** Numbers must come from tool output. The evaluation flags any number in an answer that does not appear in the tool results or the question.

**Least privilege.** Read-only connection, curated tables only, no staging or system tables, timeouts and row limits.

**Transparency.** Every question, tool call and answer is logged. The app labels demo mode as not being an LLM.

**Known gaps.** No authentication, no PII handling (the data has none), no prompt-injection test set beyond a handful of refusal cases, and the audit log is not tamper-proof.
