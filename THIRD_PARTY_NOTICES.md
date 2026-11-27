# Third-party notices

## PurffleShorts

Parts of Shorts Studio are adapted from PurffleShorts
(https://github.com/Chamanrajragu/purffle-shorts), commit `514fd2547227b98d951dfc1489fc8c7ce72f1b68`.
Each adapted file says so in its header and lists what was adapted:

| Shorts Studio file | PurffleShorts file |
|---|---|
| `backend/shorts_studio/render/ffmpeg.py` | `purffle_shorts/ffmpeg.py` |
| `backend/shorts_studio/render/plan.py` | `purffle_shorts/render.py` |
| `backend/shorts_studio/render/raster.py` | `purffle_shorts/overlays.py` |
| `backend/shorts_studio/render/sfx.py` | `purffle_shorts/sfx.py` |
| `backend/shorts_studio/speech/engines.py` | `purffle_shorts/tts.py` |
| `backend/shorts_studio/timeline/words.py` | `purffle_shorts/timing.py` |

```
MIT License

Copyright (c) 2025 Purffle

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## ViralMint

ViralMint (https://github.com/openclaw-easy/ViralMint, AGPL-3.0-only) was used only as a design reference.
No ViralMint code, comments or prompts are included in Shorts Studio.

## Fonts (bundled in `assets/fonts/`)

- **Anton** (`Anton-Regular.ttf`), Copyright 2020 The Anton Project Authors
  (https://github.com/googlefonts/AntonFont). SIL Open Font License 1.1, full text in `assets/fonts/Anton-OFL.txt`.
- **Inter** (`Inter-Variable.ttf`), Copyright 2020 The Inter Project Authors (https://github.com/rsms/inter).
  SIL Open Font License 1.1, full text in `assets/fonts/Inter-OFL.txt`.

The fonts are unmodified. Captions, badges and cards are drawn with them; the exported videos contain only
rendered pixels, which the OFL places no conditions on.

## Python libraries (installed by pip, not bundled)

The dependencies in `pyproject.toml` are installed separately and used unmodified. Most are MIT, BSD or Apache-2.0
(FastAPI, Starlette, Uvicorn, jsonschema, python-multipart, Pillow). **edge-tts** (https://github.com/rany2/edge-tts)
is LGPL-3.0; Shorts Studio imports it as a library and doesn't change or redistribute it. Edge voices are an online
Microsoft service; check its terms for your use.

## Generated media

The sample gameplay clip (Conway's Game of Life), the sample music loop and the sound effects are synthesised by
FFmpeg or Python on your machine when you ask for them. They are not copied from anywhere.

## Runtime tools (not bundled)

Shorts Studio calls FFmpeg and ffprobe as separate programs found on your `PATH`. They are not distributed
with this repository. FFmpeg builds that include libx264 are licensed under the GPL; see https://ffmpeg.org/legal.html.
