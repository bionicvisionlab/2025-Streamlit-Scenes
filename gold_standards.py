import streamlit as st
import pandas as pd
from googleapiclient.discovery import build
from google.oauth2 import service_account
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload
import datetime
import os
from io import BytesIO
import json

# --------------------------------
# Session State Initialization
# --------------------------------
if "pointer" not in st.session_state:
    st.session_state.pointer = 0
if "df" not in st.session_state:
    st.session_state.df = pd.DataFrame(
        columns=["SubjectID", "Image", "Subfolder", "Description", "Timestamp"]
    )
if "csv_file_id" not in st.session_state:
    st.session_state.csv_file_id = None
if "exit" not in st.session_state:
    st.session_state.exit = False
if "error_msg" not in st.session_state:
    st.session_state.error_msg = ""
if "master_images" not in st.session_state:
    st.session_state.master_images = None

# --------------------------------
# Exit Screen
# --------------------------------
if st.session_state.exit:
    st.markdown("## Thanks and come back later!")
    st.stop()

# --------------------------------
# Authentication and Setup
# --------------------------------
SCOPES = ["https://www.googleapis.com/auth/drive"]
service_account_info = json.loads(st.secrets["google"]["service_account_json"])
creds = service_account.Credentials.from_service_account_info(service_account_info, scopes=SCOPES)
drive_service = build("drive", "v3", credentials=creds)
FOLDER_ID = "1c0NESrnsa2VTHWYf73pAVR2FmTx9ehe6"

def fetch_all_images(folder_id, parent_folder_name=""):
    """Recursively retrieve images from Google Drive subfolders."""
    images = []
    response = drive_service.files().list(
        q=f"'{folder_id}' in parents", 
        fields="files(id, name, mimeType)",
        pageSize=150
    ).execute()
    for file in response.get("files", []):
        if file["mimeType"] == "application/vnd.google-apps.folder":
            subfolder_name = f"{parent_folder_name}/{file['name']}" if parent_folder_name else file["name"]
            images.extend(fetch_all_images(file["id"], subfolder_name))
        elif file["mimeType"].startswith("image/"):
            images.append({
                "id": file["id"],
                "name": file["name"],
                "subfolder": parent_folder_name
            })
    return images

def download_image_bytes(file_id):
    """Download image bytes from Google Drive."""
    request = drive_service.files().get_media(fileId=file_id)
    fh = BytesIO()
    downloader = MediaIoBaseDownload(fh, request)
    done = False
    while 
