import os

# ROOT DATA FOLDER
# Override with OPEN_NOTEBOOK_DATA_DIR to relocate persistent application data
# outside the repository (downstream Windows: E:\Maintenance_Ai_Agent_Data).
# Unset preserves the historical ./data behavior. Must be set before process
# start: api/routers/sources.py, commands/podcast_commands.py, and the graph
# modules bind these paths at import time.
DATA_FOLDER = (
    os.environ.get("OPEN_NOTEBOOK_DATA_DIR", "").strip().rstrip("/\\") or "./data"
)

# LANGGRAPH CHECKPOINT FILE
sqlite_folder = f"{DATA_FOLDER}/sqlite-db"
os.makedirs(sqlite_folder, exist_ok=True)
LANGGRAPH_CHECKPOINT_FILE = f"{sqlite_folder}/checkpoints.sqlite"

# UPLOADS FOLDER
UPLOADS_FOLDER = f"{DATA_FOLDER}/uploads"
os.makedirs(UPLOADS_FOLDER, exist_ok=True)

# PODCASTS FOLDER
# Matches the root that build_episode_output_dir() (commands/podcast_commands.py)
# creates episode directories under when called with DATA_FOLDER in production.
PODCASTS_FOLDER = f"{DATA_FOLDER}/podcasts"
os.makedirs(PODCASTS_FOLDER, exist_ok=True)

# TIKTOKEN CACHE FOLDER
# Reads TIKTOKEN_CACHE_DIR from the environment so Docker can redirect the cache
# to a path outside /data/ (which is typically volume-mounted and would hide the
# pre-baked encoding baked into the image at build time). An explicit
# TIKTOKEN_CACHE_DIR always wins; otherwise the cache follows DATA_FOLDER
# (and therefore OPEN_NOTEBOOK_DATA_DIR when set).
TIKTOKEN_CACHE_DIR = os.environ.get("TIKTOKEN_CACHE_DIR", "").strip() or f"{DATA_FOLDER}/tiktoken-cache"
os.makedirs(TIKTOKEN_CACHE_DIR, exist_ok=True)
