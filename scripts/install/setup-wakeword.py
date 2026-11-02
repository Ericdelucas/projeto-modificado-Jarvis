#!/usr/bin/env python3
"""Download the small Portuguese Vosk model once; detection then runs offline."""

import argparse
import shutil
import tempfile
import urllib.request
import zipfile
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=Path(".runtime/wakeword"))
    parser.add_argument(
        "--english", action="store_true", help="Instala também o modelo para computer"
    )
    args = parser.parse_args()
    target = args.directory.resolve()
    names = ["vosk-model-small-pt-0.3"]
    if args.english:
        names.append("vosk-model-small-en-us-0.15")
    for name in names:
        install(target, name)


def install(target: Path, name: str):
    model = target / name
    if (model / "final.mdl").is_file() or (model / "am/final.mdl").is_file():
        print(f"Modelo já instalado: {model}")
        return
    target.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryFile() as archive:
        with urllib.request.urlopen(
            f"https://alphacephei.com/vosk/models/{name}.zip",
            timeout=120,
        ) as source:
            shutil.copyfileobj(source, archive)
        archive.seek(0)
        with zipfile.ZipFile(archive) as data:
            for item in data.infolist():
                (target / item.filename).resolve().relative_to(target)
            data.extractall(target)
    print(f"Modelo instalado: {model}")


if __name__ == "__main__":
    main()
