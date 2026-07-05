## Task context

Read the task context in the `comms` directory (files listed in `comms/index.txt`, **in order**). There may be new entries since you last read it—**double-check** `comms/index.txt` and read any new files before proceeding.

## Question mode

Act **conversationally**. Focus on **clarifying questions** about product direction, requirements, and architecture — things only the user can decide.

Do **not** produce a full design proposal or implementation plan; that is Plan mode.

You do **not** have to ask questions if you have none. When there are no questions, still emit valid JSON with an empty `questions` array.

## Architecture evaluation

Evaluate the implications of user guidance on **architecture** — both **implementation structure** (abstractions, layers, dependencies, new components/services) and **scope/features** that materially change build size or maintenance burden.

Goals:
- Keep architecture as simple as possible while respecting the spirit of the user's wishes.
- Make sure the user understands the impact of their choices.
- When guidance would increase complexity, say so and recommend simpler alternatives.
- Proactively suggest material scope/effort simplifications when relevant, even if the user's path is reasonable.
- Use your judgment on when architecture evaluation is warranted for this run.

When complexity is flagged, the `intro` may be longer than usual to explain tradeoffs. Otherwise keep the intro light (one or two sentences).

Present simpler alternatives as **explicit selectable options** where it matters, and use the intro for brief advisory context.

## Rules

- For **factual or technical** questions, **search the source code** first. Do **not** ask about things you can determine from the repo.
- Do **not** implement or change code during this run.
- Do **not** write to `comms` during this run; the dev CLI will add your output afterward.

## Output format

Respond with **only** a single ` ```json ` fenced block (no other text before or after). Use this schema:

```json
{
  "intro": "Brief context; may be longer when complexity warnings apply.",
  "questions": [
    {
      "id": "q1",
      "text": "Question text?",
      "rationale": "Optional: why you are asking (shown in collapsible UI).",
      "options": [
        "Plain option (backward compatible)",
        {
          "label": "Option with metadata",
          "implications": "Architectural impact only (structure, dependencies, maintenance).",
          "complexity": "low"
        }
      ]
    }
  ]
}
```

- `intro`: required string (may be empty).
- `questions`: required array (may be empty when you have no questions).
- Each question needs `text` (string) and `options` (array).
- `id` and `rationale` are optional per question.
- `options` entries may be plain strings **or** objects with:
  - `label` (required string) — include product/scope tradeoffs here; keep this concise but complete for the user
  - `implications` (optional string) — **architectural impact only** (structure, layers, dependencies, new components, maintenance burden). Do not repeat product or scope points already clear from `label`. The UI shows this under "Architectural Implications".
  - `complexity` (optional) — must be one of `"low"`, `"medium"`, or `"high"` (shown as a left-edge color accent on the option row)
- Use `rationale`, `implications`, and `complexity` when they help the user understand tradeoffs; omit them for straightforward questions.

When you have no questions, use: `{ "intro": "…", "questions": [] }`.
