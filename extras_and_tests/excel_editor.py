import openpyxl
import csv

def excel_links_to_csv(excel_file, output_csv):
    # Load the workbook and select the first worksheet
    wb = openpyxl.load_workbook(excel_file, data_only=True)
    sheet = wb.active

    # Get the hyperlinks from the second column
    links = []
    for row in sheet.iter_rows(min_col=2, max_col=2, min_row=2):  # Start from row 2 to skip header
        cell = row[0]
        if cell.hyperlink:
            links.append(cell.hyperlink.target)
        else:
            links.append(None)  # or '' if you prefer empty string for cells without hyperlinks

    # Write the links to a CSV file
    with open(output_csv, 'w', newline='', encoding='utf-8') as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(['Links'])  # Header
        for link in links:
            writer.writerow([link])

    print(f"CSV file '{output_csv}' has been created with {len(links)} links.")

# Usage
excel_file = 'All_Mortys.xlsx'
output_csv = 'morty_links.csv'
excel_links_to_csv(excel_file, output_csv)
