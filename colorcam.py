#!/usr/bin/env python3
"""
ColorCam GUI - Well Plate Color Measurement with Camera Preview
Integrates Pi Camera, RoboCam printer control, and well position loading.

Features:
- Live camera preview
- Load well positions from JSON (from well_plate_location_gui.py) or CSV
- Automated well-by-well capture with RGB analysis
- Real-time results display
- Save results to file

Author: Rewritten with GUI
Date: 2025
"""

import FreeSimpleGUI as sg
import time
import json
import csv
import threading
from datetime import datetime
from PIL import Image
import io

import numpy as np
import matplotlib.pyplot as plt

from picamera2 import Picamera2
from picamera2.encoders import JpegEncoder

# Try to import robocam modules
try:
    from robocam.robocam_ccc import RoboCam
    from robocam.laser import Laser
    ROBOCAM_AVAILABLE = True
except ImportError as e:
    print(f"Warning: robocam modules not available: {e}")
    print("Printer control will be disabled.")
    ROBOCAM_AVAILABLE = False
    RoboCam = None
    Laser = None

# ===== Configuration =====
DEFAULT_SIZE = (640, 480)
DEFAULT_CENTER = (DEFAULT_SIZE[0]/2, DEFAULT_SIZE[1]/2)
DEFAULT_RADIUS = 100
DEFAULT_Z = 2.0
DEFAULT_SETTLE_TIME = 1.0

# ===== Global variables =====
picam2 = None
robocam = None
laser = None
camera_running = False
capture_thread = None
stop_capture = False
well_positions = []
snake_path = []
results = []

# ===== Camera Functions =====

def init_camera():
    """Initialize Pi Camera."""
    global picam2
    try:
        picam2 = Picamera2()
        still_config = picam2.create_video_configuration(
            main={'size': DEFAULT_SIZE, 'format': 'BGR888'}
        )
        picam2.configure(still_config)
        picam2.start()
        return True
    except Exception as e:
        print(f"Error initializing camera: {e}")
        return False

def get_camera_frame():
    """Capture a single frame from camera and convert to PIL Image."""
    global picam2
    if picam2 is None:
        return None
    try:
        # Capture array
        array = picam2.capture_array()
        # Convert BGR to RGB
        rgb_array = array[:, :, ::-1]
        # Convert to PIL Image
        img = Image.fromarray(rgb_array)
        return img
    except Exception as e:
        print(f"Error capturing frame: {e}")
        return None

def create_mask(size, center, radius):
    """Create circular mask for RGB averaging."""
    y, x = np.ogrid[:size[1], :size[0]]
    cendist = np.sqrt((x - center[0])**2 + (y - center[1])**2)
    mask = cendist <= radius
    return mask

# ===== Printer Functions =====

def init_printer(baudrate=250000):
    """Initialize RoboCam printer connection."""
    global robocam, laser
    if not ROBOCAM_AVAILABLE:
        return False
    try:
        robocam = RoboCam(baudrate=baudrate)
        laser = Laser(21)
        return True
    except Exception as e:
        print(f"Error initializing printer: {e}")
        return False

def home_printer():
    """Home the printer."""
    global robocam
    if robocam is None:
        return False
    try:
        robocam.home()
        return True
    except Exception as e:
        print(f"Error homing printer: {e}")
        return False

def move_to_well(x, y, z):
    """Move printer to well position."""
    global robocam
    if robocam is None:
        return False
    try:
        robocam.move_absolute(x, y, z)
        return True
    except Exception as e:
        print(f"Error moving printer: {e}")
        return False

# ===== Well Position Loading =====

def load_well_positions_json(json_file):
    """Load well positions from JSON file (from well_plate_location_gui.py)."""
    try:
        with open(json_file, 'r') as f:
            config = json.load(f)
        
        # Extract well positions and snake path
        positions = config.get('well_positions', {})
        path = config.get('snake_path', [])
        
        # Convert to list of tuples: [(well_name, x, y, z), ...]
        well_list = []
        for well_name in path if path else sorted(positions.keys()):
            if well_name in positions:
                pos = positions[well_name]
                well_list.append((
                    well_name,
                    pos.get('X', 0),
                    pos.get('Y', 0),
                    pos.get('Z', 0)
                ))
        
        return well_list, path
    except Exception as e:
        print(f"Error loading JSON: {e}")
        return None, None

def load_well_positions_csv(csv_file):
    """Load well positions from CSV file.
    Expected format: well_name,x,y,z (header optional)
    """
    try:
        well_list = []
        with open(csv_file, 'r') as f:
            reader = csv.reader(f)
            # Skip header if it exists
            first_row = next(reader, None)
            if first_row and not first_row[0].replace('.', '').replace('-', '').isdigit():
                # Likely a header, continue
                pass
            else:
                # First row is data, process it
                if first_row:
                    try:
                        well_name = first_row[0] if len(first_row) > 0 else "Unknown"
                        x = float(first_row[1]) if len(first_row) > 1 else 0
                        y = float(first_row[2]) if len(first_row) > 2 else 0
                        z = float(first_row[3]) if len(first_row) > 3 else DEFAULT_Z
                        well_list.append((well_name, x, y, z))
                    except (ValueError, IndexError):
                        pass
            
            # Process remaining rows
            for row in reader:
                if len(row) >= 4:
                    try:
                        well_name = row[0]
                        x = float(row[1])
                        y = float(row[2])
                        z = float(row[3])
                        well_list.append((well_name, x, y, z))
                    except ValueError:
                        continue
        
        # Generate snake path from well list order
        path = [well[0] for well in well_list]
        return well_list, path
    except Exception as e:
        print(f"Error loading CSV: {e}")
        return None, None

# ===== Capture Functions =====

def capture_well_rgb(well_name, x, y, z, settle_time, mask, window=None):
    """Capture image at well position and calculate RGB averages."""
    global picam2, robocam, laser
    
    # Move to position
    if robocam is not None:
        if not move_to_well(x, y, z):
            return None
        time.sleep(settle_time)
    
    # Capture image
    if picam2 is None:
        return None
    
    try:
        # Capture array
        iarray = picam2.capture_array()
        
        # Calculate RGB averages within mask
        redavg = np.average(iarray[:, :, 2][mask])  # BGR format: index 2 is red
        greenavg = np.average(iarray[:, :, 1][mask])
        blueavg = np.average(iarray[:, :, 0][mask])
        
        return {
            'well': well_name,
            'x': x,
            'y': y,
            'z': z,
            'red': round(redavg),
            'green': round(greenavg),
            'blue': round(blueavg),
            'timestamp': datetime.now().isoformat()
        }
    except Exception as e:
        print(f"Error capturing RGB for {well_name}: {e}")
        return None

def capture_all_wells(well_list, z_height, settle_time, mask, window, progress_key, status_key, results_key):
    """Capture RGB for all wells in sequence."""
    global stop_capture, results
    
    results = []
    total = len(well_list)
    
    for idx, (well_name, x, y, z) in enumerate(well_list):
        if stop_capture:
            window[status_key].update("Capture stopped by user")
            break
        
        # Use provided Z or override with user input
        current_z = z if z > 0 else z_height
        
        window[status_key].update(f"Capturing {well_name} ({idx+1}/{total})...")
        window[progress_key].update(f"{idx+1}/{total}")
        window.refresh()
        
        result = capture_well_rgb(well_name, x, y, current_z, settle_time, mask, window)
        
        if result:
            results.append(result)
            # Update results display
            results_text = "Results:\n" + "="*50 + "\n"
            for r in results:
                results_text += f"{r['well']}: R={r['red']}, G={r['green']}, B={r['blue']}\n"
            window[results_key].update(results_text)
            window.refresh()
        
        time.sleep(0.5)  # Small delay between wells
    
    window[status_key].update("Capture complete!" if not stop_capture else "Capture stopped")
    window[progress_key].update(f"{len(results)}/{total}")

def capture_thread_func(well_list, z_height, settle_time, mask, window, progress_key, status_key, results_key):
    """Thread function for capturing wells."""
    try:
        capture_all_wells(well_list, z_height, settle_time, mask, window, progress_key, status_key, results_key)
    except Exception as e:
        window[status_key].update(f"Error: {str(e)}")
        print(f"Capture thread error: {e}")

# ===== Camera Preview Thread =====

def camera_preview_thread(window, preview_key):
    """Continuously update camera preview."""
    global camera_running, picam2
    
    while camera_running:
        if picam2 is None:
            time.sleep(0.1)
            continue
        
        try:
            img = get_camera_frame()
            if img is not None:
                # Resize for preview (optional, can adjust)
                img.thumbnail((640, 480), Image.Resampling.LANCZOS)
                
                # Convert to bytes for FreeSimpleGUI
                bio = io.BytesIO()
                img.save(bio, format='PNG')
                img_bytes = bio.getvalue()
                
                window[preview_key].update(data=img_bytes)
        except Exception as e:
            print(f"Preview update error: {e}")
        
        time.sleep(0.033)  # ~30 FPS

# ===== GUI Layout =====

def create_gui_layout():
    """Create the GUI layout."""
    layout = [
        [sg.Text("ColorCam - Well Plate RGB Measurement", font=("Helvetica", 16, "bold"))],
        [sg.HSeparator()],
        
        # Left column: Controls
        [
            sg.Column([
                [sg.Text("Camera Preview", font=("Helvetica", 12, "bold"))],
                [sg.Image(key="-PREVIEW-", size=(640, 480))],
                
                [sg.HSeparator()],
                
                [sg.Text("Well Position File", font=("Helvetica", 12, "bold"))],
                [
                    sg.Input(key="-WELL_FILE-", size=(40, 1), enable_events=True),
                    sg.FileBrowse("Browse", file_types=(("JSON/CSV", "*.json *.csv"), ("JSON", "*.json"), ("CSV", "*.csv")))
                ],
                [sg.Button("Load Well Positions", key="-LOAD_WELLS-")],
                [sg.Text("Wells loaded: 0", key="-WELL_COUNT-")],
                
                [sg.HSeparator()],
                
                [sg.Text("Printer Settings", font=("Helvetica", 12, "bold"))],
                [sg.Text("Z Height:"), sg.Input(str(DEFAULT_Z), key="-Z_HEIGHT-", size=(10, 1))],
                [sg.Text("Settle Time (s):"), sg.Input(str(DEFAULT_SETTLE_TIME), key="-SETTLE_TIME-", size=(10, 1))],
                [sg.Button("Home Printer", key="-HOME-"), sg.Button("Connect Printer", key="-CONNECT-")],
                
                [sg.HSeparator()],
                
                [sg.Text("Capture Settings", font=("Helvetica", 12, "bold"))],
                [sg.Text("Mask Center X:"), sg.Input(str(int(DEFAULT_CENTER[0])), key="-CENTER_X-", size=(10, 1))],
                [sg.Text("Mask Center Y:"), sg.Input(str(int(DEFAULT_CENTER[1])), key="-CENTER_Y-", size=(10, 1))],
                [sg.Text("Mask Radius:"), sg.Input(str(int(DEFAULT_RADIUS)), key="-RADIUS-", size=(10, 1))],
                
                [sg.HSeparator()],
                
                [sg.Button("Start Capture", key="-START-", button_color=("white", "green"), size=(15, 2)),
                 sg.Button("Stop Capture", key="-STOP-", button_color=("white", "red"), size=(15, 2), disabled=True)],
                [sg.Text("Status: Ready", key="-STATUS-")],
                [sg.Text("Progress: 0/0", key="-PROGRESS-")],
                
                [sg.HSeparator()],
                
                [sg.Text("Results", font=("Helvetica", 12, "bold"))],
                [sg.Multiline(key="-RESULTS-", size=(None, 10), autoscroll=True, disabled=True)],
                [sg.Button("Save Results", key="-SAVE_RESULTS-"), sg.Button("Plot Results", key="-PLOT-")],
            ], vertical_alignment='top'),
            
            # Right column: Results table (optional, can be expanded)
            sg.Column([
                [sg.Text("Well Information", font=("Helvetica", 12, "bold"))],
                [sg.Multiline(key="-WELL_INFO-", size=(None, 20), disabled=True)],
            ], vertical_alignment='top')
        ],
    ]
    
    return layout

# ===== Main GUI =====

def main():
    global picam2, robocam, laser, camera_running, capture_thread, stop_capture, well_positions, snake_path, results
    
    sg.theme("LightGreen")
    
    # Initialize camera
    if not init_camera():
        sg.popup_error("Failed to initialize camera. Exiting.", title="Error")
        return
    
    # Create GUI
    window = sg.Window("ColorCam - Well Plate RGB Measurement", create_gui_layout(), resizable=True, finalize=True)
    
    # Start camera preview thread
    camera_running = True
    preview_thread = threading.Thread(target=camera_preview_thread, args=(window, "-PREVIEW-"), daemon=True)
    preview_thread.start()
    
    printer_connected = False
    
    # Main event loop
    while True:
        event, values = window.read(timeout=100)
        
        if event == sg.WIN_CLOSED:
            break
        
        # Load well positions
        elif event == "-LOAD_WELLS-":
            file_path = values["-WELL_FILE-"]
            if not file_path:
                sg.popup_error("Please select a file first.", title="Error")
                continue
            
            try:
                if file_path.endswith('.json'):
                    well_list, path = load_well_positions_json(file_path)
                elif file_path.endswith('.csv'):
                    well_list, path = load_well_positions_csv(file_path)
                else:
                    sg.popup_error("Unsupported file format. Please use JSON or CSV.", title="Error")
                    continue
                
                if well_list:
                    well_positions = well_list
                    snake_path = path if path else [w[0] for w in well_list]
                    window["-WELL_COUNT-"].update(f"Wells loaded: {len(well_positions)}")
                    
                    # Display well info
                    info_text = f"Loaded {len(well_positions)} wells:\n\n"
                    for well_name, x, y, z in well_positions[:10]:  # Show first 10
                        info_text += f"{well_name}: X={x:.2f}, Y={y:.2f}, Z={z:.2f}\n"
                    if len(well_positions) > 10:
                        info_text += f"... and {len(well_positions) - 10} more\n"
                    window["-WELL_INFO-"].update(info_text)
                    
                    sg.popup(f"Successfully loaded {len(well_positions)} well positions!", title="Success")
                else:
                    sg.popup_error("Failed to load well positions. Check file format.", title="Error")
            except Exception as e:
                sg.popup_error(f"Error loading file:\n{str(e)}", title="Error")
        
        # Connect printer
        elif event == "-CONNECT-":
            if ROBOCAM_AVAILABLE:
                if init_printer():
                    printer_connected = True
                    window["-STATUS-"].update("Status: Printer connected")
                    sg.popup("Printer connected successfully!", title="Success")
                else:
                    sg.popup_error("Failed to connect to printer.", title="Error")
            else:
                sg.popup_error("RoboCam modules not available.", title="Error")
        
        # Home printer
        elif event == "-HOME-":
            if printer_connected and robocam is not None:
                window["-STATUS-"].update("Status: Homing printer...")
                window.refresh()
                if home_printer():
                    sg.popup("Printer homed successfully!", title="Success")
                    window["-STATUS-"].update("Status: Ready")
                else:
                    sg.popup_error("Failed to home printer.", title="Error")
            else:
                sg.popup_error("Please connect printer first.", title="Error")
        
        # Start capture
        elif event == "-START-":
            if not well_positions:
                sg.popup_error("Please load well positions first.", title="Error")
                continue
            
            try:
                z_height = float(values["-Z_HEIGHT-"])
                settle_time = float(values["-SETTLE_TIME-"])
                center_x = float(values["-CENTER_X-"])
                center_y = float(values["-CENTER_Y-"])
                radius = float(values["-RADIUS-"])
            except ValueError:
                sg.popup_error("Please enter valid numbers for settings.", title="Error")
                continue
            
            # Create mask
            mask = create_mask(DEFAULT_SIZE, (center_x, center_y), radius)
            
            # Disable start, enable stop
            window["-START-"].update(disabled=True)
            window["-STOP-"].update(disabled=False)
            stop_capture = False
            
            # Start capture thread
            capture_thread = threading.Thread(
                target=capture_thread_func,
                args=(
                    well_positions,
                    z_height,
                    settle_time,
                    mask,
                    window,
                    "-PROGRESS-",
                    "-STATUS-",
                    "-RESULTS-"
                ),
                daemon=True
            )
            capture_thread.start()
        
        # Stop capture
        elif event == "-STOP-":
            stop_capture = True
            window["-START-"].update(disabled=False)
            window["-STOP-"].update(disabled=True)
            window["-STATUS-"].update("Status: Stopping...")
        
        # Save results
        elif event == "-SAVE_RESULTS-":
            if not results:
                sg.popup_error("No results to save.", title="Error")
                continue
            
            filename = sg.popup_get_file("Save results as", save_as=True, default_extension=".json",
                                        file_types=(("JSON", "*.json"), ("CSV", "*.csv")))
            if filename:
                try:
                    if filename.endswith('.json'):
                        with open(filename, 'w') as f:
                            json.dump({
                                'timestamp': datetime.now().isoformat(),
                                'results': results,
                                'settings': {
                                    'z_height': float(values.get("-Z_HEIGHT-", DEFAULT_Z)),
                                    'settle_time': float(values.get("-SETTLE_TIME-", DEFAULT_SETTLE_TIME)),
                                    'mask_center': (float(values.get("-CENTER_X-", DEFAULT_CENTER[0])),
                                                   float(values.get("-CENTER_Y-", DEFAULT_CENTER[1]))),
                                    'mask_radius': float(values.get("-RADIUS-", DEFAULT_RADIUS))
                                }
                            }, f, indent=2)
                    else:  # CSV
                        with open(filename, 'w', newline='') as f:
                            writer = csv.writer(f)
                            writer.writerow(['Well', 'X', 'Y', 'Z', 'Red', 'Green', 'Blue', 'Timestamp'])
                            for r in results:
                                writer.writerow([r['well'], r['x'], r['y'], r['z'],
                                                r['red'], r['green'], r['blue'], r['timestamp']])
                    sg.popup(f"Results saved to:\n{filename}", title="Success")
                except Exception as e:
                    sg.popup_error(f"Error saving file:\n{str(e)}", title="Error")
        
        # Plot results
        elif event == "-PLOT-":
            if not results:
                sg.popup_error("No results to plot.", title="Error")
                continue
            
            try:
                wells = [r['well'] for r in results]
                reds = [r['red'] for r in results]
                greens = [r['green'] for r in results]
                blues = [r['blue'] for r in results]
                
                plt.figure(figsize=(12, 6))
                x_pos = range(len(wells))
                width = 0.25
                
                plt.bar([x - width for x in x_pos], reds, width, label='Red', color='red', alpha=0.7)
                plt.bar(x_pos, greens, width, label='Green', color='green', alpha=0.7)
                plt.bar([x + width for x in x_pos], blues, width, label='Blue', color='blue', alpha=0.7)
                
                plt.xlabel('Well')
                plt.ylabel('RGB Value')
                plt.title('RGB Values by Well')
                plt.xticks(x_pos, wells, rotation=45, ha='right')
                plt.legend()
                plt.tight_layout()
                plt.show()
            except Exception as e:
                sg.popup_error(f"Error plotting:\n{str(e)}", title="Error")
    
    # Cleanup
    camera_running = False
    stop_capture = True
    if capture_thread and capture_thread.is_alive():
        capture_thread.join(timeout=2)
    
    if picam2:
        picam2.stop()
        picam2.close()
    
    window.close()

if __name__ == "__main__":
    main()
