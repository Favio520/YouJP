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
