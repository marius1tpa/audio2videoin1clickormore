import os
import subprocess
from flask import Flask, render_template, request, jsonify, send_from_directory, send_file, after_this_request
from pydub import AudioSegment
from pydub.silence import detect_silence
import shutil

app = Flask(__name__)

# Directory setup
UPLOAD_FOLDER = 'uploads'
SEGMENTS_FOLDER = 'segments'
VIDS_FOLDER = 'vids'
OUTPUT_VIDEOS_FOLDER = 'output-videos'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(SEGMENTS_FOLDER, exist_ok=True)
os.makedirs(VIDS_FOLDER, exist_ok=True)
os.makedirs(OUTPUT_VIDEOS_FOLDER, exist_ok=True)

media_files_by_segment = {}

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

    return jsonify({'segments': segments, 'trimmed_duration': total_trimmed_duration})

@app.route('/upload_media', methods=['POST'])
def upload_media():
    segment_id = request.form.get('segment_id')
    media_file = request.files.get('media_file')

    if not segment_id or not media_file:
        return jsonify({'error': 'Missing segment ID or media file'}), 400

    ext = media_file.filename.split('.')[-1]
    filename = f'segment_{segment_id}_media.{ext}'
    file_path = os.path.join(VIDS_FOLDER, filename)  
    media_file.save(file_path)

    media_files_by_segment[segment_id] = file_path
    return jsonify({'message': 'Media uploaded successfully', 'file_path': file_path})

@app.route('/create_video', methods=['POST'])
def create_video():
    data = request.json
    frame_width = int(data['frame_width'])
    frame_height = int(data['frame_height'])
    zoom_type = data['zoom_type']

    if len(media_files_by_segment) == 0:
        return jsonify({'error': 'No media files uploaded'}), 400

    node_process = subprocess.run(['node', 'video.js', str(frame_width), str(frame_height), zoom_type], capture_output=True, text=True)

    if node_process.returncode != 0:
        return jsonify({'error': 'Video creation failed', 'details': node_process.stderr}), 500

    final_video_with_audio_filename = 'final_with_audio_output.mp4'
    final_video_with_audio_path = os.path.join(OUTPUT_VIDEOS_FOLDER, final_video_with_audio_filename)
   
    return jsonify({'video_url': f'/output-videos/{final_video_with_audio_filename}'})

@app.route('/download_video', methods=['GET'])
def download_video():
    final_video_with_audio_path = os.path.join(OUTPUT_VIDEOS_FOLDER, 'final_with_audio_output.mp4')
    
    if not os.path.exists(final_video_with_audio_path):
        return jsonify({'error': 'Video not found'}), 404

    @after_this_request
    def cleanup(response):
        try:
            shutil.rmtree(UPLOAD_FOLDER)
            shutil.rmtree(SEGMENTS_FOLDER)
            shutil.rmtree(VIDS_FOLDER)
            shutil.rmtree(OUTPUT_VIDEOS_FOLDER)
            os.makedirs(UPLOAD_FOLDER, exist_ok=True)
            os.makedirs(SEGMENTS_FOLDER, exist_ok=True)
            os.makedirs(VIDS_FOLDER, exist_ok=True)
            os.makedirs(OUTPUT_VIDEOS_FOLDER, exist_ok=True)
        except Exception as e:
            print(f"Error cleaning up: {e}")
        return response

    return send_file(final_video_with_audio_path, as_attachment=True)

if __name__ == '__main__':
    app.run(debug=True)
