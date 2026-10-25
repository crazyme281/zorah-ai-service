import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tempfile
# Never let tests touch the real chat store.
os.environ.setdefault("LEARNED_CHAT_STORE", os.path.join(tempfile.mkdtemp(), "chat_learned.json"))