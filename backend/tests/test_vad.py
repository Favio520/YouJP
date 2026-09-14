"""Integracion con el modelo real de Silero.

No se puede sintetizar voz convincente, asi que aqui no se comprueba que detecte
habla: eso lo dira el banco con audio real. Lo que se comprueba es el envoltorio,
que es donde estan los errores silenciosos -- forma de los tensores, tamano de
ventana y alineamiento de las muestras sobrantes entre llamadas.
"""

from __future__ import annotations

import numpy as np
import pytest

from youjp.audio.vad import SileroVAD, VADGate
from youjp.config import get_settings

settings = get_settings()

pytestmark = pytest.mark.skipif(
    not settings.vad_model.is_file(),
    reason="falta models/silero_vad.onnx (uv run python ../scripts/fetch_models.py)",
)


@pytest.fixture
def vad() -> SileroVAD:
    return SileroVAD(settings.vad_model, sample_rate=16_000)


def _speech_samples() -> list:
    """Muestras del banco que contienen voz, por convencion de nombre.

    Las que empiezan por 0 son audio de control sintetico (silencio, ruido); de
    10 en adelante son grabaciones reales. No se versionan, asi que estos tests
    se saltan en una copia limpia del repositorio.
    """
    folder = settings.bench_dir / "samples"
    if not folder.is_dir():
        return []
    return [p for p in sorted(folder.glob("*.wav")) if not p.name.startswith("0")]


def test_v5_antepone_el_contexto(vad: SileroVAD):
    """El bug del 14-09-2026.

    Silero v5 espera 64 muestras de contexto delante de cada ventana de 512: el
    tensor que entra al modelo es de 576. Sin ellas no hay error ni aviso -- el
    modelo devuelve ~0,001 para absolutamente todo, habla y silencio por igual,
    y el pipeline entero deja de transcribir en silencio. Este test mira el
    tensor que realmente se le pasa al modelo.
    """
    if not vad._uses_state:  # noqa: SLF001
        pytest.skip("modelo v4: no usa ventana de contexto")

    anchos: list[int] = []
    real_run = vad._sess.run  # noqa: SLF001

    def espia(outputs, feeds):
        anchos.append(feeds["input"].shape[1])
        return real_run(outputs, feeds)

    vad._sess.run = espia  # noqa: SLF001
    vad.probabilities(np.zeros(vad.window_samples * 3, dtype=np.float32))

    assert anchos == [vad.window_samples + 64] * 3


@pytest.mark.skipif(not _speech_samples(), reason="no hay muestras con voz en bench/samples")
def test_distingue_habla_de_silencio():
    """La prueba que de verdad importa: silencio y habla tienen que dar
    resultados *distintos*. Probar solo silencio deja pasar un VAD roto, porque
    'probabilidad baja' parece correcto."""
    import soundfile as sf

    speech, _ = sf.read(str(_speech_samples()[0]), dtype="float32")
    if speech.ndim > 1:
        speech = speech.mean(axis=1)

    probs_habla = SileroVAD(settings.vad_model).probabilities(speech[: 16_000 * 30])
    probs_silencio = SileroVAD(settings.vad_model).probabilities(
        np.zeros(16_000 * 30, dtype=np.float32)
    )

    assert probs_habla.max() > 0.9, "no detecta voz en una grabacion con voz"
    assert (probs_habla > 0.5).mean() > 0.2, "detecta demasiada poca voz"
    assert probs_silencio.max() < 0.1, "detecta voz en silencio digital"


def test_ventana_de_512_muestras(vad: SileroVAD):
    """Silero v5 exige exactamente 512 muestras a 16 kHz. Si el envoltorio
    eligiera otro tamano, ONNX fallaria o -- peor -- daria probabilidades
    sin sentido."""
    assert vad.window_samples in (512, 1536)


def test_una_probabilidad_por_ventana(vad: SileroVAD):
    pcm = np.zeros(vad.window_samples * 10, dtype=np.float32)
    probs = vad.probabilities(pcm)
    assert probs.shape == (10,)
    assert np.all((probs >= 0.0) & (probs <= 1.0))


def test_el_silencio_no_dispara(vad: SileroVAD):
    probs = vad.probabilities(np.zeros(vad.window_samples * 20, dtype=np.float32))
    assert probs.max() < 0.5


def test_las_muestras_sobrantes_se_guardan(vad: SileroVAD):
    """Las tramas que llegan de la extension son de 100 ms (1600 muestras) y no
    son multiplo de la ventana. Si el resto no se arrastra entre llamadas, las
    ventanas se desalinean y el VAD se vuelve ruido."""
    w = vad.window_samples
    assert len(vad.probabilities(np.zeros(w + 100, dtype=np.float32))) == 1
    # Quedaban 100; con w-100 mas se completa exactamente una ventana.
    assert len(vad.probabilities(np.zeros(w - 100, dtype=np.float32))) == 1
    assert len(vad.probabilities(np.zeros(10, dtype=np.float32))) == 0


def test_reset_vacia_lo_pendiente(vad: SileroVAD):
    vad.probabilities(np.zeros(100, dtype=np.float32))
    vad.reset()
    assert len(vad.probabilities(np.zeros(vad.window_samples - 100, dtype=np.float32))) == 0


def test_la_puerta_no_se_dispara_en_silencio(vad: SileroVAD):
    gate = VADGate(vad, min_silence_ms=300)
    events = gate.push(np.zeros(16_000, dtype=np.float32))
    assert events == []
    assert not gate.is_speech
    assert gate.now == pytest.approx(1.0, abs=0.05)


def test_la_puerta_avanza_su_reloj(vad: SileroVAD):
    """El reloj del VAD tiene que seguir al audio procesado, no al de pared:
    de el salen los instantes de inicio y fin de cada frase."""
    gate = VADGate(vad, start_time=10.0)
    gate.push(np.zeros(16_000 * 2, dtype=np.float32))
    assert gate.now == pytest.approx(12.0, abs=0.05)
