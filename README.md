# Tales Through Things (T3) — v2

People tell a memory; T3 turns it into an object that tells it back, as a haiku,
in its own voice. The quick demo (fixed sequence) stays in `../sequence_fake_video/`.

## Experience (one button: press to continue, hold to speak)

1. **Intro**: "I collect memories and turn them into objects. Have a look at a few of them."
2. **Collection**: 3 archived memories (turning point-cloud object + haiku), press for the next.
3. **Invitation**: "Would you like to turn it into an object?" → hold and answer.
   *Not yet* → 3 more memories, then ask again.
4. **Questions**: a random theme (`server/script.json`); its first question word for word,
   then AI follow-ups based on the answers (3 questions in total).
5. **Thanks** → **generating** (breathing ring) → **the object + its haiku**.
6. **Archive?** yes → joins the collection; no → deleted. Back to the intro.

Also: a hold under 1.5 s shows "Hold the button while you speak to record" (blue flashes);
2 minutes without input during a visit → back to the intro (the visit is discarded).

## Run

```sh
cd tales_through_things
caffeinate -dis python3 server/main.py
```

On the iPad: open `https://<mac-ip>:8444` (printed at start) → Share → **Add to Home Screen**.
Same certificate as the demo, so no extra iPad setup. Keys: `R` reset · `H` status overlay · `F` fullscreen.

## AI

Every AI step goes through one interface (`server/providers.py`):
transcribe → yes/no → next question → object + haiku → image → 3D → point cloud.

- **Now: mock mode** (no keys): scripted questions, a demo object, realistic delays.
- **Next: cloud** (`.env`, see `.env.example`): Claude for the conversation and haiku,
  fal.ai for speech-to-text, image and 3D (TRELLIS), converted to coloured points here.
- **Later, optionally: local** steps on the PC (48 GB GPU) or Mac mini M2 behind the same interface.

## Data

- `archive/<id>/` — memories visitors chose to keep: `meta.json` (object, haiku, theme, date),
  `points.bin`, `model.glb`. Seeded with the four demo objects.
- `runs/<id>/` — a visit in progress; deleted if not archived (or after an hour).
- No audio or transcripts are stored. Privacy information is on the exhibition poster.

## Files

- `web/` — the iPad page (`app.js` flow, `pointcloud.js` objects, `wave.js` mic + recording)
- `server/` — `main.py` (HTTPS + API), `sessions.py` (a visit), `providers.py` (AI),
  `archive.py` (collection), `script.json` (texts and themes)
- `tools/` — point-cloud converters, `ipad_eval.py` (inspect the iPad page over USB)
- `certs/` — local HTTPS certificate authority (**private: never share `rootCA.key`**)

Credits: interview, object, image-prompt and haiku approaches inspired by
Nicolas Grosfort's prototype (github.com/nicolasgrosfort/tales-through-things).
