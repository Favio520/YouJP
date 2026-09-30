"""La instancia de Sudachi se comparte entre las sesiones de vídeo."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from youjp.nlp.tokenizer import JapaneseTokenizer


def test_shared_tokenizer_handles_concurrent_sessions():
    tokenizer = JapaneseTokenizer()
    barrier = Barrier(8)
    text = "日本語の字幕を読みながら新しい言葉を勉強しています。" * 30

    def tokenize(_):
        barrier.wait(timeout=10)
        return "".join(token.surface for token in tokenizer.tokenize(text))

    with ThreadPoolExecutor(max_workers=8) as pool:
        assert list(pool.map(tokenize, range(32))) == [text] * 32
