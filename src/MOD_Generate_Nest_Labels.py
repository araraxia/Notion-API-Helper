#!/usr/bin/env python3

from MOD_Generate_Nest_Labels_Logger import logger
from NotionApiHelper import NotionApiHelper
from svglib.svglib import svg2rlg
from PIL import Image
from io import BytesIO
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload, MediaIoBaseDownload
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.graphics import renderPDF
from reportlab.lib.utils import ImageReader
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import Paragraph
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from math import floor
import sys, logging, datetime, json, qrcode, re, uuid
import qrcode.image.svg


notion = NotionApiHelper()

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s', handlers=[
    logging.FileHandler('logs/MOD_Generate_Nest_Labels.log'),
    logging.StreamHandler()
])
logger = logging.getLogger(__name__)

SERVICE_ACCOUNT_FILE = 'cred/green-campaign-438119-v8-17ab715c7730.json'
SCOPES = ['https://www.googleapis.com/auth/drive.readonly']

gdrive_credentials = service_account.Credentials.from_service_account_file(
    SERVICE_ACCOUNT_FILE, scopes=SCOPES)

drive_service = build('drive', 'v3', credentials=gdrive_credentials)

LABEL_GEN_PACKAGE = {'Print Status': {'select': {'name': 'Label generating'}}}
LABEL_CREATED_PACKAGE = {'Print Status': {'select': {'name': 'Label created'}}}
LABEL_ERROR_PACKAGE = {'System status': {'select': {'name': 'Error'}}}
jobrep_label_url_package = {'Label Printed': {'select': {'name': 'Printed'}}, "Label URL": {'url': None}}

LIST_NAMES = ['Jobs', 'Reprints']

NEST_LOG_PROP_ID = "%3BNMV"

JOB_DB_ID = 'f11c954da24143acb6e2bf0254b64079'
REPRINT_DB_ID = 'f631a4f09c27427dbe70f4d7a2e61e9c'
THUMBNAIL_FOLDER_ID = '1hBeSlW4h56-BmygGdeNCeZF--1gTb9Zm'
PDF_FOLDER_ID = '1HuAFqh8ITutdjSOBxo-qKU73ujVNFzMB'
COPY_FOLDER_ID = '1BL6BxkJR7GV067DKk8z1-qXlnlOg4cTM'
FILE_VIEWER_URL = 'https://drive.google.com/file/d/#ID#/view'

PDF_OUTPUT_PATH = 'output/mod/labels.pdf'
INTERNAL_STORAGE_ID_REGEX = re.compile(r'\d*__(.*)')
NEST_NAME_REGEX = re.compile(r'(\w*\s\#\d*)')

PAGE_WIDTH = 8.5 * inch # pixels, letter size
PAGE_HEIGHT = 11 * inch # pixels, letter size

LABELS_PER_PAGE = 10
LABEL_COLLUMNS = 2
LABEL_ROWS = 5

LABEL_WIDTH = 4 * inch # pixels
LABEL_HEIGHT = 2 * inch # pixels

PAGE_LR_MARGIN = floor((PAGE_WIDTH - (LABEL_WIDTH * 2)) / 2)
PAGE_TB_MARGIN = floor((PAGE_HEIGHT - (LABEL_HEIGHT * 5)) /2)

LABEL_FONT = 'Courier'
FONT_SIZE = 10 # pt
LABEL_FONT_BOLD = 'Courier-Bold'
BOLD_FONT_SIZE = 12 # pt

PADDING = 3
CENTER_DEVISOR = 5

HEADER_PLACEMENT = (PAGE_LR_MARGIN, PAGE_HEIGHT - PAGE_TB_MARGIN + PADDING)
HEADER_FONT_SIZE = 24

THUMBNAIL_MAX_SIZE = (80, 144) # pixels
THUMBNAIL_POS = (0, 0)

QR_CODE_MAX_SIZE = (floor(LABEL_HEIGHT * (2/5)), floor(LABEL_HEIGHT * (2/5))) # pixels
QR_CODE_1_POS = (THUMBNAIL_MAX_SIZE[0], 0) 
QR_CODE_2_POS = (LABEL_WIDTH - QR_CODE_MAX_SIZE[0], 0)

ROW_NEST = (THUMBNAIL_MAX_SIZE[0], QR_CODE_MAX_SIZE[1]+PADDING)
ROW_NEST_MAX_WIDTH = 95 # pixels

SHIP_BY_ROW = (ROW_NEST[0] + ROW_NEST_MAX_WIDTH, QR_CODE_MAX_SIZE[1]+PADDING)

PROD_DESCRIPTION = (THUMBNAIL_MAX_SIZE[0], ROW_NEST[1] + BOLD_FONT_SIZE + PADDING)
PROD_DESCRIPTION_MAX_WIDTH = LABEL_WIDTH - THUMBNAIL_MAX_SIZE[0]
PROD_DESCRIPTION_MAX_HEIGHT = 30 # pixels

ORDER_NUMBER = (THUMBNAIL_MAX_SIZE[0], PROD_DESCRIPTION[1] + PROD_DESCRIPTION_MAX_HEIGHT + PADDING)
ORDER_NUMBER_MAX_WIDTH = LABEL_WIDTH - THUMBNAIL_MAX_SIZE[0]

ITEM_QUANT = (THUMBNAIL_MAX_SIZE[0], ORDER_NUMBER[1] + FONT_SIZE + PADDING)
ITEM_QUANT_MAX_WIDTH = floor((LABEL_WIDTH - THUMBNAIL_MAX_SIZE[0]) / 2)

JOB_QUANT = (ITEM_QUANT[0] + ITEM_QUANT_MAX_WIDTH, ORDER_NUMBER[1] + FONT_SIZE + PADDING)
JOB_QUANT_MAX_WIDTH = ITEM_QUANT_MAX_WIDTH

ROW_CUSTOMER = (THUMBNAIL_MAX_SIZE[0], ITEM_QUANT[1] + FONT_SIZE + PADDING)
ROW_CUSTOMER_MAX_WIDTH = floor((LABEL_WIDTH - THUMBNAIL_MAX_SIZE[0]) * (2/3))

ROW_UID = (ROW_CUSTOMER[0] + ROW_CUSTOMER_MAX_WIDTH, ITEM_QUANT[1] + FONT_SIZE + PADDING)




def catch_variable():
    try:
        nest_id = sys.argv[1]
        return nest_id
    except IndexError:
        logger.error("Nothing passed to MOD_Generate_Nest_Labels.py. Exiting.")
        sys.exit(1)


def report_error(id, error_message):
    """
    Logs an error message and updates the corresponding page in Notion with the error log.
    Args:
        id (str): The ID of the Notion page to update.
        error_message (str): The error message to log and update in the Notion page.
    Returns:
        None
    """
    
    logger.error(f"Error: {error_message}")
    
    # Get old log, add new log, update page
    now = datetime.datetime.now()
    
    old_log = notion.get_page_property(id, NEST_LOG_PROP_ID)
    error_log = f"{now}::{error_message}\n{old_log}" if old_log else f"{now}::{error_message}"
    log_package = notion.rich_text_prop_gen('Logs', 'rich_text', error_log)
    package = {**LABEL_ERROR_PACKAGE, **log_package}
    
    notion.update_page(id, package)
    return


def get_page_info(id):
    logger.info(f"Getting page info - {id}")
    response = notion.get_page(id)
    
    if not response:
        logger.error("No response returned. Exiting.")
        sys.exit(1)
        
    if 'properties' not in id:
        logger.error("No properties found in response. Exiting.")
        sys.exit(1)
    
    logger.info("Response returned.")
    return response


def update_page_info(id, package):
    logger.info(f"Updating page info - {id}\n{package}")
    response = notion.update_page(id, package)
    
    if not response:
        error_message = "No response returned when updating page info."
        report_error(id, error_message)
        sys.exit(1)
        
    if 'properties' not in response:
        error_message = "No properties found in response when updating page info."
        report_error(id, error_message)
        sys.exit(1)
    
    logger.info("Response returned.")
    return response


def update_nest_page_info(content_dict, label_dict, file_id):
    logger.info("Updating nest page info.")
    
    label_url = f"{FILE_VIEWER_URL.replace('#ID#', file_id)}"
    
    for jobrep in LIST_NAMES:
        if jobrep in content_dict:
            for page in content_dict[jobrep]:
                page_id = page['id']
                
                if 'Label URL' not in page['properties']:
                    logger.error(f"Label URL property not found in page {page_id}.")
                    continue
                
                existing_labels = notion.return_property_value(page['properties']['Label URL'], page_id)
                labels = f"{label_url}, {existing_labels}" if existing_labels else label_url
                jobrep_label_url_package['Label URL']['url'] = labels
                
                logging.info(f"Updating page {page_id} with {label_url}.")
                response = notion.update_page(page_id, jobrep_label_url_package)
                
    logging.info("Updating nest page with completion status.")
    response = notion.update_page(content_dict['Nest']['id'], LABEL_CREATED_PACKAGE)            
                

def process_nest_content(nest_id, jobs, reprints):
    """
    Creates a filter including an or statement for each job/rep ID. Queries the jobs and 
    reprints databases for their page content

    Args:
        nest_id (str): The ID of the nest being processed.
        jobs (list): A list of job page IDs to be queried.
        reprints (list): A list of reprint page IDs to be queried.
    Returns:
        dict: A dictionary containing the queried jobs and reprints, with keys 'Jobs' and 'Reprints'.
    """
    
    logging.info(f"Processing nest {nest_id} content.")
    
    content_dict = {}
    
    # Need to query jobs and reprints separately
    for prop_name, list in [('Jobs', jobs), ('Reprints', reprints)]:
        content_filter = {'or': []}
        
        if list:
            # Create filter for each page_id in list, one query per db as opposed to one get request per page_id.
            for page_id in list:
                filter_template = {'property': 'Notion record', 'formula': {'string': {'contains': page_id}}}
                content_filter['or'].append(filter_template)        
            
            # Get jobs or reprints page content
            db_id = JOB_DB_ID if prop_name == 'Jobs' else REPRINT_DB_ID
            logger.info(json.dumps(content_filter))
            response = notion.query(db_id, content_filter=content_filter)
            
            # Add page data to content_dict
            content_dict[prop_name] = response

    return content_dict


def generate_qr_code(qr_value, fill_color = 'black', back_color = 'white'):
    logger.info(f"Generating QR code for {qr_value}")
    
    qr = qrcode.QRCode(
        version=3,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=6,
        border=0,
    )
    
    qr.add_data(qr_value)
    qr.make(fit=True)
    
    factory = qrcode.image.svg.SvgImage
    qr_code_image = qr.make_image(image_factory=factory, fill_color=fill_color, back_color=back_color)
    
    qr_code_io = save_image_to_memory(qr_code_image)
    
    return qr_code_io


def generate_thumbnail(isid, page_id): #isid:internal_storage_id
    logger.info(f"Generating thumbnail for {isid}")
    
    source_fh = download_file_from_drive(isid)
    
    with Image.open(BytesIO(source_fh.read())) as image:
            image.thumbnail(THUMBNAIL_MAX_SIZE, Image.LANCZOS)
            image_height = image.size[1]
            image_io = save_image_to_memory(image)
            #thumbnail_id = upload_file_to_drive(image_io, f'thumbnail_{page_id}.jpg', 'image/jpeg', THUMBNAIL_FOLDER_ID)
    
    
    return image_io, image_height


def save_image_to_memory(image):
    logger.info("Saving image to memory.")
    
    image_io = BytesIO()
    image.save(image_io, format='JPEG')
    image_io.seek(0)
    
    return image_io


def download_file_from_drive(file_id):
    logger.info(f"Downloading file {file_id} from Google Drive.")
    
    request = drive_service.files().get_media(fileId=file_id)
    fh = BytesIO()
    downloader = MediaIoBaseDownload(fh, request)
    
    done = False
    while not done:
        status, done = downloader.next_chunk()
        logger.info(f"Download {int(status.progress() * 100)}%.")
    
    fh.seek(0)
    return fh


def upload_file_to_drive(file_io, file_name, mime_type, folder_id):
    logger.info(f"Uploading file {file_name} to Google Drive.")
    
    file_io.seek(0)
    
    file_metadata = {
        'name': file_name,
        'parents': [folder_id]
        }
    
    media = MediaIoBaseUpload(file_io, mimetype=mime_type)
    
    file = drive_service.files().create(
        body=file_metadata,
        media_body=media,
        fields='id'
    )
    
    try:
        file.execute()
    except Exception as e:
        logger.error(f"Error uploading file to Google Drive: {e}", exc_info=True)
        return None
    
    logger.info(f"File ID: {file.get('id')}")
    return file.get('id')


def process_jobrep_content(content_dict):
    """
    Processes job and reprint content from a given dictionary and generates a list of label dictionaries.
    Args:
        content_dict (dict): A dictionary containing job and reprint content with nested properties.
    Returns:
        list: A list of dictionaries, each representing a label with various properties such as page_id, 
              ship_date, order_number, nest_name, quantity, product_description, customer, shipstation_qr_code, 
              qr_code, thumbnail, thumbnail_height, line_code, uid, and label_urls.
    Raises:
        KeyError: If required keys are missing in the content_dict or its nested properties.
        AttributeError: If regex matching fails for certain properties.
        ValueError: If date parsing fails for the ship_date property.
    """
    
    
    logger.info("Processing job and reprint content.")
    
    # Get nest name from nest page
    nest_name = notion.return_property_value(
        content_dict['Nest']['properties']['Name'], content_dict['Nest']['id'])
    nest_name = NEST_NAME_REGEX.match(nest_name).group(1)
    
    # Initialize label_dict with template
    label_dict = []
    label_dict_template = {
        'page_id': None,
        'ship_date': None,
        'order_number': None,
        'nest_name': nest_name,
        'quantity': None,
        'product_description': None,
        'customer': None,
        'shipstation_qr_code': None,
        'qr_code': None,
        'thumbnail': None,
        'thumbnail_height': THUMBNAIL_MAX_SIZE[1],
        'line_code': None,
        'uid': None,
        'label_urls': []
    }

    # Iterate through jobs and reprints
    for jobrep in LIST_NAMES:
        if jobrep in content_dict:
            for page in content_dict[jobrep]:
    
                
                single_label_dict = label_dict_template.copy()
                page_props = page['properties']
                page_id = page['id']
                notion_link = f'https://www.notion.so/menoenterprises/{page_id.replace("-", "")}'
                
                # Get internal storage ID to get artwork for thumbnail.
                internal_storage_id = notion.return_property_value(page_props['Internal storage ID'], page_id)
                internal_storage_id = INTERNAL_STORAGE_ID_REGEX.match(internal_storage_id).group(1)
                
                # Add properties to single_label_dict
                single_label_dict['page_id'] = page_id
                single_label_dict['order_number'] = notion.return_property_value(page_props['Order ID'], page_id)
                single_label_dict['customer'] = notion.return_property_value(page_props['Customer ID'], page_id)
                
                try:
                    single_label_dict['line_code'] = notion.return_property_value(page_props['Line item'], page_id)
                except:
                    single_label_dict['line_code'] = "N/a"
                
                try:
                    ship_date = notion.return_property_value(page_props['Ship date'], page_id)
                except:
                    ship_date = notion.return_property_value(page_props['Ship Date'], page_id)
                    
                if ship_date:
                    single_label_dict['ship_date'] = datetime.datetime.strptime(
                        ship_date, '%Y-%m-%dT%H:%M:%S.%f%z').strftime('%m-%d-%Y')
                else:
                    single_label_dict['ship_date'] = "--"
                
                single_label_dict['product_description'] = notion.return_property_value(
                    page_props['Product Description'], page_id)
                
                single_label_dict['uid'] = f"{
                    page_props['ID']['unique_id']['prefix']}-{str(page_props['ID']['unique_id']['number'])}"
                
                single_label_dict['label_urls'] = notion.return_property_value(page_props['Label URL'], page_id)
                
                # Images and QR codes
                single_label_dict['thumbnail'], single_label_dict['thumbnail_height'] = generate_thumbnail(
                    internal_storage_id, page_id)
                single_label_dict['qr_code'] = generate_qr_code(notion_link)
                single_label_dict['shipstation_qr_code'] = generate_qr_code(
                    notion.return_property_value(page_props['Order Title'], page_id), fill_color='green')
                
                # Quantity handling
                try:
                    quantity = int(notion.return_property_value(page_props['Quantity'], page_id))
                except:
                    quantity = int(notion.return_property_value(page_props['Reprint quantity'], page_id))
                
                # Generates one label per quantity
                for i in range(1, quantity+1):
                    single_label_dict['quantity'] = f"{i}-{quantity}"
                    label_dict.append(single_label_dict.copy())
            
    return label_dict


def truncate_text(text, max_width, font_name, font_size):
    while pdfmetrics.stringWidth(text, font_name, font_size) > max_width:
        text = text[:-1]
    
    return text


def draw_svg_on_canvas(c, svg_io, x, y, max_width, max_height):
    # Convert the SVG to a ReportLab drawing object
    drawing = svg2rlg(svg_io)
    
    # Calculate the scaling factor
    scale_x = max_width / drawing.width
    scale_y = max_height / drawing.height
    scale = min(scale_x, scale_y)
    
    # Apply the scaling factor
    drawing.width *= scale
    drawing.height *= scale
    drawing.scale(scale, scale)
    
    # Draw the scaled drawing on the canvas
    renderPDF.draw(drawing, c, x, y)


def draw_label(c, label, x, y):
    """
    Draw a single label on the canvas at the specified position.
    """
    styles = getSampleStyleSheet()
    styleN = ParagraphStyle(
        'CustomStyle',
        parent=styles['Normal'],
        fontName=LABEL_FONT,
        fontSize=FONT_SIZE,
        leading=11
    )
    
    c.setFont(LABEL_FONT_BOLD, BOLD_FONT_SIZE)
    c.drawString(x+ROW_UID[0], y+ROW_UID[1], f"{label['uid']}")

    truncated_text = truncate_text(label['nest_name'], ROW_NEST_MAX_WIDTH, f"{LABEL_FONT}-Bold", BOLD_FONT_SIZE)
    c.drawString(x+ROW_NEST[0], y+ROW_NEST[1], truncated_text)
    
    c.setFont(LABEL_FONT, FONT_SIZE)
    c.drawString(x+ROW_CUSTOMER[0], y+ROW_CUSTOMER[1], f"{label['customer']}")
    c.drawString(x+ITEM_QUANT[0], y+ITEM_QUANT[1], f"Item Qty:{label['quantity']}")
    
    truncated_text = truncate_text(f"{label['customer']}", ROW_CUSTOMER_MAX_WIDTH, LABEL_FONT, FONT_SIZE)
    c.drawString(x+ROW_CUSTOMER[0], y+ROW_CUSTOMER[1], truncated_text)
    
    truncated_text = truncate_text(f"Order#:{label['order_number']}", ORDER_NUMBER_MAX_WIDTH, LABEL_FONT, FONT_SIZE)
    c.drawString(x+ORDER_NUMBER[0], y+ORDER_NUMBER[1], truncated_text)
    
    truncated_text = truncate_text(f"Job Qty:{label['line_code']}", JOB_QUANT_MAX_WIDTH, LABEL_FONT, FONT_SIZE)
    c.drawString(x+JOB_QUANT[0], y+JOB_QUANT[1], truncated_text)
    
    product_description = Paragraph(label['product_description'], styleN)
    product_description.wrapOn(c, PROD_DESCRIPTION_MAX_WIDTH, PROD_DESCRIPTION_MAX_HEIGHT)
    product_description.drawOn(c, x + PROD_DESCRIPTION[0], y + PROD_DESCRIPTION[1])
    
    c.drawString(x + SHIP_BY_ROW[0], y + SHIP_BY_ROW[1], f"SHIP-BY:{label['ship_date']}")

    if label['qr_code']:
        qr_code_io = BytesIO(label['qr_code'].getvalue())
        qr_code_io.seek(0)
        draw_svg_on_canvas(
            c, qr_code_io, x + QR_CODE_2_POS[0], y + QR_CODE_2_POS[1], QR_CODE_MAX_SIZE[0], QR_CODE_MAX_SIZE[1])
        qr_code_io.close()

    if label['shipstation_qr_code']:
        shipstation_qr_code_io = BytesIO(label['shipstation_qr_code'].getvalue())
        shipstation_qr_code_io.seek(0) 
        draw_svg_on_canvas(
            c, shipstation_qr_code_io, x + QR_CODE_1_POS[0], y + QR_CODE_1_POS[1], QR_CODE_MAX_SIZE[0], QR_CODE_MAX_SIZE[1])
        shipstation_qr_code_io.close()

    if label['thumbnail']:
        thumbnail_io = BytesIO(label['thumbnail'].getvalue())
        thumbnail_io.seek(0)  
        c.drawImage(ImageReader(thumbnail_io), x + THUMBNAIL_POS[0], y + THUMBNAIL_POS[1] + 
                    ((THUMBNAIL_MAX_SIZE[1] - label['thumbnail_height'])/2),)
        thumbnail_io.close()


def generate_labels(label_dict):
    logger.info("Generating labels.")
    
    pdf_io = BytesIO()
    
    c = canvas.Canvas(pdf_io, pagesize=letter)
    
    for index, label in enumerate(label_dict):
        label_counter = (index + 1) % LABELS_PER_PAGE
        side_indicator = index % LABEL_COLLUMNS
        
        x_pos = PAGE_LR_MARGIN + ((side_indicator) * LABEL_WIDTH)
        x_pos = x_pos - CENTER_DEVISOR if side_indicator == 0 else x_pos + CENTER_DEVISOR
        
        y_pos = PAGE_TB_MARGIN + ((index % LABEL_ROWS) * LABEL_HEIGHT)

        draw_label(c, label, x_pos, y_pos)
       
        if label_counter == 0:
            c.setFont(LABEL_FONT_BOLD, HEADER_FONT_SIZE)
            c.drawString(HEADER_PLACEMENT[0], HEADER_PLACEMENT[1], f"MOD Labels")
            logging.info(f"Page {index//LABELS_PER_PAGE} complete.")
            c.showPage()
       
    c.save()
    logger.info(f"Labels saved to PDF in memory.")
    return pdf_io


def main():
    unique_id = str(uuid.uuid4())    
    nest_id = catch_variable()
    logger.info(f"[START] - {unique_id} - Nest ID: {nest_id}")
    
    # Update page to Label generating, gets page properties as a response.
    nest_page = update_page_info(nest_id, LABEL_GEN_PACKAGE)
    
    # Get properties from page response
    nest_properties = nest_page['properties']
    
    jobs = []
    reps = []
    
    # Get jobs and reprints for nest
    for each, variable in [('Jobs', jobs), ('Reprints', reps)]:
        variable.extend(notion.return_property_value(nest_properties[each], nest_id))
    
    # If no jobs or reprints found, log error and exit.
    if all([not jobs, not reps]):
        log_message = f"No jobs or reprints found for nest {nest_id}."
        report_error(nest_id, log_message)
        sys.exit(1)
        
    # Get content for nest, jobs, and reprints
    content_dict = process_nest_content(nest_id, jobs, reps)
    
    # Add nest data to the content_dict, which includes job and reprint data
    content_dict['Nest'] = nest_page
        
    # Process content for labels
    label_dict = process_jobrep_content(content_dict)
    
    # Generate labels and upload to Google Drive
    pdf_io = generate_labels(label_dict)
    
    # Upload PDF to Google Drive
    filename = f'MOD-{unique_id}_{datetime.datetime.now().strftime("%Y-%m-%d-%H-%M")}.pdf'
    file_id = upload_file_to_drive(pdf_io, filename, 'application/pdf', PDF_FOLDER_ID)
    copied_id = upload_file_to_drive(pdf_io, filename, 'application/pdf', COPY_FOLDER_ID)
    
    # Close PDF in memory
    pdf_io.close()
    
    # Update nest, jobs, and reps with label URL
    update_nest_page_info(content_dict, label_dict, file_id)
    
    logger.info(f"[END] - {unique_id} - Nest ID: {nest_id}")
    
if __name__ == '__main__':
    logger.info("MOD_Generate_Nest_Labels.py started")
    main()