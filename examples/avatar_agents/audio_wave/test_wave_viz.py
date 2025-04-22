import cv2
import numpy as np
import librosa
from wave_viz import WaveformVisualizer

def main():
    # Initialize visualizer
    visualizer = WaveformVisualizer()
    
    # Create a black canvas
    canvas = np.zeros((600, 800, 3), dtype=np.uint8)
    
    # Load audio file
    audio_path = "cxk.mp3"
    print("Loading audio file...")
    audio_data, sample_rate = librosa.load(audio_path, sr=None)
    print(f"Audio loaded: {len(audio_data)} samples, {sample_rate}Hz")
    
    # Setup video writer
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    out = cv2.VideoWriter('wave.mp4', fourcc, 30.0, (800, 600))
    
    # Process audio in chunks
    chunk_size = 1024
    total_chunks = len(audio_data) // chunk_size
    
    print("Processing audio visualization...")
    for i in range(0, len(audio_data), chunk_size):
        chunk = audio_data[i:i + chunk_size]
        
        # Clear canvas
        canvas.fill(0)
        
        # Draw visualization
        visualizer.draw(canvas, chunk)
        
        # Write frame to video
        out.write(canvas)
        
        # Print progress
        if i % (chunk_size * 100) == 0:
            progress = (i // chunk_size) / total_chunks * 100
            print(f"Processing: {progress:.1f}%")
    
    # Release video writer
    out.release()
    print("Video saved as wave.mp4")

if __name__ == "__main__":
    main() 