const fs = require('fs');
const ffmpeg = require('fluent-ffmpeg');
const path = require('path');

// Get arguments for frame size and zoom type
const frameWidth = parseInt(process.argv[2]);
const frameHeight = parseInt(process.argv[3]);
const zoomType = process.argv[4];

const audioFolder = path.join(__dirname, 'segments');
const mediaFolder = path.join(__dirname, 'vids');
const outputFolder = path.join(__dirname, 'output-videos');
const videoSegmentsFolder = path.join(__dirname, 'vid-segments');

const targetFrameRate = 60;
const videoBitrate = '3000k';  // Increased bitrate for better quality
const crfValue = 20;           // Lower CRF for higher quality

// Ensure folders exist
if (!fs.existsSync(outputFolder)) fs.mkdirSync(outputFolder);
if (!fs.existsSync(videoSegmentsFolder)) fs.mkdirSync(videoSegmentsFolder);

// Map media files by segment ID
const mediaFiles = fs.readdirSync(mediaFolder)
    .reduce((acc, file) => {
        const match = file.match(/segment_(\d+)_media\..+/);
        if (match) {
            const segmentId = parseInt(match[1], 10);
            acc[segmentId] = path.join(mediaFolder, file);
        }
        return acc;
    }, {});

// Logging FFmpeg errors and providing detailed error logs
function logFfmpegError(error, stage) {
    console.error(`Error during ${stage}: ${error.message}`);
    if (error.stderr) {
        console.error(`FFmpeg error output: ${error.stderr}`);
    }
}

// Get the duration of the audio segment
function getAudioSegmentDuration(segmentPath) {
    return new Promise((resolve, reject) => {
        ffmpeg.ffprobe(segmentPath, (err, metadata) => {
            if (err) {
                return reject(`Error fetching audio segment duration: ${err.message}`);
            }
            resolve(metadata.format.duration);
        });
    });
}

// Calculate cropping filter to fit video within frame size
function getCropFilter(inputWidth, inputHeight, targetWidth, targetHeight) {
    const inputAspectRatio = inputWidth / inputHeight;
    const targetAspectRatio = targetWidth / targetHeight;

    if (inputAspectRatio > targetAspectRatio) {
        // Input is wider than the target, crop horizontally
        const cropWidth = Math.round(targetAspectRatio * inputHeight);
        const xOffset = Math.round((inputWidth - cropWidth) / 2);
        return `crop=${cropWidth}:${inputHeight}:${xOffset}:0`;
    } else {
        // Input is taller than the target, crop vertically
        const cropHeight = Math.round(inputWidth / targetAspectRatio);
        const yOffset = Math.round((inputHeight - cropHeight) / 2);
        return `crop=${inputWidth}:${cropHeight}:0:${yOffset}`;
    }
}

// Apply zoom effect (zoom in/zoom out/no effect)
function applyZoomEffect(inputFile, zoomType, outputFile, duration, frameSize) {
    return new Promise((resolve, reject) => {
        ffmpeg.ffprobe(inputFile, (err, metadata) => {
            if (err) return reject(`Error retrieving metadata: ${err.message}`);

            const inputWidth = metadata.streams[0].width;
            const inputHeight = metadata.streams[0].height;
            const cropFilter = getCropFilter(inputWidth, inputHeight, frameSize[0], frameSize[1]);

            let videoFilter = cropFilter; // Apply cropping filter first

            if (zoomType === 'zoom_in') {
                videoFilter += `,zoompan=z='min(zoom+0.0015,2)':d=1:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'`;
            } else if (zoomType === 'zoom_out') {
                videoFilter += `,zoompan=z='max(zoom-0.0015,1)':d=1:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'`;
            }

            ffmpeg(inputFile)
                .videoFilter(videoFilter)
                .outputOptions([
                    `-t ${duration}`,
                    `-r ${targetFrameRate}`,
                    `-b:v ${videoBitrate}`,  // Set the video bitrate for better quality
                    `-crf ${crfValue}`,      // Lower CRF value for better quality
                    '-preset slow',          // Slower preset for better quality
                    '-pix_fmt yuv420p',
                    '-vcodec libx264'
                ])
                .on('end', () => resolve(outputFile))
                .on('error', (err, stdout, stderr) => {
                    logFfmpegError({ message: err.message, stderr }, 'Zoom Effect');
                    reject(err);
                })
                .save(outputFile);
        });
    });
}

// Process GIF to handle looping, cropping, and scaling
function processGif(inputFile, duration, frameSize, outputFile) {
    return new Promise((resolve, reject) => {
        ffmpeg.ffprobe(inputFile, (err, metadata) => {
            if (err) {
                logFfmpegError({ message: err.message }, 'FFprobe for GIF Duration');
                return reject(err);
            }

            const inputWidth = metadata.streams[0].width;
            const inputHeight = metadata.streams[0].height;
            const cropFilter = getCropFilter(inputWidth, inputHeight, frameSize[0], frameSize[1]);

            ffmpeg(inputFile)
                .inputOptions('-ignore_loop 0')
                .outputOptions([
                    `-t ${duration}`,
                    `-vf ${cropFilter},scale=${frameSize[0]}:${frameSize[1]}`,
                    `-b:v ${videoBitrate}`,  // Set video bitrate for better quality
                    `-crf ${crfValue}`,      // Lower CRF value for better quality
                    '-preset slow',          // Higher quality preset
                    `-r ${targetFrameRate}`,
                    '-pix_fmt yuv420p',
                    '-vcodec libx264'
                ])
                .on('end', () => resolve(outputFile))
                .on('error', (err, stdout, stderr) => {
                    logFfmpegError({ message: err.message, stderr }, 'GIF Processing');
                    reject(err);
                })
                .save(outputFile);
        });
    });
}

// Concatenate video clips
function concatenateClips(videoClips, outputPath) {
    const concatListFile = path.join(outputFolder, 'concat_list.txt');
    fs.writeFileSync(concatListFile, videoClips.map(clip => `file '${clip}'`).join('\n'));

    return new Promise((resolve, reject) => {
        ffmpeg()
            .input(concatListFile)
            .inputOptions(['-f', 'concat', '-safe', '0'])
            .outputOptions([
                `-c:v libx264`,
                `-b:v ${videoBitrate}`,  // Apply bitrate for final video
                `-crf ${crfValue}`,      // CRF value for better quality
                '-preset slow',          // Higher quality preset
                `-pix_fmt yuv420p`,
                `-r ${targetFrameRate}`,
                `-c:a aac`,
                '-strict -2'
            ])
            .on('end', resolve)
            .on('error', (err, stdout, stderr) => {
                logFfmpegError({ message: err.message, stderr }, 'Concatenation');
                reject(err);
            })
            .save(outputPath);
    });
}

// Overlay the combined audio on the final video
function overlayAudioOnVideo(finalVideoPath, audioPath, outputPath) {
    return new Promise((resolve, reject) => {
        ffmpeg()
            .input(finalVideoPath)
            .input(audioPath)
            .outputOptions([
                '-c:v copy',
                '-c:a aac',
                `-b:a 192k`,  // Improve audio bitrate for better sound quality
                '-strict -2'
            ])
            .on('end', resolve)
            .on('error', (err, stdout, stderr) => {
                logFfmpegError({ message: err.message, stderr }, 'Audio Overlay');
                reject(err);
            })
            .save(outputPath);
    });
}

// Main function to process video clips
async function processVideoClips() {
    let videoClips = [];
    const startTime = Date.now();
    console.log('Processing video clips...');

    for (let segmentId in mediaFiles) {
        const outputFile = path.join(videoSegmentsFolder, `clip_${segmentId}.mp4`);
        const inputFile = mediaFiles[segmentId];
        const audioSegment = path.join(audioFolder, `segment_${segmentId}.mp3`);
        let duration;

        try {
            duration = await getAudioSegmentDuration(audioSegment);
            console.log(`Processing segment ${segmentId}, duration: ${duration} seconds`);
        } catch (err) {
            console.error(`Error retrieving duration for audio segment ${segmentId}: ${err}`);
            continue;
        }

        try {
            const ext = path.extname(inputFile).toLowerCase();
            if (ext === '.gif') {
                await processGif(inputFile, duration, [frameWidth, frameHeight], outputFile);
            } else if (ext === '.mp4') {
                await applyZoomEffect(inputFile, zoomType, outputFile, duration, [frameWidth, frameHeight]);
            }

            videoClips.push(outputFile);
            console.log(`Processed segment ${segmentId}`);
        } catch (err) {
            console.error(`Error processing segment ${segmentId}: ${err.message}`);
        }
    }

    try {
        const finalVideoPath = path.join(outputFolder, 'final_output.mp4');
        console.log('Concatenating all video clips...');
        await concatenateClips(videoClips, finalVideoPath);

        // Concatenate audio segments
        const audioSegments = fs.readdirSync(audioFolder)
            .filter(file => file.match(/segment_(\d+)\.mp3/))
            .sort((a, b) => {
                const segmentA = parseInt(a.match(/segment_(\d+)\.mp3/)[1], 10);
                const segmentB = parseInt(b.match(/segment_(\d+)\.mp3/)[1], 10);
                return segmentA - segmentB;
            })
            .map(file => path.join(audioFolder, file));

        const combinedAudioPath = path.join(outputFolder, 'combined_audio.mp3');

        await new Promise((resolve, reject) => {
            const concatListFile = path.join(outputFolder, 'audio_concat_list.txt');
            fs.writeFileSync(concatListFile, audioSegments.map(file => `file '${file}'`).join('\n'));

            ffmpeg()
                .input(concatListFile)
                .inputOptions(['-f', 'concat', '-safe', '0'])
                .outputOptions(['-c', 'copy'])
                .on('end', resolve)
                .on('error', (err, stdout, stderr) => {
                    logFfmpegError({ message: err.message, stderr }, 'Audio Concatenation');
                    reject(err);
                })
                .save(combinedAudioPath);
        });

        const finalOutputWithAudio = path.join(outputFolder, 'final_with_audio_output.mp4');
        console.log('Overlaying audio on the final video...');
        await overlayAudioOnVideo(finalVideoPath, combinedAudioPath, finalOutputWithAudio);

        const endTime = Date.now();
        const timeTaken = ((endTime - startTime) / 1000).toFixed(2);
        console.log(`Video processing completed in ${timeTaken} seconds`);
        console.log(`Final video with audio: ${finalOutputWithAudio}`);
    } catch (err) {
        console.error(`Error creating final video: ${err}`);
    }
}

processVideoClips().catch(err => console.error(`Error processing videos: ${err.message}`));
