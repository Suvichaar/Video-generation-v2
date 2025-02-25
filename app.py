import streamlit as st
import requests
import re
import os
import subprocess

st.header("🎵 Audio Transcription & Subtitle Video Generator")
st.write("Upload an audio file, transcribe it into subtitles, and generate a video with subtitles.")

# Utility function to format timestamps for VTT
def format_vtt_timestamp(seconds):
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    sec = int(seconds % 60)
    millisec = int((seconds - int(seconds)) * 1000)
    return f"{hours:02}:{minutes:02}:{sec:02}.{millisec:03}"

# Simplify repetitive lyrics
def simplify_lyrics(text):
    pattern_oh = r'(Oh(\s+Oh)*)'
    pattern_la = r'(La(\s+La)*)'
    pattern_na = r'(Na(\s+Na)*)'

    if re.match(pattern_oh, text, re.IGNORECASE):
        return "Chorus: Oh (singing)"
    elif re.match(pattern_la, text, re.IGNORECASE):
        return "Chorus: La (singing)"
    elif re.match(pattern_na, text, re.IGNORECASE):
        return "Chorus: Na (singing)"

    text = re.sub(r'\s+', ' ', text.strip())
    return text

# Transcribe audio with Azure Whisper API
def transcribe_audio(file_path, api_key, api_url):
    with open(file_path, 'rb') as audio_file:
        headers = {'api-key': api_key}
        files = {'file': audio_file}
        response = requests.post(
            api_url, headers=headers, files=files,
            data={"response_format": "verbose_json", "temperature": 0.2, "language": "en"}
        )
        if response.status_code == 200:
            return response.json()
        else:
            st.error(f"Error: {response.status_code}, {response.text}")
            return None

# Generate a VTT subtitle file
def generate_vtt_file(transcript, output_vtt="transcription.vtt", max_duration_per_subtitle=10.0):
    if not transcript or "segments" not in transcript:
        st.error("Invalid transcript format or empty response.")
        return None

    segments = transcript["segments"]
    with open(output_vtt, "w", encoding="utf-8") as vtt_file:
        vtt_file.write("WEBVTT\n\n")
        for segment in segments:
            start = segment["start"]
            end = segment["end"]
            text = segment["text"].strip()

            if not text or len(text) < 1:
                continue

            simplified_text = simplify_lyrics(text)

            if (end - start) > max_duration_per_subtitle:
                chunk_duration = max_duration_per_subtitle
                current_start = start
                while current_start < end:
                    chunk_end = min(current_start + chunk_duration, end)
                    start_vtt = format_vtt_timestamp(current_start)
                    end_vtt = format_vtt_timestamp(chunk_end)
                    chunk_text = simplified_text if (chunk_end - current_start) <= max_duration_per_subtitle else f"{simplified_text} (cont.)"
                    vtt_file.write(f"{start_vtt} --> {end_vtt}\n{chunk_text}\n\n")
                    current_start += chunk_duration
            else:
                start_vtt = format_vtt_timestamp(start)
                end_vtt = format_vtt_timestamp(end)
                vtt_file.write(f"{start_vtt} --> {end_vtt}\n{simplified_text}\n\n")
    return output_vtt

# Convert VTT to ASS
def convert_vtt_to_ass(vtt_path, ass_path, resolution):
    width, height = (1920, 1080) if resolution == "Landscape" else (1080, 1920)

    ass_template = f"""[Script Info]
Title: Styled Subtitles
ScriptType: v4.00+
Collisions: Normal
PlayDepth: 0
PlayResX: {width}
PlayResY: {height}

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Nunito,72,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,3,2,2,20,20,100,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    def convert_time(vtt_time):
        h, m, s = vtt_time.split(":")
        s, ms = s.split(".")
        ms = ms[:2]
        return f"{h}:{m}:{s}.{ms}"

    with open(vtt_path, "r", encoding="utf-8") as vtt, open(ass_path, "w", encoding="utf-8") as ass:
        ass.write(ass_template)
        lines = vtt.readlines()

        for i in range(len(lines)):
            if "-->" in lines[i]:
                start, end = lines[i].strip().split(" --> ")
                start = convert_time(start)
                end = convert_time(end)
                text = lines[i + 1].strip() if i + 1 < len(lines) else ''

                effect = "{\\fad(500,500)}"
                if text:
                    ass.write(f"Dialogue: 0,{start},{end},Default,,0,0,0,,{effect}{text}\n")

    return ass_path

# Burn subtitles onto the video
def burn_subtitles(background_image, audio_file, output_video, resolution):
    width, height = (1920, 1080) if resolution == "Landscape" else (1080, 1920)
    ass_file = "subtitles.ass"
    convert_vtt_to_ass("transcription.vtt", ass_file, resolution)

    temp_bg_video = "temp_bg.mp4"
    temp_final_video = "temp_final.mp4"

    create_bg_command = [
        "ffmpeg", "-y",
        "-loop", "1",
        "-i", background_image,
        "-c:v", "libx264",
        "-t", "3:14",
        "-vf", f"scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2",
        "-pix_fmt", "yuv420p",
        temp_bg_video
    ]
    
    subprocess.run(create_bg_command, check=True)

    burn_subs_command = [
        "ffmpeg", "-y",
        "-i", temp_bg_video,
        "-vf", f"ass={ass_file}",
        "-c:v", "libx264",
        "-preset", "slow",
        "-crf", "18",
        temp_final_video
    ]
    
    subprocess.run(burn_subs_command, check=True)

    add_audio_command = [
        "ffmpeg", "-y",
        "-i", temp_final_video,
        "-i", audio_file,
        "-c:v", "copy",
        "-c:a", "aac",
        "-b:a", "192k",
        "-shortest",
        output_video
    ]

    subprocess.run(add_audio_command, check=True)
    return output_video

# User inputs
background_image = st.file_uploader("Upload Background Image", type=["jpg", "png"])
resolution = st.radio("Select Video Format", ["Landscape", "Portrait"])

if st.button("Generate Video"):
    video_path = "output.mp4"
    burn_subtitles(background_image, uploaded_file, video_path, resolution)
    with open(video_path, "rb") as video_file:
        st.download_button("Download Video", video_file, file_name="subtitled_video.mp4")
