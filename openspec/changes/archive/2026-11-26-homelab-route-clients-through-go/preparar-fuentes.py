"""Materializa fuentes de la revisión aprobada y las tres pruebas del Bloque 1."""

import io
import subprocess
import tarfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
BASE = "307a8b9"
SERVICES = ("estimador-cag", "estimator-web-go", "estimator-web-react")
TESTS = (
    "estimador-cag/tests/test_stream_disconnect.py",
    "estimator-web-go/internal/rag/pgstore_test.go",
    "estimator-web-go/internal/web/lab_test.go",
)


def inputs():
    archive = subprocess.check_output(["git", "archive", BASE, *SERVICES], cwd=ROOT)
    files = {}
    with tarfile.open(fileobj=io.BytesIO(archive)) as sources:
        for member in sources:
            if member.isdir():
                continue
            if not member.isfile():
                raise SystemExit(f"Entrada no regular en la revisión aprobada: {member.name}")
            files[Path(member.name)] = sources.extractfile(member).read()
    for name in TESTS:
        path = ROOT / name
        if not path.is_file() or path.resolve() != path:
            raise SystemExit(f"Se esperaba una prueba local regular: {name}")
        files[Path(name)] = path.read_bytes()
    # Evita que el cliente Docker herede proxies o helpers de credenciales del host.
    files[Path("docker-config/config.json")] = b"{}\n"
    return files


def main():
    target = ROOT / ".block1"
    files = inputs()
    if target.is_symlink():
        raise SystemExit("La ruta .block1 debe ser un directorio local.")
    if target.exists():
        entries = list(target.rglob("*"))
        if any(path.is_symlink() or not (path.is_file() or path.is_dir()) for path in entries):
            raise SystemExit("La copia de fuentes contiene una entrada no regular.")
        if {path.relative_to(target) for path in entries if path.is_file()} != files.keys():
            raise SystemExit("La copia de fuentes no coincide con la lista aprobada.")
        if any((target / path).read_bytes() != content for path, content in files.items()):
            raise SystemExit("La copia de fuentes difiere de las entradas aprobadas.")
    else:
        target.mkdir(mode=0o700)
        for path, content in files.items():
            copy = target / path
            copy.parent.mkdir(parents=True, exist_ok=True)
            copy.write_bytes(content)
    print(f"Fuentes de caracterización verificadas: {len(files)} archivos en .block1")


if __name__ == "__main__":
    main()
