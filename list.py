import importlib

# Non-default packages you want to check
packages = [
    "flask",
    "flask_sqlalchemy",
    "werkzeug",
    "sqlalchemy"
]

for pkg in packages:
    try:
        module = importlib.import_module(pkg)
        version = getattr(module, "__version__", "Unknown version attr")
        print(f"{pkg}: {version}")
    except ImportError:
        print(f"{pkg}: Not installed")
