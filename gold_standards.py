import streamlit as st
import pandas as pd
from googleapiclient.discovery import build
from google.oauth2 import service_account
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload
import datetime
import os
from io import BytesIO
import json

# ----------------------------
# Authentication and Setup
# ----------------------------
SCOPES = ["https://www.googleapis.com/auth/drive"]
SERVICE_ACCOUNT_FILE = "service-account.json"  # Your credentials JSON file

# Load service account credentials from Streamlit secrets
service_account_info = json.loads(st.secrets["google"]["service_account_json"])
creds = service_account.Credentials.from_service_account_info(service_account_info, scopes=SCOPES)
drive_service = build("drive", "v3", credentials=creds)

# Use your provided folder ID
FOLDER_ID = "1c0NESrnsa2VTHWYf73pAVR2FmTx9ehe6"

def fetch_all_images(folder_id, parent_folder_name=""):
    """Recursively retrieve images from Google Drive subfolders."""
    images = []
    response = drive_service.files().list(
        q=f"'{folder_id}' in parents", 
        fields="files(id, name, mimeType)"
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
    Look for a CSV named "responses_<subject_id>.csv" in FOLDER_ID.
    If found, download and return it as a DataFrame along with its file ID.
    Otherwise, return an empty DataFrame and None.
    """
    filename = f"responses_{subject_id}.csv"
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
    If file_id is provided, update that file; otherwise, create a new file in FOLDER_ID.
    Returns the file ID.
    """
    filename = f"responses_{subject_id}.csv"
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

# ----------------------------
# Session State Initialization
# ----------------------------
if "img_index" not in st.session_state:
    st.session_state.img_index = 0
if "labeled_images" not in st.session_state:
    st.session_state.labeled_images = set()
if "df" not in st.session_state:
    st.session_state.df = None
if "csv_file_id" not in st.session_state:
    st.session_state.csv_file_id = None

# ----------------------------
# App UI
# ----------------------------
st.title("Online Image Labeling Tool")

subject_id = st.text_input("Enter Subject ID:")

if subject_id:
    # Load CSV from drive if not already loaded
    if st.session_state.df is None:
        df, file_id = load_csv_from_drive(subject_id)
        st.session_state.df = df
        st.session_state.csv_file_id = file_id
        st.session_state.labeled_images = set(df["Image"]) if not df.empty else set()

    # Retrieve and sort all images from the drive folder
    image_files = sorted(fetch_all_images(FOLDER_ID), key=lambda x: x["name"])
    # Filter out images that have already been labeled
    unlabeled_images = [img for img in image_files if img["name"] not in st.session_state.labeled_images]

    if st.session_state.img_index >= len(unlabeled_images):
        st.success("All images have been labeled! 🎉")
    else:
        current_image = unlabeled_images[st.session_state.img_index]
        img_bytes = download_image_bytes(current_image["id"])
        st.image(
            img_bytes,
            caption=f"{current_image['subfolder']}/{current_image['name']}",
            width=400,
        )
        # Use a dynamic key based on the current image index so a new text area is created per image.
        description_key = f"description_input_{st.session_state.img_index}"
        description = st.text_area(
            f"Enter description for {current_image['name']}",
            key=description_key
        )

        def save_current_description(index):
            """Save the current description with a timestamp into the DataFrame and update Drive."""
            desc_key = f"description_input_{index}"
            desc = st.session_state.get(desc_key, "")
            timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            new_row = pd.DataFrame(
                [[subject_id, current_image["name"], current_image["subfolder"], desc, timestamp]],
                columns=["SubjectID", "Image", "Subfolder", "Description", "Timestamp"]
            )
            st.session_state.df = pd.concat([st.session_state.df, new_row], ignore_index=True)
            st.session_state.labeled_images.add(current_image["name"])
            # Save updated DataFrame to Drive and update file_id
            st.session_state.csv_file_id = save_csv_to_drive(subject_id, st.session_state.df, st.session_state.csv_file_id)

        def save_and_next():
            current_index = st.session_state.img_index
            save_current_description(current_index)
            st.session_state.img_index += 1
            st.stop()  # Force a re-run immediately so that the next image is displayed

        def exit_app():
            current_index = st.session_state.img_index
            desc_key = f"description_input_{current_index}"
            # Save description if nonempty (without advancing the index)
            if st.session_state.get(desc_key, "").strip():
                save_current_description(current_index)
            # Exit the app without incrementing the index
            import keyboard, psutil
            keyboard.press_and_release('ctrl+w')
            pid = os.getpid()
            p = psutil.Process(pid)
            p.terminate()

        # ----------------------------
        # Buttons (using if/elif to ensure only one is processed)
        # ----------------------------
        col1, col2 = st.columns(2)
        btn_save = col1.button("Save and Next")
        btn_exit = col2.button("Exit")
        if btn_save:
            save_and_next()
        elif btn_exit:
            exit_app()
