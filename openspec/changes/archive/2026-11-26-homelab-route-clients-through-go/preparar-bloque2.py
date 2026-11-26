"""Prepara fuentes aprobadas para las verificaciones aisladas del Bloque 2."""

import io
import subprocess
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
BASE = "0b9ee672b9a644a201ca60596786009bafc23ca8"
SERVICES = ("estimador-cag", "estimator-web-go")
NEW_FILES = (
    "estimador-cag/app/api/disconnect.py",
    "estimador-cag/tests/block2_sse_fixture.py",
    "estimator-web-go/internal/estimatorai/public.go",
    "estimator-web-go/internal/estimatorai/contracts.go",
    "estimator-web-go/internal/estimatorai/stream.go",
    "estimator-web-go/internal/web/api.go",
    "estimator-web-go/internal/web/api_test.go",
    "estimator-web-go/internal/web/api_stream.go",
    "estimator-web-go/internal/web/api_stream_test.go",
    "estimator-web-go/internal/web/api_stream_integration_test.go",
    "estimator-web-go/internal/web/authorization.go",
    "estimator-web-go/internal/web/authorization_test.go",
)


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT)


def source_files():
    changed = git("diff", "--name-only", "-z", BASE, "--", *SERVICES).decode().split("\0")
    with tarfile.open(fileobj=io.BytesIO(git("archive", BASE, *SERVICES))) as archive:
        files = {}
        for member in archive:
            if member.isdir():
                continue
            if not member.isfile():
                raise SystemExit(f"Entrada no regular: {member.name}")
            files[Path(member.name)] = archive.extractfile(member).read()
    for name in filter(None, (*changed, *NEW_FILES)):
        path = Path(name)
        source = ROOT / path
        if not source.exists() and name in NEW_FILES:
            continue
        if (path.suffix not in {".go", ".py"} or not source.is_file() or source.resolve() != source):
            raise SystemExit(f"Fuente de verificación inesperada: {name}")
        files[path] = source.read_bytes()
    return files


def main():
    root = ROOT / ".block2"
    target = root / "fuentes"
    docker_config = root / "docker-config"
    for directory in (root, target, docker_config):
        if directory.is_symlink():
            raise SystemExit(f"No se admite un enlace simbólico: {directory.name}")
        directory.mkdir(mode=0o700, exist_ok=True)
    files = source_files()
    for path in target.rglob("*"):
        if path.is_symlink() or not (path.is_dir() or (path.is_file() and path.relative_to(target) in files)):
            raise SystemExit(f"Entrada ajena a las fuentes aprobadas: {path.relative_to(target)}")
    for path, content in files.items():
        destination = target / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        if not destination.exists() or destination.read_bytes() != content:
            destination.write_bytes(content)
    config = docker_config / "config.json"
    if config.is_symlink() or (config.exists() and config.read_bytes() != b"{}\n"):
        raise SystemExit("La configuración Docker de pruebas no está vacía.")
    if not config.exists():
        config.write_bytes(b"{}\n")
    print(f"Fuentes del Bloque 2 verificadas: {len(files)} archivos.")


if __name__ == "__main__":
    main()
