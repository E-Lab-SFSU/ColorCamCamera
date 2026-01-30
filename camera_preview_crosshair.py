#!/usr/bin/env python3
"""
Camera Preview with Center Crosshair
Simple standalone tool to show live camera preview with crosshair overlay.

Use this while setting up well plate locations to ensure the camera is centered
over each well.

Author: Created for well plate setup
Date: 2025
"""

import FreeSimpleGUI as sg
import time
import threading
from PIL import Image, ImageDraw

from picamera2 import Picamera2

# ===== Configuration =====
DEFAULT_SIZE = (640, 480)
CROSSHAIR_COLOR = (255, 0, 0)  # Red
CROSSHAIR_WIDTH = 2
CROSSHAIR_LENGTH = 30  # Length of each crosshair line
CROSSHAIR_GAP = 5  # Gap in center

# ===== Global variables =====
picam2 = None
camera_running = False
crosshair_center_x = DEFAULT_SIZE[0] // 2
crosshair_center_y = DEFAULT_SIZE[1] // 2
crosshair_length = CROSSHAIR_LENGTH
crosshair_gap = CROSSHAIR_GAP
crosshair_width = CROSSHAIR_WIDTH

# ===== Camera Functions =====

def init_camera():
    """Initialize Pi Camera."""
    global picam2
    try:
        # Initialize camera object
        picam2 = Picamera2()
        
        # Small delay to ensure camera is ready
        time.sleep(0.1)
        
        # Create video configuration - this is where the error often occurs
        # The error "list index out of range" can happen if camera controls
        # are not yet available or camera is not properly detected
        try:
            still_config = picam2.create_video_configuration(
                main={'size': DEFAULT_SIZE, 'format': 'BGR888'}
            )
        except (IndexError, AttributeError) as e:
            print(f"Error creating video configuration: {e}")
            # Try alternative: preview configuration
            try:
                print("Trying preview configuration instead...")
                still_config = picam2.create_preview_configuration(
                    main={'size': DEFAULT_SIZE, 'format': 'BGR888'}
                )
            except Exception as e2:
                print(f"Error creating preview configuration: {e2}")
                # Try minimal configuration
                try:
                    print("Trying minimal configuration...")
                    still_config = picam2.create_preview_configuration()
                except Exception as e3:
                    print(f"Error creating minimal configuration: {e3}")
                    return False
        
        # Configure and start camera
        picam2.configure(still_config)
        picam2.start()
        
        # Give camera a moment to start
        time.sleep(0.5)
        
        return True
    except IndexError as e:
        print(f"Error initializing camera (list index out of range): {e}")
        print("This usually means no camera is detected or camera is not ready.")
        print("Troubleshooting steps:")
        print("  1. Check camera connection")
        print("  2. Ensure no other process is using the camera")
        print("  3. Try: sudo systemctl restart libcamera")
        print("  4. Check: libcamera-hello --list-cameras")
        if picam2:
            try:
                picam2.close()
            except:
                pass
        return False
    except Exception as e:
        print(f"Error initializing camera: {e}")
        import traceback
        traceback.print_exc()
        if picam2:
            try:
                picam2.close()
            except:
                pass
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

def draw_crosshair(img, center_x, center_y, color, width, length, gap):
    """Draw a crosshair on the image."""
    draw = ImageDraw.Draw(img)
    
    # Horizontal line (left part)
    draw.line(
        [(center_x - length, center_y), (center_x - gap, center_y)],
        fill=color,
        width=width
    )
    # Horizontal line (right part)
    draw.line(
        [(center_x + gap, center_y), (center_x + length, center_y)],
        fill=color,
        width=width
    )
    # Vertical line (top part)
    draw.line(
        [(center_x, center_y - length), (center_x, center_y - gap)],
        fill=color,
        width=width
    )
    # Vertical line (bottom part)
    draw.line(
        [(center_x, center_y + gap), (center_x, center_y + length)],
        fill=color,
        width=width
    )
    
    # Optional: Draw center dot
    dot_radius = 3
    draw.ellipse(
        [(center_x - dot_radius, center_y - dot_radius),
         (center_x + dot_radius, center_y + dot_radius)],
        fill=color,
        outline=color
    )
    
    return img

# ===== Camera Preview Thread =====

def camera_preview_thread(window, preview_key):
    """Continuously update camera preview with crosshair."""
    global camera_running, picam2, crosshair_center_x, crosshair_center_y
    global crosshair_length, crosshair_gap, crosshair_width
    
    while camera_running:
        if picam2 is None:
            time.sleep(0.1)
            continue
        
        try:
            img = get_camera_frame()
            if img is not None:
                # Draw crosshair using current global values
                img = draw_crosshair(
                    img,
                    crosshair_center_x,
                    crosshair_center_y,
                    CROSSHAIR_COLOR,
                    crosshair_width,
                    crosshair_length,
                    crosshair_gap
                )
                
                # Convert to bytes for FreeSimpleGUI
                import io
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
    center_x = DEFAULT_SIZE[0] // 2
    center_y = DEFAULT_SIZE[1] // 2
    
    layout = [
        [sg.Text("Camera Preview with Crosshair", font=("Helvetica", 16, "bold"))],
        [sg.Text("Use this preview to center the camera over wells", font=("Helvetica", 10))],
        [sg.HSeparator()],
        
        [sg.Image(key="-PREVIEW-", size=DEFAULT_SIZE)],
        
        [sg.HSeparator()],
        
        [
            sg.Column([
                [sg.Text("Crosshair Settings", font=("Helvetica", 12, "bold"))],
                [sg.Text("Center X:"), sg.Input(str(center_x), key="-CENTER_X-", size=(10, 1), enable_events=True)],
                [sg.Text("Center Y:"), sg.Input(str(center_y), key="-CENTER_Y-", size=(10, 1), enable_events=True)],
                [sg.Button("Reset to Center", key="-RESET_CENTER-")],
            ]),
            sg.Column([
                [sg.Text("Crosshair Appearance", font=("Helvetica", 12, "bold"))],
                [sg.Text("Length:"), sg.Input(str(CROSSHAIR_LENGTH), key="-LENGTH-", size=(10, 1), enable_events=True)],
                [sg.Text("Gap:"), sg.Input(str(CROSSHAIR_GAP), key="-GAP-", size=(10, 1), enable_events=True)],
                [sg.Text("Width:"), sg.Input(str(CROSSHAIR_WIDTH), key="-WIDTH-", size=(10, 1), enable_events=True)],
            ])
        ],
        
        [sg.HSeparator()],
        
        [sg.Text("Status: Ready", key="-STATUS-")],
        [sg.Button("Exit", key="-EXIT-", button_color=("white", "red"))],
    ]
    
    return layout

# ===== Main GUI =====

def main():
    global picam2, camera_running
    
    sg.theme("LightGreen")
    
    # Initialize camera
    if not init_camera():
        sg.popup_error("Failed to initialize camera. Exiting.", title="Error")
        return
    
    # Create GUI
    window = sg.Window(
        "Camera Preview with Crosshair",
        create_gui_layout(),
        resizable=False,
        finalize=True
    )
    
    # Start camera preview thread
    camera_running = True
    preview_thread = threading.Thread(
        target=camera_preview_thread,
        args=(window, "-PREVIEW-"),
        daemon=True
    )
    preview_thread.start()
    
    # Main event loop
    while True:
        event, values = window.read(timeout=100)
        
        if event == sg.WIN_CLOSED or event == "-EXIT-":
            break
        
        # Update crosshair center position
        elif event == "-CENTER_X-":
            try:
                crosshair_center_x = int(values["-CENTER_X-"])
            except ValueError:
                pass
        
        elif event == "-CENTER_Y-":
            try:
                crosshair_center_y = int(values["-CENTER_Y-"])
            except ValueError:
                pass
        
        elif event == "-RESET_CENTER-":
            crosshair_center_x = DEFAULT_SIZE[0] // 2
            crosshair_center_y = DEFAULT_SIZE[1] // 2
            window["-CENTER_X-"].update(str(crosshair_center_x))
            window["-CENTER_Y-"].update(str(crosshair_center_y))
        
        # Update crosshair appearance
        elif event == "-LENGTH-":
            try:
                crosshair_length = int(values["-LENGTH-"])
            except ValueError:
                pass
        
        elif event == "-GAP-":
            try:
                crosshair_gap = int(values["-GAP-"])
            except ValueError:
                pass
        
        elif event == "-WIDTH-":
            try:
                crosshair_width = int(values["-WIDTH-"])
            except ValueError:
                pass
    
    # Cleanup
    camera_running = False
    if preview_thread.is_alive():
        preview_thread.join(timeout=2)
    
    if picam2:
        picam2.stop()
        picam2.close()
    
    window.close()

if __name__ == "__main__":
    main()

