import os
from pathlib import Path
from dotenv import load_dotenv
ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / '.env')
RUNTIME = ROOT / 'runtime'
RUNTIME.mkdir(exist_ok=True)
MODE = os.getenv('NLP_MODE', 'lightweight')
EMBEDDING_MODEL = os.getenv('EMBEDDING_MODEL', 'sentence-transformers/all-MiniLM-L6-v2')
NLI_MODEL = os.getenv('NLI_MODEL', 'cross-encoder/nli-deberta-v3-small')
NLI_THRESHOLD = float(os.getenv('NLI_THRESHOLD', '0.80'))
MAX_NLI_PAIRS = max(1, min(200, int(os.getenv('MAX_NLI_PAIRS', '40'))))
MAX_EVIDENCE_CHARS = max(2000, min(60000, int(os.getenv('MAX_EVIDENCE_CHARS', '24000'))))
