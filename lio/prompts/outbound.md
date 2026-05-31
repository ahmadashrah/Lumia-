## Capability: Outbound Outreach

Generate a personalized outreach sequence for the target.

Input: JSON with recipient name, company, role, segment, and any context.

Constraints:
- Per email: subject ≤8 words, body ≤120 words, one CTA.
- Default cadence: 4 touches over 14 days (day 1, day 4, day 8, day 14) unless input overrides.
- Open with a specific hook tied to the recipient's company, role, or stated context. No generic intros.
- One CTA per email. No multi-asks.
- Plain text. No emojis. No bullet lists in the body.

Return ONLY valid JSON in exactly this shape (no prose around it, no markdown fences):

{
  "recipient": "string",
  "context_used": "string — what you anchored the personalization on",
  "sequence": [
    {"day": 1,  "subject": "...", "body": "...", "cta": "..."},
    {"day": 4,  "subject": "...", "body": "...", "cta": "..."},
    {"day": 8,  "subject": "...", "body": "...", "cta": "..."},
    {"day": 14, "subject": "...", "body": "...", "cta": "..."}
  ],
  "notes": "string — anything Ahmad should know before sending"
}
