# YouJP

Real-time Japanese subtitles on YouTube, with local speech recognition,
Spanish or English translation, and clickable vocabulary for Japanese learners.

YouJP captures tab audio, transcribes it with Whisper, and analyzes Japanese
with Sudachi and JMdict. Processing runs on your computer. Setup requires
internet access to download dependencies, models, and dictionaries; YouTube
still uses its normal network connection.

See the [architecture review](docs/arquitectura.html) and [decision records](docs/adr/)
for implementation details and historical measurements (in Spanish).

## Features and status

- Live Japanese subtitles with confirmed and tentative text.
- Japanese-to-Spanish or Japanese-to-English translation, selectable while watching.
- Clickable words with readings, rōmaji, conjugations, and JMdict definitions.
- Automatic furigana for uncommon words, or furigana on all kanji.
- Subtitle history with timestamps that seek back to the corresponding sentence.
- Live controls for subtitle size, position, background, and language visibility.
- A settings panel available in Spanish and English, with a saved language preference.
- A Windows launcher for preparing and running the local backend.

The streaming and translation pipeline is implemented. Vocabulary analysis is
still being tested; recognition mistakes can also affect readings and definitions.

## Requirements

- Windows 10 or 11 and an NVIDIA GPU with a recent driver for the documented GPU setup.
  CUDA runtime libraries come as Python wheels; the CUDA Toolkit is not required.
- [uv](https://docs.astral.sh/uv/) for the Python environment.
- Node.js and npm to build the browser extension.
- Chrome or Edge to load the extension.
- Ollama for the default translation provider.
- `ffmpeg` on `PATH` when preparing benchmark audio samples.

## Quick start on Windows

Open `YouJP.cmd` in the project root and select **Preparar / actualizar**
(Prepare / update). This prepares the backend, builds the extension, and creates
`YouJP.exe`. You can then launch the executable directly or create a shortcut.
Keep it beside the project folders: it is not a standalone installer.

See the [Windows launcher guide](scripts/windows/README.md) for launcher-specific
instructions (in Spanish).

The default translator uses **Qwen3-4B-Instruct-2507 through Ollama**. Download it once:

```powershell
ollama pull qwen3:4b-instruct-2507-q4_K_M
```

Use **Carpeta extensión** (Extension folder) in the launcher to open the build
directory. In Chrome or Edge, open `chrome://extensions` or `edge://extensions`,
enable **Developer mode**, select **Load unpacked**, and choose
`extension/.output/chrome-mv3`.

Start the backend, open a Japanese YouTube video, and **click the extension icon**.
The icon shows `ON` while capturing; click it again to stop. Browser tab capture
requires this user gesture, so the extension intentionally has no action popup.

## Language and display settings

Open the gear beside the YouTube volume control, or press **Alt+S**.

- **Settings language / Idioma de los ajustes:** choose **English** or **Español**
  for the settings panel. This preference is saved independently of translation.
- **Translate into / Traducir al:** choose English or Spanish for new translations.
  Earlier history entries retain their original translation language.
- **Show:** display both languages, Japanese only, or translation only.
- **Furigana:** choose automatic, always, or off. Automatic mode annotates words
  that JMdict does not mark as common.

Size, width, distance from the bottom, background, visible previous sentences,
and partial text visibility update immediately and persist between sessions.
Resetting display settings preserves the selected settings-panel language.
Other application screens may still contain Spanish text.

Hover over the subtitles to reveal the drag handle, history button, and settings
button. Positions are stored as percentages so they adapt to fullscreen playback.
Confirmed text is white; gray italic text is tentative and may change.

| Shortcut | Action |
|---|---|
| **Alt+S** | Open subtitle settings |
| **Alt+H** | Open session history |
| **Alt+M** | Open metrics |
| **Esc** | Close an open panel |

Click a Japanese word to inspect its reading, rōmaji, part of speech,
conjugation, and dictionary senses. The history panel retains the latest 300
sentences and their translations. Click a timestamp to replay that moment.

## Manual development setup

From the project root:

```powershell
.\tasks.ps1 setup       # Python environment, CUDA libraries, and models
.\tasks.ps1 doctor      # Check the installation
.\tasks.ps1 test        # Backend tests
```

Start the server:

```powershell
cd backend
uv run uvicorn youjp.main:app --host 127.0.0.1 --port 8770
```

In a separate terminal:

```powershell
cd extension
npm ci
npm run build          # Output: extension/.output/chrome-mv3
```

On Windows, use `npm.cmd` if PowerShell blocks the `npm.ps1` wrapper.
During development, `npm run dev` starts a separate Chrome instance with hot reload.

### Extension identity

The unpacked extension has a fixed ID, `maigpfdicmnmilihmhnfalbcchkpobab`.
The backend accepts that origin by default. If an older installation has a
different ID, remove it, load the rebuilt extension, and restart the backend.

To allow another ID, set `YOUJP_ALLOWED_EXTENSION_IDS` to one or more
comma-separated IDs. An empty value permits any valid extension origin for
development. Rejected origins are recorded in the backend log.

## Dictionary

Build the dictionary once:

```powershell
cd backend
uv run python ../scripts/fetch_dicts.py
uv run python -m youjp.dict.build_db
```

The measured dictionary snapshot required about 145 MB of downloads and 15 seconds
to process. It produced `data/youjp.sqlite3` with 218,776 JMdict entries and 10,384
KANJIDIC2 kanji, using about 70 MB. Without it, subtitles and translation still
work, but dictionary lookup is unavailable.

Definitions follow the translation target. In Spanish mode, entries without
Spanish glosses fall back to English and are labeled accordingly. In the measured
snapshot, Spanish covered 16% of dictionary entries but 88% of words in the sampled
spoken transcripts, reflecting stronger coverage of common vocabulary.

## Translation providers and GPU memory

The default provider is **Qwen3-4B-Instruct-2507 on the GPU through Ollama**.
In the small six-sentence comparison, NLLB translated two sentences correctly
and Qwen3-4B five; both took around 300 ms on the test GPU. This is a limited
project benchmark. See [ADR 0003](docs/adr/0003-nmt-dedicado-frente-a-llm.md).

Whisper and the translator left only 400–900 MiB free on the tested 6,144 MiB GPU
with the browser open. If memory is tight, choose one of these alternatives
before starting the backend:

```powershell
$env:YOUJP_LLM_NUM_GPU = '0'    # CPU translation: frees about 2.7 GB; 1–6 s per sentence
$env:YOUJP_MT_PROVIDER = 'nllb' # Smaller translator: about 1.5 GB less, lower measured quality
$env:YOUJP_MT_PROVIDER = 'none' # Disable translation
```

For a manual NLLB installation, run `uv sync --extra nllb` from `backend`.
The Windows setup includes that extra; a basic backend installation does not need it.
Translation targets are described in [ADR 0006](docs/adr/0006-destinos-de-traduccion.md).

The server reports low VRAM and other Ollama models remaining in memory.
Use `ollama stop <model-name>` to unload a model you no longer need.

## Troubleshooting

| Symptom | What to check |
|---|---|
| Stuck on “conectando con el backend…” | Start the backend and verify port 8770. |
| Extension cannot connect after an update | Check its ID, reload the extension, and restart the backend. |
| Tab audio becomes silent | Inspect audio reinjection in `offscreen/main.ts`. |
| Audio sounds muffled | Playback must use the native sample rate; only ASR audio uses 16 kHz. |
| No subtitles for a non-Japanese video | The pipeline targets Japanese speech; VAD and filters may discard other audio. |
| No text after seeking | Check the backend log for a pipeline flush. |

Debug the service worker and offscreen document through `chrome://extensions`.
Debug the content script through the YouTube tab's developer console.

### Windows GPU memory fallback

In NVIDIA Control Panel, open **Manage 3D settings → Program Settings**, add
`backend\.venv\Scripts\python.exe`, and set **CUDA – Sysmem Fallback Policy**
to **Prefer No Sysmem Fallback**, if available in your driver.

On the tested system, WDDM silently spilled to system RAM when VRAM ran out,
making inference 5–10 times slower. Disabling fallback makes insufficient GPU
memory visible as an error during debugging.

### Model download appears stuck

The Hugging Face Xet backend can spend a long time reconstructing data before
writing files. If `models/whisper` does not grow, try the incremental downloader
from the `backend` directory:

```powershell
$env:HF_HUB_DISABLE_XET = '1'
uv run python ../scripts/fetch_models.py --whisper large-v3-turbo
```

### Models use twice the expected disk space

Without Windows Developer Mode, the Hugging Face cache may copy files instead of
creating symbolic links. A 1.6 GB model can therefore use 3.2 GB. Enable Developer
Mode in Windows Settings to allow symlinks, or keep the extra copies.

## Testing without a browser

The replay client exercises the backend using the same WebSocket handshake and
16 kHz PCM frames as the extension, paced in 100 ms intervals:

```powershell
cd backend
uv run python ../scripts/replay_client.py ../bench/samples/11-noticias-entrevista.wav
uv run python ../scripts/replay_client.py <wav> --seek-at 20
uv run python ../scripts/check_frame_conformance.py
```

Extension checks:

```powershell
cd extension
npm test
npm run compile
npm run lint
npm run build
```

## Benchmarks

Prepare representative Japanese samples: clear news narration, conversation,
anime or drama, speech over music, and pure silence. Silence matters because
Whisper can invent Japanese sentences when no speech is present.

```powershell
.\scripts\prepare_sample.ps1 -Source "D:\clips\news.mp4" -Name news -Duration 60
.\scripts\fetch_sample.ps1 -Url "https://youtu.be/XXXX" -Name news -Start 00:01:30 -Duration 60
.\tasks.ps1 bench            # Real-time pacing: measures latency
.\tasks.ps1 bench -Fast      # No pacing: measures real-time factor
```

**Latency** measures the delay from spoken audio to displayed text, recorded as
`speech_latency_ms`. **RTF** (real-time factor) measures processing time divided
by audio duration: 0.3 means one second of audio takes 0.3 seconds to process;
above 1.0, processing falls behind.

Each run writes its results and configuration to `bench/results/`.

### Historical baseline

Measured on September 14, 2026 with an idle RTX 2060 6 GB, faster-whisper 1.2.1,
and CTranslate2 4.8.2. These are historical results on one machine, not fresh
measurements of every later revision. Details are in [the ADRs](docs/adr/).

| Sample | Latency p50 | p95 | Whisper p50 | Sentences | Rejected passes |
|---|---|---|---|---|---|
| Digital silence, 45 s | — | — | — | 0 | 0 passes |
| Pink noise, 45 s | — | — | — | 0 | 0 passes |
| Studio narration | 1,440 ms | 3,951 ms | 362 ms | 11 | 5 / 94 |
| Street interviews | 1,666 ms | 2,673 ms | 440 ms | 14 | 3 / 94 |
| News report, final segment | 1,421 ms | 2,065 ms | 382 ms | 11 | 5 / 92 |
| Anime action scene | 1,365 ms | 3,534 ms | 380 ms | 6 | 11 / 67 |

Desktop VRAM usage was 1,181 MiB and total peak usage 2,496 MiB: 1,315 MiB
attributable to the model. Whisper did not run on either silence or pink noise.
Anime was harder: 87 characters in 62 seconds versus roughly 290 for news, with
16% of passes rejected versus 3–5%. Errors included お娘 for あの娘 and フリーレ
for フリーレン. Readings derived from imperfect transcripts require caution.

### Model comparison

The selected model is **`large-v3-turbo`**. Three 70-second Japanese TV segments
covered studio narration, street interviews, and voice over music.

| Metric | large-v3-turbo | kotoba-whisper-v2.0-faster |
|---|---|---|
| Latency p50 | 1,477–1,826 ms | 1,514–3,276 ms |
| Latency p95 | 2,096–4,307 ms | 4,359–7,301 ms |
| Inference per pass p50 | 408–482 ms | 317–338 ms |
| Partial results per sample | 73–77 | 36–41 |
| Empty passes | 0 | 12–27 |
| Model VRAM | ~1,600 MiB | ~1,400 MiB |
| Word timestamps in the tested stack | Supported | Crashed the process |

Kotoba inferred faster but frequently returned empty partial windows. Because
LocalAgreement requires two matching passes, those gaps delayed confirmation.
Its quality did not compensate in the examples: it produced 大人の自首室
(“adult surrender-to-police room”) where Turbo produced 大人の自習室
(“adult study room”).

Other findings from the measured stack:

- Desktop GPU usage without Chrome playback was 825–1,060 MiB.
- Kotoba's alignment heads referenced layers outside its distilled two-layer
  decoder. Word timestamps caused a native `0xC0000005` crash. A cached subprocess
  probe detects this and falls back to character-interpolated timestamps.
- Confidence statistics alone did not prevent hallucinations: on digital silence,
  Turbo emitted 「ご視聴ありがとうございました」 with `no_speech_prob = 0.000`
  and `avg_logprob = −0.143`. VAD is essential; see [ADR 0004](docs/adr/0004-el-vad-es-la-barrera.md).
- Decoder repetition limits reduced inference p95 from 1,688 to 571 ms in a
  problematic voice-over-music sample, using `no_repeat_ngram_size`,
  `repetition_penalty`, and a `max_new_tokens` limit.
- Relaxing the confidence threshold from −1.0 to −2.5 reduced rejected passes
  from five to two but worsened latency p95 from 3,951 to 7,811 ms. Low-quality
  hypotheses delayed LocalAgreement; the threshold remained −1.0.

Close GPU-intensive games and applications before reproducing these results.
With a game running, total peak VRAM rose from 2,496 to 5,392 MiB and median
latency nearly doubled. The benchmark reports contention but cannot remove it.

```powershell
.\tasks.ps1 bench -Model large-v3-turbo
.\tasks.ps1 bench -Model kotoba-tech/kotoba-whisper-v2.0-faster
.\tasks.ps1 bench -Model small
```

## Project structure

```text
backend/youjp/
  audio/      Audio buffers and voice activity detection
  asr/        Whisper, LocalAgreement, segmentation, hallucination filters
  pipeline/   Streaming orchestration
  obs/        Metrics, GPU monitoring, and logging
extension/    Browser capture, subtitles, and vocabulary interface
scripts/      Setup, model downloads, sample preparation, and benchmarks
bench/        Audio samples and benchmark results
docs/         Architecture and decision records
```

## Third-party licenses

JMdict and KANJIDIC2 are provided by [EDRDG](https://www.edrdg.org/) under
CC BY-SA 4.0. Whisper uses the MIT license and Sudachi uses Apache-2.0.
Review the non-commercial license of NLLB-200 before distributing it.
