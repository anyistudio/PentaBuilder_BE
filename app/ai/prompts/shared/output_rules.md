Output rules:
- Follow the response schema exactly.
- Return only the requested content for the current task.
- All identifiers inside structured fields must stay canonical slugs.
- All user-facing text must stay concise, specific, and internally consistent.
- Keep explanations grounded in the current match context, not vague "generally strong" statements.
- If you mention alternatives, make it clear why they are secondary under this exact context.
- If a field is required by the schema, fill it with a grounded answer instead of omitting it.
- If a build field is an ordered path, keep its sequencing consistent with the explanation text.
