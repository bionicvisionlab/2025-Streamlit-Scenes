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
if "labeled_images" not in st.session_state:
    st.session_state.labeled_images = set()

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
creds = service_account.Credentials.from_service_account_info(
    service_account_info, scopes=SCOPES
)
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
    while not done:
        status, done = downloader.next_chunk()
    fh.seek(0)
    return fh.read()

def load_csv_from_drive(subject_id):
    """
    Look for a CSV named "gold_standards_<subject_id>.csv" in FOLDER_ID.
    If found, return it as a DataFrame and its file ID.
    Otherwise, return an empty DataFrame and None.
    """
    filename = f"gold_standards_{subject_id}.csv"
    query = f"name = '{filename}' and '{FOLDER_ID}' in parents and trashed = false"
    results = drive_service.files().list(q=query, fields="files(id, name)").execute()
    files = results.get('files', [])
    if files:
         file_id = files[0]['id']
         request = drive_service.files().get_media(fileId=file_id)
         fh = BytesIO()
         downloader = MediaIoBaseDownload(fh, request)
         done = False
         while not done:
             status, done = downloader.next_chunk()
         fh.seek(0)
         try:
             df = pd.read_csv(fh)
         except Exception:
             df = pd.DataFrame(columns=["SubjectID", "Image", "Subfolder", "Description", "Timestamp"])
         return df, file_id
    else:
         df = pd.DataFrame(columns=["SubjectID", "Image", "Subfolder", "Description", "Timestamp"])
         return df, None

def save_csv_to_drive(subject_id, df, file_id):
    """
    Save the DataFrame as a CSV file to Drive.
    Update if file_id is provided, else create a new file.
    Returns the file ID.
    """
    filename = f"gold_standards_{subject_id}.csv"
    csv_buffer = BytesIO()
    df.to_csv(csv_buffer, index=False)
    csv_buffer.seek(0)
    media = MediaIoBaseUpload(csv_buffer, mimetype='text/csv', resumable=True)
    if file_id:
         updated_file = drive_service.files().update(fileId=file_id, media_body=media).execute()
         return updated_file['id']
    else:
         file_metadata = {
             'name': filename,
             'parents': [FOLDER_ID]
         }
         new_file = drive_service.files().create(body=file_metadata, media_body=media, fields='id').execute()
         return new_file['id']

def save_current_description(pointer, current_image, subject_id):
    """Save or update the description for the current image and update Drive."""
    desc_key = f"description_input
