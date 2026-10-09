# Tales Through Things (T3) — v2

People tell a memory; T3 turns it into an object that tells it back, as a haiku,
in its own voice. The quick demo (fixed sequence) stays in `../sequence_fake_video/`.

## Experience (one button: press to continue, hold to speak)

1. **Intro**: "I collect memories and turn them into objects. Have a look at a few of them."
2. **Collection**: 3 archived memories (turning point-cloud object + haiku, crossfading),
   drawn at random among all memories not yet seen in the visit. Press for the next.
3. **Invitation**: "Would you like to turn it into an object?" → hold and answer.
   *Not yet* → 3 more memories, then ask again.
4. **Questions**: a random theme (toy, summer, dish, outside, pocket — `server/script.json`);
   its first question word for word, then AI follow-ups based on the answers (3 questions in total).
5. **Thanks** → **generating** (breathing ring) → **the object + its haiku**.
6. **Archive?** yes → joins the collection; no → deleted. Back to the intro.

Also:
- While recording, the blue fills the screen and the three-line wave follows the voice.
- A tap, or a recording with no voice in it (checked on the server before paying for
  speech-to-text), shows "Hold the button while you speak" with blue flashes.
- 2 minutes without input during a visit → back to the intro (the visit is discarded).
- Typeface: Josefin Sans (embedded, works offline), haiku in italic; Lexend as fallback.
- The black disc never moves: it is aligned with a physical cover on the iPad.

## Run (on the Mac, for the iPad)

```sh
cd tales_through_things
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt   # once
caffeinate -dis .venv/bin/python server/main.py
```

On the iPad: open `https://<mac-ip>:8444` (printed at start) → Share → **Add to Home Screen**.
Same certificate as the demo, so no extra iPad setup.

Keys: `Space` = the button · `R`/`Esc` reset · `H` status overlay · `F` fullscreen.
`?memory=<id>` shows one archived memory (review).
`/collection.html` lists every archived memory (click one, or ← →, to see it turn; `#<id>` links to one).

## AI

Every AI step goes through one interface (`server/providers.py`):
transcribe → yes/no → next question → object + haiku → image → 3D → point cloud.

| Step | Service | Key in `.env` |
|---|---|---|
| Speech-to-text | OpenAI `gpt-4o-mini-transcribe` | `OPENAI_API_KEY` |
| Questions, object + haiku | Claude Sonnet 5.5 | `ANTHROPIC_API_KEY` |
| Yes / no | Claude Haiku 4.5 | (same) |
| Image → 3D | fal.ai FLUX schnell → TRELLIS | `FAL_KEY` |

Then `server/glb_points.py` samples the 3D model into 180,000 points in its real colours.

- Copy `.env.example` to `.env` and fill in the keys. **Any service without a key falls back
  to the mock**, so the whole experience also works with stand-in AI
  (`MOCK_YESNO`, `MOCK_FAST` for testing).
- Check the keys: `.venv/bin/python tools/check_ai.py` (add `--3d` for image + 3D, ~3 cents).
- **Haiku**: `T3_HAIKU=strict` (default) = classic form: 5-7-5 syllables counted on the server
  (CMU pronouncing dictionary), season word, a cut, one instant, the object's first-person voice;
  off-count haiku are sent back for revision (up to 3 times). `T3_HAIKU=free` = haiku-inspired.
- Visitor texts never contain dashes (prompts forbid them, `server/textclean.py` removes leftovers).
- Later, optionally: local steps on the PC (48 GB GPU) or Mac mini M2 behind the same interface.

## Settings (`.env`)

| Variable | Default | |
|---|---|---|
| `T3_PORT` | `8444` | the demo uses 8443, so both can run side by side |
| `T3_HAIKU` | `strict` | `strict` or `free` |
| `T3_MODEL` / `T3_FAST_MODEL` / `T3_STT_MODEL` | see table above | override the models |
| `T3_MAX_SESSIONS_PER_HOUR` | `40` | spending cap on new visits |
| `T3_MIN_VOICE_MS` / `T3_VOICE_LEVEL` | `150` / `0.006` | "did they say something?" threshold |
| `T3_DATA` | project folder | where `archive/` and `runs/` live |
| `T3_PASSCODE` | none | passcode screen (remote testing) |
| `T3_BEHIND_PROXY` | off | `1` = plain HTTP on localhost behind an HTTPS proxy |

## Online test version

A copy runs on a private server so colleagues can test remotely: Caddy (HTTPS) → systemd
service `t3` on localhost, with `T3_BEHIND_PROXY=1`, its own `.env`, a passcode and its own
archive (separate from the Mac's).

- **Deploy**: `tools/deploy.sh` (rsync + install requirements + restart). The SSH host `t3-vps`
  is defined privately in `~/.ssh/config`. Never copies `.env`, `certs/`, `archive/` or `runs/`.
- **Passcode**: signed cookie (secret in `.t3-secret`, created on first start), with
  guessing protection (8 failures per visitor per 15 min, 40 per hour overall).
- **Spending cap**: at most `T3_MAX_SESSIONS_PER_HOUR` new visits, even if the passcode leaks.

## Data

- `archive/<id>/` — memories visitors chose to keep: `meta.json` (object, haiku, theme, date),
  `points.bin`, `model.glb`. Seeded with four demo objects (Game Boy, bicycle, disposable
  camera, biscuit tin), made with the same image → 3D pipeline.
- `runs/<id>/` — a visit in progress; deleted if not archived (or after an hour).
- No audio or transcripts are stored. Privacy information is on the exhibition poster.
- Point-cloud links carry a version, so an open iPad always loads the current file;
  failed loads are retried.

## Files

- `web/` — the iPad page (`app.js` flow, `pointcloud.js` objects, `wave.js` mic + recording)
  - `voice-lab.html` — recording-feedback ideas side by side (ripples, dust, rings…)
  - `font-lab.html` — typeface candidates in the disc, grouped by mood
- `server/` — `main.py` (HTTPS + API + passcode), `sessions.py` (a visit), `providers.py` (AI),
  `prompts.py`, `syllables.py` (haiku check), `voice.py` (voice detection),
  `glb_points.py` (3D → points), `archive.py` (collection), `script.json` (texts and themes)
- `tools/` — `deploy.sh`, `check_ai.py`, point-cloud converters, `ipad_eval.py`
  (inspect the iPad page over USB with Web Inspector)
- `certs/` — local HTTPS certificate authority (**private: never share `rootCA.key`**)

Never committed: `.env`, `certs/`, `archive/`, `runs/`, `.t3-secret`.

Credits: interview, object, image-prompt and haiku approaches inspired by
Nicolas Grosfort's prototype (github.com/nicolasgrosfort/tales-through-things).
