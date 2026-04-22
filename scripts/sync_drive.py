"""
Syncs images and videos from a Google Drive folder into images/ and writes
portfolio-data.json for the site to consume.

Drive folder structure expected:
  <DRIVE_FOLDER_ID>/
    restore/   ← .jpg .jpeg .png .webp .mp4 .mov .webm
    rebuild/
    renew/

Files placed directly in the root folder are categorised as "other" and
still appear in the "All Projects" view.

File name → display title: "kitchen-remodel.jpg" → "Kitchen Remodel"

Required env vars:
  GOOGLE_SERVICE_ACCOUNT_JSON   full JSON string of the service-account key
  DRIVE_FOLDER_ID               ID of the root Drive folder
"""

import io
import json
import os
import re
import sys
from pathlib import Path

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]
VALID_CATEGORIES = {"restore", "rebuild", "renew"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
VIDEO_EXTS = {".mp4", ".mov", ".webm"}

OUTPUT_DIR = Path("images")
MANIFEST_PATH = Path("portfolio-data.json")


def get_service():
    sa_json = os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"]
    info = json.loads(sa_json)
    creds = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def list_children(service, folder_id):
    items, page_token = [], None
    while True:
        resp = (
            service.files()
            .list(
                q=f"'{folder_id}' in parents and trashed=false",
                fields="nextPageToken, files(id, name, mimeType)",
                pageToken=page_token,
            )
            .execute()
        )
        items.extend(resp.get("files", []))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return items


def download(service, file_id, dest: Path):
    dest.parent.mkdir(parents=True, exist_ok=True)
    request = service.files().get_media(fileId=file_id)
    buf = io.BytesIO()
    dl = MediaIoBaseDownload(buf, request)
    done = False
    while not done:
        _, done = dl.next_chunk()
    dest.write_bytes(buf.getvalue())


def to_title(filename: str) -> str:
    stem = Path(filename).stem
    return re.sub(r"[-_]+", " ", stem).title()


def media_type(name: str):
    ext = Path(name).suffix.lower()
    if ext in IMAGE_EXTS:
        return "image"
    if ext in VIDEO_EXTS:
        return "video"
    return None


def main():
    root_id = os.environ["DRIVE_FOLDER_ID"]
    service = get_service()
    manifest = []

    root_items = list_children(service, root_id)

    for item in root_items:
        is_folder = item["mimeType"] == "application/vnd.google-apps.folder"
        name = item["name"]

        if is_folder:
            category = name.lower()
            if category not in VALID_CATEGORIES:
                print(f"  Skipping unknown folder: {name}")
                continue
            for media in list_children(service, item["id"]):
                mtype = media_type(media["name"])
                if not mtype:
                    continue
                dest = OUTPUT_DIR / category / media["name"]
                print(f"  ↓ {category}/{media['name']}")
                download(service, media["id"], dest)
                manifest.append(
                    {
                        "src": f"images/{category}/{media['name']}",
                        "type": mtype,
                        "category": category,
                        "title": to_title(media["name"]),
                    }
                )
        else:
            mtype = media_type(name)
            if not mtype:
                continue
            dest = OUTPUT_DIR / name
            print(f"  ↓ {name}")
            download(service, item["id"], dest)
            manifest.append(
                {
                    "src": f"images/{name}",
                    "type": mtype,
                    "category": "other",
                    "title": to_title(name),
                }
            )

    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2))
    print(f"\nDone. {len(manifest)} file(s) synced → portfolio-data.json written.")


if __name__ == "__main__":
    main()
