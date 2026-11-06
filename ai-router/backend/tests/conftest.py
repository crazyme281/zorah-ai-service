import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tempfile
# Never let tests touch the real chat store.
os.environ.setdefault("LEARNED_CHAT_STORE", os.path.join(tempfile.mkdtemp(), "chat_learned.json"))

# Operational state (kill switch, budget, decision log, audit log) goes to a
# throwaway folder so tests never write into the repo.
os.environ.setdefault("OPS_DATA_DIR", tempfile.mkdtemp())
# The shared API instance must not rate-limit the many test requests; the
# limiter itself is tested with its own small limits in test_ops.py.
os.environ.setdefault("RATE_LIMIT_IP_PER_MIN", "100000")
os.environ.setdefault("RATE_LIMIT_SESSION_PER_MIN", "100000")