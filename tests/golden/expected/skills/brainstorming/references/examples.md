# Brainstorming Examples

Worked examples of the brainstorming phases.

## Starting a session (Phase 1, one question at a time)

```
User: Let's brainstorm the new notification system.

Claude: Before we explore approaches, let me understand the current state.
What notification mechanisms exist in the system today, if any?

User: We have email notifications via SendGrid for account events. Nothing else.

Claude: Got it — email-only via SendGrid for account events. What's driving the need for a
new system? Are there specific gaps (real-time, in-app, more channels), or is it about the
reliability/scalability of what exists?
```

## Presenting approaches (Phase 2)

```
Claude: Based on what we've discussed, here are three approaches:

**Approach A: Event-driven with SQS + Lambda**  [summary + details]
**Approach B: Django Signals + Celery workers**  [summary + details]
**Approach C: Third-party service (Knock/Novu)**  [summary + details]

| Aspect          | A: SQS + Lambda          | B: Signals + Celery             | C: Third-party         |
|-----------------|--------------------------|---------------------------------|------------------------|
| Effort          | High                     | Medium                          | Low                    |
| Risk            | Medium (new infra)       | Low (known stack)               | Medium (vendor lock)   |
| Complexity      | High                     | Medium                          | Low                    |
| Maintainability | High (decoupled)         | Medium (coupled)                | Low (external)         |
| Trade-offs      | Most flexible, most work | Fastest to ship, scaling limits | Fastest, least control |
```

## When the user already has a plan (route away)

```
User: Let's brainstorm the auth migration — here's the plan doc: docs/auth-migration-plan.md

Claude: You already have a plan document. This is better suited for `/forge implement` to
execute the plan, or `/forge` to run the full implement + dual-model review pipeline. Want me
to use one of those instead?
```
