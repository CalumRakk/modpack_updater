import argparse
import json
import mimetypes
import shutil
import subprocess
import sys
import tempfile
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional, Union


def parse_args():
    parser = argparse.ArgumentParser(
        description="Sincroniza el modpack de Minecraft con la última versión de Modrinth."
    )
    parser.add_argument(
        "--minecraft", required=True, help="Ruta a la carpeta del perfil de Minecraft"
    )
    parser.add_argument(
        "--api", required=True, help="URL de la API de Modrinth para el modpack"
    )
    return parser.parse_args()


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
                        "content": z.read(name),
                    }
                )

    return result


def has_last_modpack_version(last_version: str):
    """Comprueba si tiene la ultima version del 'archivo .mrpack' descargada"""

    if not MODPACKS_FOLDER.exists():
        return False

    # Comprobar si el archivo .mrpack corresponde a la última versión
    for file in list(MODPACKS_FOLDER.glob("*.mrpack")):
        if last_version in file.name:
            return True
    return False


def get_last_modpack_version() -> Optional[Path]:
    """Obtiene la ultima version del 'archivo .mrpack' descargada"""
    if not MODPACKS_FOLDER.exists():
        return None

    mrpack_files = list(MODPACKS_FOLDER.glob("*.mrpack"))
    if not mrpack_files:
        return None

    latest_mrpack = max(mrpack_files, key=lambda f: f.stat().st_mtime)
    return MODPACKS_FOLDER / latest_mrpack


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


def sync_mods_folder(files_from_mrpack):
    """Sincroniza la carpeta /mods con los archivos del modpack.

    - Conserva mods idénticos (mismo nombre y tamaño)
    - Elimina mods que ya no existen en el .mrpack
    - Devuelve lista de mods que deben descargarse
    """
    folder_mods = MINECRAFT_FOLDER / "mods"
    folder_mods.mkdir(exist_ok=True)

    # Mapear mods esperados (por nombre -> tamaño)
    expected = {Path(f["path"]).name: f["fileSize"] for f in files_from_mrpack}

    # Mods existentes en disco
    existing = {f.name: f.stat().st_size for f in folder_mods.glob("*.jar")}

    to_delete = []
    to_download = []

    # --- Detectar mods sobrantes ---
    for name in existing:
        if name not in expected:
            to_delete.append(name)

    # --- Detectar mods faltantes o distintos ---
    for name, size in expected.items():
        if name not in existing or existing[name] != size:
            to_download.append(name)

    # --- Eliminar mods sobrantes ---
    for name in to_delete:
        path = folder_mods / name
        path.unlink(missing_ok=True)
        print(f"🗑️ Eliminado mod sobrante: {name}")

    # --- Mostrar resumen ---
    print(f"\n- {len(to_download)} mods necesitan descargarse.")
    print(f"- {len(existing) - len(to_delete)} mods conservados.\n")

    # Devolver lista de archivos que hay que descargar
    return [f for f in files_from_mrpack if Path(f["path"]).name in to_download]


def download_mod(file: dict, base_folder: Path):
    """Descarga un solo mod."""
    path = base_folder / file["path"]
    url = file["downloads"][0]
    filesize = file["fileSize"]

    if path.exists() and path.stat().st_size == filesize:
        return f"✔ {file['path']} (ya actualizado)"

    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        with open(path, "wb") as f:
            f.write(response.content)
        return f"✔ {file['path']} (descargado)"
    except Exception as e:
        return f"⚠️ Error en {file['path']}: {e}"


def main():
    modpack_versions = fetch_modpack_versions(MODPACK_API_URL)
    if not modpack_versions:
        return

    last_version_filename = modpack_versions[0]["files"][0]["filename"]
    last_version_url = modpack_versions[0]["files"][0]["url"]

    if not has_last_modpack_version(last_version_filename):
        print(f"Descargando la versión {last_version_filename} del modpack...")

        folder_temp = tempfile.TemporaryDirectory()
        mrpack_path = Path(folder_temp.name) / last_version_filename
        download_modpack(last_version_url, mrpack_path)

        print("Leyendo el contenido del modpack descargado...")
        data = read_mrpack(mrpack_path)

        print("\nDescargando mods en paralelo...\n")
        files_from_pack = data["modrinth.index.json"]["files"]  # type: ignore
        files_to_download = sync_mods_folder(files_from_pack)

        # --- Descargas concurrentes ---
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [
                executor.submit(download_mod, file, MINECRAFT_FOLDER)
                for file in files_to_download
            ]
            for future in as_completed(futures):
                print(future.result())

        # --- Sobrescribir overrides ---
        print("\nAplicando overrides...")
        for file in data["overrides"]:
            path = MINECRAFT_FOLDER / file["path"]
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "wb") as f:
                content = file["content"]
                if isinstance(content, str):
                    content = content.encode("utf-8", errors="ignore")
                f.write(content)
            print(f"✔ {file['path']} (override aplicado)")

        print("\n✅ Modpack actualizado correctamente.")
        MODPACKS_FOLDER.mkdir(parents=True, exist_ok=True)
        shutil.move(mrpack_path, MODPACKS_FOLDER / last_version_filename)

    else:
        print("\n✅ Modpack ya ha sido actualizado.")


if __name__ == "__main__":
    MINECRAFT_FOLDER = Path("CARPETA DE TU MINECRAFT")
    MODPACK_API_URL = "https://api.modrinth.com/v2/project/la-casita-del-arbol/version"
    MODPACKS_FOLDER = MINECRAFT_FOLDER / "modpacks"
    requests = get_or_install_requests()

    main()
