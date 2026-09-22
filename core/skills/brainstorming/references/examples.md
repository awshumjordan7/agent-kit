# Brainstorming Examples

Worked examples of the brainstorming phases.

## Starting a session (Phase 1, independent questions together)

```
User: Let's brainstorm the new notification system.

Claude: Before we explore approaches, let me understand the current state:
1. What notification mechanisms exist in the system today, if any?
2. Who needs the new notifications?
3. Are there delivery, timing, or infrastructure constraints I should account for?

User: We have email notifications via SendGrid for account events. Customers need in-app
notifications within a minute, and we need to stay on our existing AWS stack.

Claude: Got it — email-only today, with customer-facing in-app delivery within a minute on
the existing AWS stack. Which account events need in-app delivery first?
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
