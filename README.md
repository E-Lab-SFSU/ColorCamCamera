# ColorCamCamera
ColorCam using PI camera approach

## Installation on Raspberry Pi

Install required dependencies:

```bash
pip3 install -r requirements.txt
```

Or install individually:

```bash
pip3 install FreeSimpleGUI pyserial Pillow numpy matplotlib picamera2
```

## Dependencies

- **FreeSimpleGUI**: GUI framework (lightweight alternative to PySimpleGUI)
- **pyserial**: Serial communication for printer control
- **Pillow**: Image processing
- **numpy**: Numerical operations
- **matplotlib**: Plotting results
- **picamera2**: Raspberry Pi camera interface

## Files

- `well_plate_location_gui.py`: Well plate location calculator with printer control
- `camera_preview_crosshair.py`: Camera preview with crosshair overlay
- `colorcam.py`: Main color measurement application