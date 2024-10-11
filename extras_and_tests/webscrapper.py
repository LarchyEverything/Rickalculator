import csv
import os
import requests
from urllib.parse import quote

def clean_morty_name(name):
    # Remove 'Morty' from the end if present
    if name.endswith(' Morty'):
        name = name[:-6]
    
    # Handle special cases
    name = name.replace("'s", "")
    name = name.replace("S.O.S.", "SOS")
    name = name.replace("-", "")
    
    # Capitalize each word and remove remaining special characters
    return ''.join(word.capitalize() for word in name.split() if word.isalnum())

def download_morty_image(number, name, url):
    filename = f"{number}_{name}.png"
    filepath = os.path.join("morty_front", filename)
    
    response = requests.get(url)
    if response.status_code == 200:
        with open(filepath, 'wb') as f:
            f.write(response.content)
        print(f"Downloaded: {filename}")
    else:
        print(f"Failed to download: {filename}")

# Create the morty_front directory if it doesn't exist
os.makedirs("morty_front", exist_ok=True)

# Read the CSV file and download missing images
with open('All_Mortys.csv', 'r') as csvfile:
    reader = csv.reader(csvfile)
    next(reader)  # Skip the header row if it exists
    
    for row in reader:
        morty_number = row[0]
        morty_name = row[1]
        
        # Check if the image already exists
        if not os.path.exists(os.path.join("morty_front", f"{morty_number}_{morty_name}.png")):
            # Clean and format the Morty name
            cleaned_name = clean_morty_name(morty_name)
            
            # Generate the image filename
            image_name = f"Morty{cleaned_name}Front.png"
            
            # Create the full URL
            url = f"https://pocketmortys.net/media/com_pocketmortys/assets/{quote(image_name)}"
            
            # Download the image
            download_morty_image(morty_number, morty_name, url)

print("Download process completed.")