# Third-party notices

Opus Note is licensed under the [MIT License](LICENSE). It depends on and redistributes work by
others, listed here. Each component remains under its own license; nothing in this file alters
those terms.

Three categories matter, and they are different:

1. **Bundled into the built client.** `npm run build` inlines these into `frontend/dist`, which the
   API serves — so the built bundle *redistributes* them and their notices must travel with it.
2. **Vendored assets.** Files committed to this repository under someone else's license.
3. **Installed separately.** Python packages resolved by `pip`, and browser packages resolved by
   `npm` at development time. These are not redistributed by this repository, so they carry no
   notice obligation here — they are listed for completeness.

---

## 1. Bundled into the built client

Minification strips comments, so the notices below are reproduced here rather than relying on
licence headers surviving in `dist`. The build also emits a short banner carrying the essential
attribution; see `frontend/vite.config.ts`.

| Package | Version | License | Copyright |
| --- | --- | --- | --- |
| [OpenSheetMusicDisplay](https://github.com/opensheetmusicdisplay/opensheetmusicdisplay) | 2.1.2 | BSD-3-Clause | Copyright 2019 PhonicScore |
| [VexFlow](https://github.com/vexflow/vexflow) | 1.2.93 | MIT | Copyright (c) 2010 Mohit Muthanna Cheppudira |
| [Tone.js](https://tonejs.github.io/) | 15.1.22 | MIT | Copyright (c) 2014-2020 Yotam Mann |
| [JSZip](https://stuk.github.io/jszip/) | 3.10.1 | MIT *(see note)* | Copyright (c) 2009-2016 Stuart Knightley, David Duponchel, Franz Buchinger, António Afonso |
| [Svelte](https://svelte.dev/) | 5.57.0 | MIT | Copyright (c) 2016-2025 Svelte Contributors |

**Note on JSZip.** It is dual-licensed `MIT OR GPL-3.0-or-later`. This project takes it under the
**MIT** option, and does not use the GPL option.

The MIT and BSD-3-Clause licenses each require that the copyright notice and permission notice are
reproduced in redistributed copies. The BSD-3-Clause license additionally forbids using the name of
the copyright holder or contributors to endorse or promote this project.

## 2. Vendored assets

### Spectral typeface

- **Files:** `frontend/src/assets/fonts/spectral-600.woff2`
- **Copyright:** 2017 The Spectral Project Authors (<https://github.com/productiontype/Spectral>)
- **License:** SIL Open Font License, Version 1.1
- **Full text:** [`frontend/src/assets/fonts/OFL.txt`](frontend/src/assets/fonts/OFL.txt)

Redistributed unmodified, which is the case the OFL permits most simply: the license text
accompanies the font, the font is not sold on its own, and the Reserved Font Name is not applied to
any modified version — because there is no modified version.

## 3. Fetched at runtime, not redistributed

### Salamander Grand Piano V3

- **Author:** Alexander Holm
- **Source:** <https://archive.org/details/SalamanderGrandPianoV3>
- **License:** [Creative Commons Attribution 3.0](https://creativecommons.org/licenses/by/3.0/)

The sampled instrument — 30 MP3 files, approximately 2 MB — is **not committed to this
repository**. `backend/app/piano.py` downloads it from
<https://tonejs.github.io/audio/salamander> on request and serves it from the local machine
thereafter, so this repository does not redistribute it. Attribution is shown in the user interface
next to the download control, which is what CC BY 3.0 requires of that use.

Note that CC BY 3.0 is a content license, not a software license, and it is deliberately not applied
to any code in this project.

## 4. Installed separately

### Python (runtime)

Resolved by `pip` from `backend/requirements.txt` and its transitive closure, and not redistributed
by this repository. The runtime tree contains 36 distributions; all are permissive. Notable members
and their licenses:

| Package | License |
| --- | --- |
| FastAPI | MIT |
| Starlette, Uvicorn | BSD-3-Clause |
| Pydantic, pydantic-core | MIT |
| **music21** | BSD-3-Clause |
| matplotlib | PSF (Python Software Foundation License) |
| NumPy | BSD-3-Clause (with 0BSD, MIT, Zlib and CC0-1.0 components) |
| requests | Apache-2.0 |
| python-multipart | Apache-2.0 |
| certifi | MPL-2.0 |
| Pillow | MIT-CMU |

**Note on certifi.** It is licensed MPL-2.0, which is *file-level* copyleft: it requires that
modifications to MPL-covered files remain under the MPL. It is used here unmodified as a dependency,
so it places no condition on this project's own license.

No package in the runtime tree is GPL, AGPL or LGPL.

### Python (development and test)

Not distributed. `pytest`, `httpx`, `coverage`, `playwright`, `mutmut`, `hypothesis` and others;
licenses are MIT, BSD, or Apache-2.0, with `hypothesis` under MPL-2.0. Development-only
dependencies do not affect the license of the distributed application.

### JavaScript (development)

Resolved by `npm` at development time. `vite`, `svelte-check`, `typescript` and their transitive
dependencies are MIT, ISC, Apache-2.0 or BSD-3-Clause. The one exception is `lightningcss`
(MPL-2.0), a build-time CSS minifier, used unmodified and not distributed in the application
bundle.

---

## Summary of licenses in this repository

| Work | License |
| --- | --- |
| Opus Note source code | MIT — [`LICENSE`](LICENSE) |
| Spectral typeface | SIL OFL 1.1 — [`OFL.txt`](frontend/src/assets/fonts/OFL.txt) |
| Bundled client libraries | MIT and BSD-3-Clause (§1) |
| Salamander Grand Piano samples | CC BY 3.0, fetched at runtime (§3) |
