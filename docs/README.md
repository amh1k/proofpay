# ProofPay Documentation

## Design — what we're building

| Document | Contents |
|---|---|
| [Overview](overview.md) | Product concept, features, verification flow, MVP scope, demo scenarios |
| [System design](system-design.md) | Architecture, components, trust model, decision rules, security, ADRs |
| [Data model](data-model.md) | Entities, relationships, constraints, invariants, indexing, retention |

## Execution — how we're building it

| Document | Contents |
|---|---|
| [Build plan](build-plan.md) | The seven phases, in order, with a definition of done for each |
| [Work division](work-division.md) | Who owns which directories, so four people can work at once without colliding |
| [Setup](setup.md) | Local setup, dependency rules, platform notes |
| [Practices](practices.md) | Environments, git workflow, testing strategy, licensing, execution discipline |
| [References](references.md) | 68 verified reference repositories, with what specifically to take from each |
| [Cost check](cost-check.md) | Every component verified free or free-tier, and how to avoid a bill |
| [Phase guides](phases/) | A deep best-practices guide for each build phase |

---

## Suggested reading order

**Joining the project:**
[Overview](overview.md) → [Build plan](build-plan.md) → [Setup](setup.md)

**About to write code:**
[Work division](work-division.md) → [Practices](practices.md) → the guide for your phase in [`phases/`](phases/)

**Designing something new:**
[System design](system-design.md) → [Data model](data-model.md) → [References](references.md)

Read a phase guide **immediately before starting that phase**, not all at once. A guide read three
days early is a guide nobody remembers.
