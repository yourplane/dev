## Task context

Read the task context in the `comms` directory (files listed in `comms/index.txt`, **in order**). There may be new entries since you last read it—**double-check** `comms/index.txt` and read any new files before proceeding.

## Question mode

Act **conversationally**. Keep explanation **light** (one or two sentences at most). Focus on **clarifying questions** about product direction, requirements, and architecture — things only the user can decide.

Do **not** produce a full design proposal or implementation plan; that is Plan mode.

You do **not** have to ask questions if you have none. When there are no questions, still emit valid JSON with an empty `questions` array.

## Rules

- For **factual or technical** questions, **search the source code** first. Do **not** ask about things you can determine from the repo.
- Do **not** implement or change code during this run.
- Do **not** write to `comms` during this run; the dev CLI will add your output afterward.

## Output format

Respond with **only** a single ` ```json ` fenced block (no other text before or after). Use this schema:

```json
{
  "intro": "Brief context for the user (1–2 sentences). May be empty.",
  "questions": [
    {
      "id": "q1",
      "text": "Question text?",
      "options": ["Option A", "Option B"]
    }
  ]
}
```

- `intro`: required string (may be empty).
- `questions`: required array (may be empty when you have no questions).
- Each question needs `text` (string) and `options` (array of plain strings; may be empty).
- `id` is optional; omit or use `q1`, `q2`, etc.

When you have no questions, use: `{ "intro": "…", "questions": [] }`.
