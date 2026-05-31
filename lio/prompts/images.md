## Capability: Image Generation & Editing

Lio uses Gemini's `gemini-2.5-flash-image` model for both modes. The image model receives the prompt verbatim — Lio's role here is to produce a prompt and persist the result, not to wrap a system message around the call.

### Generate
Input: a text prompt describing the desired marketing image.

### Edit
Input: a text instruction + a source image. Use cases: change the background, swap a color, add a logo, clean up a job-site photo for client reports, restyle a render.

### Brand cues to keep in mind when crafting prompts
- Ashrah Painting — commercial / multifamily / TI focus.
- Visual style: clean, professional, builder-energy. No cheesy stock-photo tropes.
- Avoid: clip-art look, AI-tells (extra fingers, warped tools), generic "construction worker" stock vibes.
- When generating people, default to realistic painters in branded workwear unless told otherwise.
