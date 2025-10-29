import json
import mimetypes
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Optional, Union


def get_or_install_requests():
    try:
        import requests
    except ImportError:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "requests"])
        import requests
    return requests


def guess_type(name):
    t, _ = mimetypes.guess_type(name)
    return t or "application/octet-stream"


def read_mrpack(path: Union[str, Path]):
    path = Path(path) if isinstance(path, str) else path

    result = {"modrinth.index.json": [], "overrides": []}
    with zipfile.ZipFile(path, "r") as z:
        namelist = z.namelist()

        # --- 1. Extraer metadatos del índice ---
        if "modrinth.index.json" in namelist:
            with z.open("modrinth.index.json") as f:
                index_data = json.load(f)
                result["modrinth.index.json"] = index_data

        # --- 2. Archivos incrustados (overrides/, etc.) ---
        for name in namelist:
            if name.startswith("overrides/"):
                result["overrides"].append(
                    {
                        "path": name.removeprefix("overrides/"),
                        "type": guess_type(name),
                        "content": z.read(name),
                    }
                )

    return result


def has_last_modpack_version(last_version: str):
    """Comprueba si tiene la ultima version del 'archivo .mrpack' descargada"""

    if not FOLDER_MODPACKS.exists():
        return False

    # Comprobar si el archivo .mrpack corresponde a la última versión
    for file in list(FOLDER_MODPACKS.glob("*.mrpack")):
        if last_version in file.name:
            return True
    return False


def get_last_modpack_version() -> Optional[Path]:
    """Obtiene la ultima version del 'archivo .mrpack' descargada"""
    if not FOLDER_MODPACKS.exists():
        return None

    mrpack_files = list(FOLDER_MODPACKS.glob("*.mrpack"))
    if not mrpack_files:
        return None

    latest_mrpack = max(mrpack_files, key=lambda f: f.stat().st_mtime)
    return FOLDER_MODPACKS / latest_mrpack


def download_modpack(version_url: str, output_path: Path):
    """Descarga el archivo .mrpack de la version especificada"""
    response = requests.get(version_url)

    if response.status_code == 200:
        with open(output_path, "wb") as f:
            f.write(response.content)
        print(f"modpacks descargado en: {output_path}")
        return output_path
    else:
        print(f"Error al descargar el modpacks: {response.status_code}")
        return None


def fetch_modpack_versions(url):
    response = requests.get(url)
    if response.status_code == 200:
        versions = response.json()
        return versions
    else:
        print(f"Error al obtener versiones: {response.status_code}")
        return None


def remove_content_of_folder_mods():
    folder_mods = FOLDER_MINECRAFT / "mods"
    if folder_mods.exists():
        for mod_file in folder_mods.glob("*"):
            mod_file.unlink()


def main():
    modpack_versions = fetch_modpack_versions(URL_MODPACK)
    if not modpack_versions:
        return

    last_version_filename = modpack_versions[0]["files"][0]["filename"]
    last_version_url = modpack_versions[0]["files"][0]["url"]
    if not has_last_modpack_version(last_version_filename):
        print(f"Descargando la versión {last_version_filename} del modpacks...")

        # folder temporal
        folder_temp = tempfile.TemporaryDirectory()
        mrpack_path = Path(folder_temp.name) / last_version_filename
        download_modpack(last_version_url, mrpack_path)

        print("Leyendo el contenido del modpacks descargado...")
        data = read_mrpack(mrpack_path)

        print("\nContenido de modrinth.index.json:")

        # remove_content_of_folder_mods()

        # for file in data["modrinth.index.json"]["files"]:  # type: ignore
        #     path = FOLDER_MINECRAFT / file["path"]
        #     filesize = file["fileSize"]
        #     url = file["downloads"][0]
        #     if not path.exists() or path.stat().st_size != filesize:
        #         print(f"- {file['path']} (size: {filesize} bytes)")
        #         response = requests.get(url)
        #         path.parent.mkdir(parents=True, exist_ok=True)
        #         with open(path, "wb") as f:
        #             f.write(response.content)

        for file in data["overrides"]:
            path = FOLDER_MINECRAFT / file["path"]
            print(f"- {file['path']} (override)")
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "wb") as f:
                try:
                    f.write(file["content"].encode("utf-8"))
                except Exception as e:
                    f.write(file["content"])
        print("\nModpack actualizado correctamente.")

        # Mover el archivo .mrpack a la carpeta de modpacks
        FOLDER_MODPACKS.mkdir(parents=True, exist_ok=True)
        shutil.move(mrpack_path, FOLDER_MODPACKS / last_version_filename)


if __name__ == "__main__":
    mi_carpeta_de_minecraft = (
        r"C:\Users\Leo\AppData\Roaming\ModrinthApp\profiles\La casita del Arbol 0.0.4"
    )

    # Variables para gestionar los modpacks
    FOLDER_MINECRAFT = Path(mi_carpeta_de_minecraft)
    URL_MODPACK = "https://api.modrinth.com/v2/project/la-casita-del-arbol/version"
    FOLDER_MODPACKS = FOLDER_MINECRAFT / "modpacks"
    requests = get_or_install_requests()

    main()
