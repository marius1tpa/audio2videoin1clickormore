import os
import subprocess
from flask import Flask, render_template, request, jsonify, send_from_directory, send_file, after_this_request
from pydub import AudioSegment
from pydub.silence import detect_silence
import shutil

app = Flask(__name__)

# Directory setup under web-media root
MEDIA_ROOT = 'web-media'
UPLOAD_FOLDER = os.path.join(MEDIA_ROOT, 'uploads')
SEGMENTS_FOLDER = os.path.join(MEDIA_ROOT, 'segments')
VIDS_FOLDER = os.path.join(MEDIA_ROOT, 'vids')
OUTPUT_VIDEOS_FOLDER = os.path.join(MEDIA_ROOT, 'output-videos')

# Create directories if they don't exist
def create_directories():
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    os.makedirs(SEGMENTS_FOLDER, exist_ok=True)
    os.makedirs(VIDS_FOLDER, exist_ok=True)
    os.makedirs(OUTPUT_VIDEOS_FOLDER, exist_ok=True)

create_directories()

media_files_by_segment = {}

# Allowed media types (GIF, PNG, JPG, MP4, etc.)
ALLOWED_EXTENSIONS = {'gif', 'png', 'jpg', 'jpeg', 'mp4'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/segments/<filename>')
def serve_audio(filename):
    return send_from_directory(SEGMENTS_FOLDER, filename)

@app.route('/output-videos/<filename>')
def serve_video(filename):
    return send_from_directory(OUTPUT_VIDEOS_FOLDER, filename)

@app.route('/upload_audio', methods=['POST'])
def upload_audio():
    if 'audio_file' not in request.files:
        return jsonify({'error': 'No audio file uploaded'}), 400

    file = request.files['audio_file']
    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400

    file_path = os.path.join(UPLOAD_FOLDER, file.filename)
    file.save(file_path)

    audio = AudioSegment.from_file(file_path)
    silence_thresh = request.form.get('silence_thresh', -50, type=int)
    min_silence_len = request.form.get('min_silence_len', 300, type=int)
    max_silence_len = request.form.get('max_silence_len', 500, type=int)  # Maximum silence length

    silence_spots = detect_silence(audio, min_silence_len=min_silence_len, silence_thresh=silence_thresh)

    segments = []
    start_point = 0
    segment_index = 1
    total_trimmed_duration = 0

    for silence_start, silence_end in silence_spots:
        silence_duration = silence_end - silence_start

        if silence_duration > max_silence_len:
            silence_end = silence_start + max_silence_len

        if start_point < silence_start:
            segment = audio[start_point:silence_start].strip_silence(silence_thresh=silence_thresh)

            if len(segment) > 0:
                segment_filename = f'segment_{segment_index}.mp3'
                segment_path = os.path.join(SEGMENTS_FOLDER, segment_filename)
                segment.export(segment_path, format="mp3")

                total_trimmed_duration += len(segment)

                segments.append({
                    'index': segment_index,
                    'start': total_trimmed_duration - len(segment),
                    'end': total_trimmed_duration,
                    'filename': segment_filename,
                    'filepath': f'/segments/{segment_filename}'
                })
                segment_index += 1

        start_point = silence_end

    if start_point < len(audio):
        segment = audio[start_point:].strip_silence(silence_thresh=silence_thresh)
        if len(segment) > 0:
            segment_filename = f'segment_{segment_index}.mp3'
            segment_path = os.path.join(SEGMENTS_FOLDER, segment_filename)
            segment.export(segment_path, format="mp3")

            total_trimmed_duration += len(segment)

            segments.append({
                'index': segment_index,
                'start': total_trimmed_duration - len(segment),
                'end': total_trimmed_duration,
                'filename': segment_filename,
                'filepath': f'/segments/{segment_filename}'
            })

    # Store segment count for future media uploads
    media_files_by_segment['segment_count'] = len(segments)

    return jsonify({'segments': segments, 'trimmed_duration': total_trimmed_duration})

@app.route('/upload_bulk_media', methods=['POST'])
def upload_bulk_media():
    media_files = request.files.getlist('media_files')  # Multiple files
    segment_count = media_files_by_segment.get('segment_count', 0)

    if not media_files:
        return jsonify({'error': 'No media files uploaded'}), 400

    if segment_count == 0:
        return jsonify({'error': 'No segments found, upload audio first'}), 400

    # Initialize counter for uploaded files
    uploaded_files_count = 0

    # Iterate over media files and assign to segments
    for index, media_file in enumerate(media_files):
        if uploaded_files_count >= segment_count:
            break

        if media_file and allowed_file(media_file.filename):
            ext = media_file.filename.split('.')[-1]
            filename = f'segment_{uploaded_files_count + 1}_media.{ext}'
            file_path = os.path.join(VIDS_FOLDER, filename)
            media_file.save(file_path)

            media_files_by_segment[str(uploaded_files_count + 1)] = file_path
            uploaded_files_count += 1

    # Check if more files are needed
    files_needed = segment_count - uploaded_files_count

    return jsonify({
        'message': f'{uploaded_files_count} media files uploaded successfully.',
        'total_files_used': uploaded_files_count,
        'files_needed': max(0, files_needed)
    })

@app.route('/create_video', methods=['POST'])
def create_video():
    data = request.json
    frame_width = int(data['frame_width'])
    frame_height = int(data['frame_height'])
    zoom_type = data['zoom_type']

    segment_count = media_files_by_segment.get('segment_count', 0)

    if segment_count == 0:
        return jsonify({'error': 'No segments or media files uploaded'}), 400

    node_process = subprocess.run(['node', 'video.js', str(frame_width), str(frame_height), zoom_type], capture_output=True, text=True)

    if node_process.returncode != 0:
        return jsonify({'error': 'Video creation failed', 'details': node_process.stderr}), 500

    final_video_with_audio_filename = 'final_with_audio_output.mp4'
    final_video_with_audio_path = os.path.join(OUTPUT_VIDEOS_FOLDER, final_video_with_audio_filename)

    return jsonify({'video_url': f'/output-videos/{final_video_with_audio_filename}'})

def clear_all_folders():
    """Clears all files and subdirectories from the media folders."""
    def clear_directory(folder_path):
        for filename in os.listdir(folder_path):
            file_path = os.path.join(folder_path, filename)
            try:
                if os.path.isfile(file_path) or os.path.islink(file_path):
                    os.remove(file_path)
                elif os.path.isdir(file_path):
                    shutil.rmtree(file_path)
            except Exception as e:
                print(f"Error deleting {file_path}: {e}")
    
    # Clear contents of the directories
    clear_directory(UPLOAD_FOLDER)
    clear_directory(SEGMENTS_FOLDER)
    clear_directory(VIDS_FOLDER)
    clear_directory(OUTPUT_VIDEOS_FOLDER)

@app.route('/download_video', methods=['GET'])
def download_video():
    final_video_with_audio_path = os.path.join(OUTPUT_VIDEOS_FOLDER, 'final_with_audio_output.mp4')

    if not os.path.exists(final_video_with_audio_path):
        return jsonify({'error': 'Video not found'}), 404

    @after_this_request
    def cleanup(response):
        # Cleanup all folders after the response is sent
        clear_all_folders()
        return response

    # Serve the file for download
    return send_file(final_video_with_audio_path, as_attachment=True)

if __name__ == '__main__':
    app.run(debug=True)
