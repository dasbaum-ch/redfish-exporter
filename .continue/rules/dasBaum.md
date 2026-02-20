---
description: dasBaum
---

## Goals
- Keep changes minimal and focused.
- Preserve existing code style and structure.
- Ask before making broad refactors.

## Behavior
- Do not invent APIs or dependencies.
- Prefer small, testable diffs.
- Call out assumptions and missing context.

## Context
- Use only files referenced in the prompt unless told otherwise.
- For large changes, propose a plan before editing.

## PR instructions
- Title format: [<project_name>] <Title>
- Always run `ruff check` and `ruff format` before committing.
