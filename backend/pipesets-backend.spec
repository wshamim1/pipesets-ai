# PyInstaller spec for the desktop app's backend.
#
#   .venv/bin/python -m pip install -r requirements-build.txt
#   .venv/bin/python -m PyInstaller pipesets-backend.spec --noconfirm
#
# Produces dist/pipesets-backend/ (one folder: the executable plus its libraries).
# Docling and its ML stack (torch, transformers, OCR) are left out on purpose — the docling
# tool reports "package not found" in the desktop app until it's offered as an add-on.
from PyInstaller.utils.hooks import collect_all, collect_submodules

# Our own packages: tools/ and loaders/ register modules found by pkgutil at runtime, and
# routers/services import each other lazily, so PyInstaller's static scan misses some.
hiddenimports = ["main"]
for pkg in ("routers", "services", "tools", "loaders", "exporters", "uvicorn"):
    hiddenimports += collect_submodules(pkg)

# Third-party packages only imported inside functions
hiddenimports += [
    "alembic", "psycopg2", "psycopg2.extras", "pymysql", "pymysql.cursors", "dateutil", "ddgs",
    "bs4", "docx", "pypdf", "openpyxl", "reportlab", "boto3", "jsonschema", "yaml", "croniter",
]

datas = [
    ("alembic.ini", "."),
    ("migrations", "migrations"),
    ("data", "data"),
    ("llm/prices", "llm/prices"),   # the LLM gateway's price tables (llm/pricing.py)
]
binaries = []

# LiteLLM loads JSON price maps / provider configs and tokenizer files from its package dir.
# It is an optional fallback now, so a build without it still works.
for pkg in ("litellm", "tiktoken", "tiktoken_ext"):
    try:
        pkg_datas, pkg_binaries, pkg_hidden = collect_all(pkg)
    except Exception:
        continue
    # LiteLLM's proxy server (admin web UI, swagger, OpenAPI snapshot) is ~36 MB of data
    # files we never serve; its Python modules stay, since core LiteLLM imports some of them
    datas += [(src, dest) for src, dest in pkg_datas if not dest.replace("\\", "/").startswith("litellm/proxy")]
    binaries += pkg_binaries
    hiddenimports += pkg_hidden

excludes = [
    "docling", "docling_core", "docling_parse", "docling_ibm_models",
    "torch", "torchvision", "torchaudio", "transformers", "sentence_transformers", "detoxify",
    "rapidocr", "rapidocr_onnxruntime", "onnxruntime", "easyocr", "cv2",
    "scipy", "sympy", "crawl4ai", "playwright",
    "pandas",  # never imported by the backend; pulled in only by optional extras
    "tkinter", "matplotlib", "IPython", "pytest",
]

a = Analysis(
    ["desktop_main.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=excludes,
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="pipesets-backend",
    console=True,
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="pipesets-backend", upx=False)
