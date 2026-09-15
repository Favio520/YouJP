"""Configuracion del backend.

Todo se puede sobreescribir con variables de entorno con prefijo ``YOUJP_``
o con un fichero ``.env`` en la raiz del repositorio. Ejemplo::

    YOUJP_ASR_MODEL=small
    YOUJP_ASR_DEVICE=cpu
    YOUJP_MIN_CHUNK_S=0.5
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/youjp/config.py -> backend/youjp -> backend -> raiz del repo
PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="YOUJP_",
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- rutas -------------------------------------------------------------
    project_root: Path = PROJECT_ROOT
    models_dir: Path = PROJECT_ROOT / "models"
    data_dir: Path = PROJECT_ROOT / "data"
    bench_dir: Path = PROJECT_ROOT / "bench"

    # --- audio -------------------------------------------------------------
    sample_rate: int = 16_000
    """Fijo. Whisper y Silero trabajan a 16 kHz; el navegador remuestrea."""

    frame_ms: int = 100
    """Tamano de trama que envia la extension. 100 ms = 1600 muestras."""

    ring_seconds: float = 30.0
    """Ventana maxima de audio retenida. Whisper no mira mas de 30 s."""

    # --- VAD (Silero v5) ---------------------------------------------------
    vad_model: Path = PROJECT_ROOT / "models" / "silero_vad.onnx"
    vad_threshold: float = 0.5
    """Probabilidad a partir de la cual se considera que empieza la voz."""

    vad_release_threshold: float = 0.35
    """Umbral mas bajo para dar por terminada la voz: evita el parpadeo."""

    vad_min_silence_ms: int = 500
    """Silencio necesario para cerrar una frase."""

    vad_speech_pad_ms: int = 200
    """Margen que se conserva antes y despues de la voz detectada."""

    # --- ASR ---------------------------------------------------------------
    asr_model: str = "large-v3-turbo"
    """Nombre de faster-whisper o ruta a un modelo CTranslate2 local."""

    asr_device: str = "cuda"
    asr_compute_type: str = "int8_float16"
    asr_beam_size: int = 1
    """Beam 1 en streaming: beam 5 multiplica por 2-3 el tiempo de decodificacion."""

    asr_language: str = "ja"

    asr_word_timestamps: Literal["auto", "on", "off"] = "auto"
    """``auto`` comprueba una vez, en un proceso aparte, si el modelo las admite.

    No es paranoia: algunos modelos destilados llevan los ``alignment_heads`` del
    modelo original, apuntando a capas del decodificador que no existen en ellos,
    y CTranslate2 muere con una violacion de acceso que Python no puede capturar.
    Sin marcas por palabra el pipeline sigue funcionando con tiempos interpolados
    por caracter. Ver :mod:`youjp.asr.probe`.
    """

    asr_no_repeat_ngram_size: int = 10
    """Prohibe repetir una secuencia de N tokens dentro de la misma pasada.

    Es la defensa en el propio decodificador contra los bucles de repeticion.
    Medido el 14-09-2026: sobre la apertura de un reportaje, turbo se engancho
    con "私はサンドルオンを使って、" y lo repitio hasta agotar la ventana,
    disparando la inferencia a 8 s y la latencia a 6,3 s en p95.

    En japones, 10 tokens son unos 10-20 caracteres; repetir esa secuencia
    literalmente en habla real es muy improbable. Bajarlo mucho empezaria a
    penalizar muletillas legitimas.
    """

    asr_repetition_penalty: float = 1.05
    """Desanimo suave de la repeticion. Valores altos degradan el japones, que
    usa particulas repetidas de forma natural."""

    asr_max_tokens_per_second: float = 14.0
    """Cota de tokens generados por segundo de audio de la ventana.

    Acota el peor caso de latencia: sin ella, un bucle genera hasta los 448
    tokens que admite Whisper por ventana, y una pasada pasa de 400 ms a 8 s.
    El japones hablado rapido no supera los ~10 caracteres por segundo.
    """

    min_chunk_s: float = 0.8
    """Cada cuanto se reejecuta Whisper sobre el buffer creciente.

    Es la palanca principal de latencia: bajarlo acerca los parciales pero sube
    la carga de GPU. Si la inferencia no cabe en este intervalo, el pipeline
    descarta pasadas en vez de acumular retraso.
    """

    buffer_trim_s: float = 15.0
    """Longitud a partir de la cual se recorta el buffer por el ultimo punto
    confirmado. Sin esto la ventana crece hasta 30 s y la inferencia se dispara."""

    prompt_chars: int = 180
    """Cuanto texto confirmado se pasa como ``initial_prompt``. Acotado a
    proposito: realimentar demasiado dispara bucles de alucinacion."""

    # --- segmentacion de frases -------------------------------------------
    sentence_end_chars: str = "。！？"  # japonesas: . ! ?
    max_sentence_chars: int = 60
    """Cierre forzado. Whisper puntua el japones de forma irregular: no se puede
    depender solo de los signos."""

    # --- filtros de alucinacion -------------------------------------------
    max_no_speech_prob: float = 0.6
    min_avg_logprob: float = -1.0
    max_repeat_ratio: float = 0.5
    """Proporcion maxima del texto que puede ser un n-grama repetido."""

    hallucination_blacklist: tuple[str, ...] = Field(
        default=(
            "ご視聴ありがとうございました",  # gracias por ver
            "チャンネル登録お願いします",  # suscribete
            "ご視聴ありがとうございます",
            "字幕による字幕",  # subtitulos por...
            "おしまい",
        ),
        description="Frases que Whisper inventa sobre silencio o musica.",
    )

    # --- diccionario y analisis del japones --------------------------------
    dict_db: Path = PROJECT_ROOT / "data" / "youjp.sqlite3"
    sudachi_dict: str = "core"
    """``core`` cubre el vocabulario general. ``full` anade nombres propios y
    terminologia, a cambio de mas memoria."""

    gloss_langs: tuple[str, ...] = ("spa", "eng")
    """Orden de preferencia de las glosas. El espanol de JMdict es una
    contribucion parcial, asi que el ingles queda de respaldo -- marcado como tal
    en la interfaz, para que se distinga de una acepcion revisada en espanol."""

    max_senses: int = 4
    """Acepciones que se envian por palabra. JMdict llega a tener veinte en
    palabras comunes y en una tarjeta sobre un video eso no se lee."""

    # --- traduccion --------------------------------------------------------
    mt_provider: Literal["nllb", "llm", "none"] = "llm"
    """Traductor del camino caliente.

    Por defecto ``llm`` (Qwen3-4B en GPU), contra lo que predecia el ADR 0003.
    Medido el 14-09-2026 sobre las mismas seis frases: NLLB-200 acierta 2 de 6 e
    invierte el significado de una ("mi control es superior al tuyo" se
    convirtio en "son mucho mejores que yo"); Qwen3-4B acierta 5 de 6 y respeta
    persona y direccion. En GPU los dos rondan los 300 ms, asi que la ventaja de
    velocidad de NLLB no existia.

    ``nllb`` se conserva porque pesa 1 500 MiB menos de VRAM y porque NLLB no
    depende de Ollama. ``none`` desactiva la traduccion."""

    mt_model: str = "entai2965/nllb-200-distilled-600M-ctranslate2"
    """Repositorio de Hugging Face o ruta local. Se usa una conversion a
    CTranslate2 ya publicada porque convertirla aqui exigiria instalar PyTorch
    (2,5 GB) para una operacion de una sola vez."""

    mt_device: str = "cuda"
    mt_compute_type: str = "int8_float16"
    mt_beam_size: int = 2
    """Beam 2 y no 1: la traduccion corre solo sobre frases finales, no en cada
    pasada, asi que el coste extra cabe de sobra en el presupuesto."""

    mt_source_lang: str = "jpn_Jpan"
    mt_target_lang: str = "spa_Latn"

    mt_max_tokens: int = 256
    """Cota de generacion. Acota el peor caso igual que en el ASR."""

    mt_context_sentences: int = 3
    """Frases anteriores que se pasan como contexto. NLLB las ignora; el LLM
    las usa para resolver sujetos omitidos y mantener el registro."""

    # --- LLM ---------------------------------------------------------------
    llm_url: str = "http://127.0.0.1:11434"
    llm_model: str = "qwen3:4b-instruct-2507-q4_K_M"
    llm_timeout_s: float = 120.0
    llm_keep_alive: str = "30m"
    """Cuanto mantiene Ollama el modelo residente sin usarlo. Descargarlo cuesta
    30 s de recarga en la siguiente frase."""

    llm_num_gpu: int = 99
    """Capas que Ollama sube a la GPU. 99 significa todas.

    En CPU el mismo modelo tarda 967-6 219 ms por frase y no sostiene un
    directo; en GPU baja a 152-540 ms. Ponerlo a 0 devuelve el LLM a la CPU,
    que es lo que hara falta cuando la fase 5 anada el modelo grande de
    explicaciones."""

    llm_num_ctx: int = 2048
    """Ventana de contexto que reserva Ollama.

    Importa mucho mas de lo que parece: Qwen3 declara 262 144 tokens de
    contexto y, si no se acota, Ollama reserva cache KV en consecuencia. Una
    frase mas tres de contexto no pasan de unos cientos de tokens, asi que
    2 048 sobra y ahorra cientos de MiB de VRAM en una tarjeta donde no
    sobran."""

    # --- servidor ----------------------------------------------------------
    host: str = "127.0.0.1"
    port: int = 8770

    # --- diagnostico -------------------------------------------------------
    log_level: str = "INFO"
    gpu_sample_hz: float = 4.0
    """Frecuencia de muestreo de VRAM para calcular el pico."""

    @property
    def samples_per_frame(self) -> int:
        return self.sample_rate * self.frame_ms // 1000


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Instancia unica. Cachear evita releer el ``.env`` en cada acceso."""
    return Settings()
