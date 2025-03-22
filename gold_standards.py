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
# Session State Initialization
# ----------------------------
if "img_index" not in st.session_state:
    st.session_state.img_index = 0
if "labeled_images" not in st.session_state:
    st.session_state.labeled_images = set()
if "df" not in st.session_state:
    # Initialize as an empty DataFrame with proper columns.
    st.session_state.df = pd.DataFrame(columns=["SubjectID", "Image", "Subfolder", "Description", "Timestamp"])
if "csv_file_id" not in st.session_state:
    st.session_state.csv_file_id = None
if "exit" not in st.session_state:
    st.session_state.exit = False
if "error_msg" not in st.session_state:
    st.session_state.error_msg = ""

# ----------------------------
# Exit Screen
# ----------------------------
if st.session_state.exit:
    st.markdown("## Thanks and come back later!")
    st.stop()

# ----------------------------
# Authentication and Setup
# ----------------------------
SCOPES = ["https://www.googleapis.com/auth/drive"]
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
    If found, download and return it as a DataFrame along with its file ID.
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
    If file_id is provided, update that file; otherwise, create a new file in FOLDER_ID.
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

def save_current_description(index, current_image, subject_id):
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
    st.session_state.csv_file_id = save_csv_to_drive(subject_id, st.session_state.df, st.session_state.csv_file_id)

# ----------------------------
# App UI
# ----------------------------
st.title("Gold Standard Descriptions")
subject_id = st.text_input("Enter your Rater ID:")

if subject_id:
    # Load CSV from Drive (only once)
    if st.session_state.df.empty:
        df, file_id = load_csv_from_drive(subject_id)
        if not df.empty:
            st.session_state.df = df
            st.session_state.csv_file_id = file_id
            # Only mark images as labeled if description is non-empty
            st.session_state.labeled_images = set(df.loc[df["Description"].str.strip() != "", "Image"])
    
    # Retrieve and sort all images from the Drive folder
    image_files = sorted(fetch_all_images(FOLDER_ID), key=lambda x: (x["subfolder"], x["name"], x["id"]))
    # Filter out images that have been labeled with non-empty description
    unlabeled_images = [img for img in image_files if img["name"] not in st.session_state.labeled_images]
    
    if st.session_state.img_index >= len(unlabeled_images):
        st.success("All images have been labeled! 🎉")
    else:
        current_image = unlabeled_images[st.session_state.img_index]
        img_bytes = download_image_bytes(current_image["id"])
        
        # Calculate caption: show subfolder and image position within that subfolder
        subfolder_images = [img for img in image_files if img["subfolder"] == current_image["subfolder"]]
        try:
            current_sub_index = subfolder_images.index(current_image) + 1
        except ValueError:
            current_sub_index = 1
        total_in_subfolder = len(subfolder_images)
        caption = (f"{current_image['subfolder']}: Image {current_sub_index} of {total_in_subfolder}"
                   if current_image["subfolder"] else f"Image {current_sub_index} of {total_in_subfolder}")
        
        st.image(img_bytes, caption=caption, width=400)
        # Create a text area for the description with a dynamic key
        description_key = f"description_input_{st.session_state.img_index}"
        st.text_area("Enter description for this image", key=description_key)
        
        # Display error message (if any) right below the text area
        if st.session_state.error_msg:
            st.error(st.session_state.error_msg)
        
        # Define callbacks for the buttons using on_click
        def save_and_next_callback():
            idx = st.session_state.img_index
            desc = st.session_state.get(f"description_input_{idx}", "").strip()
            if not desc:
                st.session_state.error_msg = "Description cannot be empty."
                return  # Do not advance
            else:
                st.session_state.error_msg = ""
                save_current_description(idx, current_image, subject_id)
                st.session_state.img_index = idx + 1
        
        def exit_app_callback():
            idx = st.session_state.img_index
            if st.session_state.get(f"description_input_{idx}", "").strip():
                save_current_description(idx, current_image, subject_id)
            st.session_state.exit = True
        
        col1, col2 = st.columns(2)
        col1.button("Save and Next", on_click=save_and_next_callback)
        col2.button("Exit", on_click=exit_app_callback)
