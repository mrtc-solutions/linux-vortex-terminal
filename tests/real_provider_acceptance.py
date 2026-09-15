"""Opt-in real GGUF inference. No fixture weights or test engine are accepted.

VORTEX_REAL_MODEL must name a real downloaded GGUF outside the repository.
Requires a working llama-cpp-python installation. This proves inference transport,
not model answer quality or compatibility with every model/provider.
"""
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backend.models import gguf


def main():
    model = Path(os.environ['VORTEX_REAL_MODEL']).resolve(strict=True)
    if model.stat().st_size < 1024 * 1024:
        raise RuntimeError('A real model with weights is required, not a GGUF header fixture')
    with tempfile.TemporaryDirectory(prefix='vortex-provider-') as tmp:
        os.environ.update(VORTEX_DATA_DIR=tmp, VORTEX_CONFIG_DIR=tmp + '/config', VORTEX_MODELS_DIR=str(model.parent))
        gguf.set_test_engine(None)
        snapshot = gguf.scan(str(model.parent), use_cache=False)
        entry = next(item for item in snapshot['valid_files'] if Path(item['path']) == model)
        result = gguf.complete(entry, 'Continue the short story.', 'Once upon a time there was a little rabbit',
                               {'gguf_ctx': 512, 'gguf_threads': 2}, timeout=120)
        assert result['engine'] in ('python', 'cli'), result
        assert result['text'].strip(), 'Real model returned no text'
        gguf.unload()
        digest = hashlib.sha256(model.read_bytes()).hexdigest()
        print(json.dumps({'result': 'PASS', 'engine': result['engine'], 'model': model.name,
                          'model_sha256': digest, 'generated_characters': len(result['text']),
                          'latency_ms': result['latency_ms'], 'test_double': False}))


if __name__ == '__main__':
    main()
