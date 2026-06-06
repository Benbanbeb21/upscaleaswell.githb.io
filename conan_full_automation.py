import os
import re
import subprocess
import requests
import feedparser
import time
from datetime import datetime

# CONFIGURATION
API_KEY = "a7165e18e69dc32127258688"
BASE_URL = "https://streamp2p.com/api/v1"
HEADERS = {"api-token": API_KEY}
OUTPUT_DIR = "/home/ubuntu/conan_automation/output"
DOWNLOAD_DIR = "/home/ubuntu/conan_automation/downloads"
TENSORPIX_BOT_PATH = "/home/ubuntu/upload/tensorpix-bot-v6.py"

os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# --- UTILS ---
def get_latest_episode():
    print("Searching nyaa.si for latest Detective Conan episode...")
    # Search for 1080p versions, excluding multisub if possible via query or filtering
    rss_url = "https://nyaa.si/?page=rss&q=Detective+Conan+1080p&c=1_2&f=0"
    feed = feedparser.parse(rss_url)
    
    for entry in feed.entries:
        # Simple regex to find episode number
        match = re.search(r" - (\d+) ", entry.title)
        if match:
            ep_num = match.group(1)
            return {
                "title": entry.title,
                "link": entry.link,
                "ep_num": ep_num
            }
    return None

def download_torrent(link, title):
    print(f"Downloading torrent: {title}")
    # Using aria2 for efficient downloading
    subprocess.run([
        "aria2c", "--dir", DOWNLOAD_DIR, 
        "--seed-time=0", 
        "--summary-interval=0",
        link
    ], check=True)
    
    # Find the downloaded file
    for f in os.listdir(DOWNLOAD_DIR):
        if f.endswith(".mkv") or f.endswith(".mp4"):
            return os.path.join(DOWNLOAD_DIR, f)
    return None

# --- STREAMP2P API ---
def get_or_create_folder(name, parent_id=0):
    # List folders to check if exists
    r = requests.get(f"{BASE_URL}/video/folder", headers=HEADERS)
    folders = r.json()
    if isinstance(folders, list):
        for f in folders:
            if f.get('name') == name and f.get('parent_id') == parent_id:
                return f.get('id')
    
    # Create if not found
    payload = {"name": name, "parent_id": parent_id}
    r = requests.post(f"{BASE_URL}/video/folder", headers=HEADERS, json=payload)
    return r.json().get('data', {}).get('id')

def upload_file(file_path, folder_id):
    upload_info = requests.get(f"{BASE_URL}/video/upload", headers=HEADERS).json()
    upload_url = upload_info.get('tusUrl')
    access_token = upload_info.get('accessToken')
    
    if not upload_url:
        print(f"Failed to get upload endpoint for {file_path}")
        return None
    
    files = {'file': open(file_path, 'rb')}
    headers = {"api-token": API_KEY, "access-token": access_token}
    params = {'folder_id': folder_id}
    
    print(f"Uploading {os.path.basename(file_path)} to folder {folder_id}...")
    response = requests.post(upload_url, headers=headers, files=files, params=params)
    return response.json()

def setup_folders(main_name):
    main_id = get_or_create_folder(main_name)
    soft_id = get_or_create_folder("Soft Sub", parent_id=main_id)
    hard_id = get_or_create_folder("Hard Sub", parent_id=main_id)
    return soft_id, hard_id

# --- PROCESSING ---
def process_part1(input_path, ep_num):
    hardsub_path = os.path.join(OUTPUT_DIR, f"Detective_Conan_{ep_num}_1080p_Hardsub.mp4")
    downscale_path = os.path.join(OUTPUT_DIR, f"Detective_Conan_{ep_num}_720p_Downscale.mkv")
    
    # Watermark: DCAIM, top-left, white with slight transparency and shadow
    watermark = "drawtext=text='DCAIM':x=20:y=20:fontsize=48:fontcolor=white@0.8:shadowcolor=black:shadowx=2:shadowy=2"
    
    print("Hard-subbing and watermarking 1080p version...")
    subprocess.run([
        "ffmpeg", "-i", input_path, 
        "-vf", f"subtitles='{input_path}',{watermark}", 
        "-c:v", "libx264", "-crf", "18", "-preset", "fast", 
        "-c:a", "aac", "-b:a", "192k", 
        hardsub_path, "-y"
    ], check=True)
    
    print("Creating watermarked 720p downscale...")
    subprocess.run([
        "ffmpeg", "-i", input_path, 
        "-vf", f"scale=-1:720,{watermark}", 
        "-c:v", "libx264", "-crf", "17", "-preset", "slow", 
        "-c:a", "aac", "-b:a", "192k", 
        downscale_path, "-y"
    ], check=True)
    
    return hardsub_path, downscale_path

def create_torrent(file_path, ep_num):
    print(f"Creating torrent file for {os.path.basename(file_path)}...")
    torrent_path = os.path.join(OUTPUT_DIR, f"Detective_Conan_{ep_num}_4K.torrent")
    
    # Using a dummy announce URL as requested for web seeds access
    # You might want to replace this with your actual tracker or web seed URL
    web_seed_url = "https://your-server.com/downloads/" 
    
    subprocess.run([
        "mktorrent", "-p", "-a", "udp://tracker.openbittorrent.com:80",
        "-w", web_seed_url,
        "-o", torrent_path,
        file_path
    ], check=True)
    return torrent_path

def process_part2(input_720p, ep_num):
    temp_upscaled = os.path.join(OUTPUT_DIR, f"temp_upscaled_{ep_num}.mkv")
    final_upscaled = os.path.join(OUTPUT_DIR, f"Detective_Conan_{ep_num}_4K_Upscaled_10bit.mkv")
    
    print(f"Upscaling to 4K using TensorPix bot...")
    subprocess.run([
        "python3", TENSORPIX_BOT_PATH,
        "--input", input_720p,
        "--segments", "25",
        "--output", temp_upscaled
    ], check=True)
    
    # Post-process to ensure 10-bit and ~6GB size
    # Watermark for 4K needs to be larger
    watermark_4k = "drawtext=text='DCAIM':x=40:y=40:fontsize=96:fontcolor=white@0.8:shadowcolor=black:shadowx=4:shadowy=4"
    
    # For ~24 mins, 6GB is roughly 34Mbps bitrate
    print("Post-processing to 10-bit 4K with watermark (targeting ~6GB)...")
    subprocess.run([
        "ffmpeg", "-i", temp_upscaled,
        "-vf", watermark_4k,
        "-c:v", "libx265", "-pix_fmt", "yuv420p10le", 
        "-b:v", "34M", "-maxrate", "40M", "-bufsize", "60M",
        "-c:a", "copy", 
        final_upscaled, "-y"
    ], check=True)
    
    if os.path.exists(temp_upscaled):
        os.remove(temp_upscaled)

    upscaled_hardsub = os.path.join(OUTPUT_DIR, f"Detective_Conan_{ep_num}_4K_Upscaled_Hardsub.mp4")
    print("Hard-subbing watermarked upscaled 4K version...")
    subprocess.run([
        "ffmpeg", "-i", final_upscaled, 
        "-vf", f"subtitles='{final_upscaled}'", 
        "-c:v", "libx264", "-pix_fmt", "yuv420p10le", "-crf", "18", "-preset", "fast", 
        "-c:a", "aac", "-b:a", "192k", 
        upscaled_hardsub, "-y"
    ], check=True)
    
    return final_upscaled, upscaled_hardsub

# --- MAIN ---
def main():
    episode = get_latest_episode()
    if not episode:
        print("No new episode found.")
        return
    
    print(f"Processing Episode {episode['ep_num']}: {episode['title']}")
    
    # 1. Download
    video_1080p = download_torrent(episode['link'], episode['title'])
    if not video_1080p:
        return

    # 2. Part 1 Processing
    hard_1080p, soft_720p = process_part1(video_1080p, episode['ep_num'])
    
    # 3. Part 1 Upload
    latest_soft_id, latest_hard_id = setup_folders("Detective Conan Latest")
    upload_file(video_1080p, latest_soft_id)
    upload_file(soft_720p, latest_soft_id)
    upload_file(hard_1080p, latest_hard_id)
    
    # 4. Part 2 Processing
    upscaled_soft, upscaled_hard = process_part2(soft_720p, episode['ep_num'])
    
    # 5. Part 2 Upload
    up_soft_id, up_hard_id = setup_folders("Detective Conan Upscaled")
    upload_file(upscaled_soft, up_soft_id)
    upload_file(upscaled_hard, up_hard_id)
    
    # 6. Create Torrent
    torrent_file = create_torrent(upscaled_soft, episode['ep_num'])
    print(f"Torrent file created at: {torrent_file}")
    
    # Cleanup
    print("Cleaning up intermediate files...")
    for f in [hard_1080p, upscaled_hard]:
        if os.path.exists(f):
            os.remove(f)
    
    print(f"Successfully completed workflow for episode {episode['ep_num']}")

if __name__ == "__main__":
    # Pre-create folders on StreamP2P
    print("Pre-creating StreamP2P folder structures...")
    setup_folders("Detective Conan Latest")
    setup_folders("Detective Conan Upscaled")
    
    main()
