import cv2
import numpy as np
import pytesseract

# Global variable to store mouse coordinates
mouse_x, mouse_y = 0, 0

def mouse_callback(event, x, y, flags, param):
    global mouse_x, mouse_y
    if event == cv2.EVENT_MOUSEMOVE:
        mouse_x, mouse_y = x, y

def process_image(image_path):
    pytesseract.pytesseract.tesseract_cmd = 'C:\\Program Files\\Tesseract-OCR\\tesseract.exe'
    
    # Read the image
    img = cv2.imread(image_path)
    height, width = img.shape[:2]
    display_img = img.copy()
    
    # Define regions for each stat (x%, y%, w%, h%)
    regions = {
        'Number': (0.075, 0.0667, 0.0688, 0.05),
        'Level': (0.36875, 0.4083, 0.05, 0.05),
        'HP': (0.825, 0.2217, 0.04375, 0.0517),
        'Attack': (0.825, 0.3033, 0.04375, 0.0475),
        'Defense': (0.825, 0.3833, 0.04375, 0.05),
        'Speed': (0.825, 0.4667, 0.04375, 0.0438)
    }
    
    stats = {}
    for key, (x_pct, y_pct, w_pct, h_pct) in regions.items():
        x = int(x_pct * width)
        y = int(y_pct * height)
        w = int(w_pct * width)
        h = int(h_pct * height)
        
        roi = img[y:y+h, x:x+w]
        text = ocr_digit(roi, key)
        stats[key] = text
        
        # Draw rectangle on display image
        cv2.rectangle(display_img, (x, y), (x+w, y+h), (0, 255, 0), 2)
        cv2.putText(display_img, f"{key}: {text}", (x, y-5), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)
    
    # Display the image with rectangles
    cv2.imshow(f"Processed {image_path}", display_img)
    cv2.waitKey(0)
    cv2.destroyAllWindows()
    
    return stats

def ocr_digit(roi, key):
    # Convert ROI to grayscale
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    
    # Apply additional preprocessing
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    _, thresh = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    
    # Dilate the image to make digits more pronounced
    kernel = np.ones((2,2), np.uint8)
    dilated = cv2.dilate(thresh, kernel, iterations=1)
    
    # Use tesseract OCR with adjusted configuration
    if key == 'Number':
        config = '--psm 6 -c tessedit_char_whitelist=#0123456789'
    elif key == 'Level':
        config = '--psm 6 -c tessedit_char_whitelist=LV0123456789'
    else:
        config = '--psm 6 -c tessedit_char_whitelist=0123456789'
    
    text = pytesseract.image_to_string(dilated, config=config)
    
    # Post-process the text
    text = text.strip()
    if key == 'Number':
        text = ''.join(filter(lambda x: x.isdigit() or x == '#', text))
    elif key == 'Level':
        text = ''.join(filter(lambda x: x.isdigit(), text))
    
    return text

# Test with the two images
image_paths = ['grom.png', 'wasp.png']

for i, path in enumerate(image_paths, 1):
    print(f"Processing image {i}:")
    stats = process_image(path)
    for key, value in stats.items():
        print(f"{key}: {value}")
    print("\n")