#!/usr/bin/env python3
# Aria Corona Sept 19th, 2024

from NotionApiHelper import NotionApiHelper
from AutomatedEmails import AutomatedEmails
from datetime import datetime
from pathlib import Path
import csv, os, time, json, logging

'''
Dependencies:
- NotionApiHelper
- AutomatedEmails

Database Dependencies:
- MOD Jobs Database
    - ID
    - Customer Name
    - Product ID
    - Product Description
    - Quantity
    - Job Revenue
    - Order ID
    - Line Item
- MOD Orders Database
    - ID
    - Shipped Date
    - Order number
    - Jobs
    - Customer name
    - Status
    - Shipment cost
    - Tracking
    - Ship method
    - Pieces
    - Shipping ID
    - title
    - Customer

This script generates a weekly report of shipped orders for Meno On-Demand. It queries the Notion API for shipped orders and their associated jobs,
and generates a CSV file for each customer with the shipped orders for that week. It then sends an email to each customer with their CSV file as an attachment.
Sets all jobs to "Invoiced" in Notion after generating the report.
'''

notion_helper = NotionApiHelper()
automated_emails = AutomatedEmails()

ORDERS_EMAIL_CONF_PATH = "conf/MOD_Weekly_Kodi_Report_Email_Conf.json"
ORDERS_SUBJECT = f"MOD Shipped Orders by Customer {datetime.now().strftime('%m-%d-%Y')}"
ORDERS_BODY = "Attached are the shipped orders for each customer for Meno On-Demand.\n\n\n\nThis is an automated email being sent by the MOD Shipped Orders by Customer script. Please do not reply to this email. If you have any questions or concerns, please contact Aria Corona directly at acorona@menoenterprises.com."

FIRST_PART_EMAIL_CONF_PATH = "conf/MOD_FirstPartyOrders_Email_Conf.json"
FP_SUBJECT = f"MOD First Party Orders {datetime.now().strftime('%m-%d-%Y')}"
FP_BODY = "Attached are the first party orders for Meno On-Demand.\n\n\n\nThis is an automated email being sent by the MOD Shipped Orders by Customer script. Please do not reply to this email. If you have any questions or concerns, please contact Aria Corona directly at acorona@menoenterprises.com"

FIRT_PARTY_SHIPPING_PATH = Path(r'conf/CustomerFirstPartyShipping.json')

print("Starting Weekly Shipped Orders Report...")

OUTPUT_DIRECTORY = "output/MOD_WeeklyReportOutput"
os.makedirs(OUTPUT_DIRECTORY, exist_ok=True)

with open(FIRT_PARTY_SHIPPING_PATH, 'r') as file:
    customer_first_party_ship = json.load(file)
    
LOG_DIRECTORY = "logs"
os.makedirs(LOG_DIRECTORY, exist_ok=True)
logging.basicConfig(
    filename=os.path.join(LOG_DIRECTORY, 'MOD_ShippedOrdersByCustomer.log'),
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger()
    
ORDER_CONTENT_FILTER = {"and": [{"property": "Status", "select": {"equals": "Shipped"}}]}
JOB_CONTENT_FILTER = {
    "and": [
        {"property": "Created", "date": {"past_month": {}}},
        {"or": [
        {"property": "Job status", "select": {"equals": "Complete"}},
        {"property": "Job status", "select": {"equals": "Packout"}}
        ]}
    ]
}

# Shipped Date, Order Number, Jobs, Customer Name, ID, Status, Ship method, Shipment cost, Tracking, Pieces, Shipping ID, title, Customer
ORDER_FILTER_PROPS = [r"oKZj", r"E%5Bqx", r"iLNe", r"%7B%7BfG", r"qW%7D%5E", r"gS%5Cd", r"%60%7BTl", r"ppZT", r"~LUW", r"%60%5C%40d", r"%60%60Wq", r"title", r"iegJ"] 
# Order ID, ID, Customer Name, Product ID, Product Description, Quantity, Job revenue, Title
JOB_FILTER_PROPS = [r"Oe~K", r"nNsG", r"vruu", r"zUY%3F", r"%7CVjk", r"KQKT", r"LIf%7B", r"title"] 

ORDER_DB_ID = "d2747a287e974348870a636fbfa91e3e"
JOB_DB_ID = "f11c954da24143acb6e2bf0254b64079"

output_dict = {}
first_party_output_dict = {}
preflight_customer_perms = {}
job_dict = {}
customer_list = []
output_key_list = [] # Shipped Orders
file_list = [] # List of file paths for email attachments (Shipped Orders)
file_list_2 = [] # List of file paths for email attachments (First Party Orders)
errored_jobs = []
errored_orders = []
order_id_list = []


logger.info("Querying Notion API for orders...")
order_notion_response = notion_helper.query(ORDER_DB_ID, ORDER_FILTER_PROPS, ORDER_CONTENT_FILTER)

time.sleep(.5)
logger.info("Querying Notion API for jobs...")
job_notion_response = notion_helper.query(JOB_DB_ID, JOB_FILTER_PROPS, JOB_CONTENT_FILTER)

for page in job_notion_response: # Parsing Jobs into a dictionary by Job Page ID, to be used later when parsing Orders.
    jid = page["properties"]["ID"]["unique_id"]["number"]
    job_page_id = page["id"]
    
    try:
        customer_name = page["properties"]["Customer Name"]["formula"]["string"]
        product_id = page["properties"]["Product ID"]["formula"]["string"]
        product_description = page["properties"]["Product Description"]["formula"]["string"]
        quantity = page["properties"]["Quantity"]["number"]
        job_revenue = page["properties"]["Job revenue"]["formula"]["number"]
        order_id = page["properties"]["Order ID"]["formula"]["string"]
        line_item = page["properties"]["Job"]["title"][0]["plain_text"]

        if job_page_id not in job_dict: # Only adding jobs that haven't been added to the job_dict yet, in case of duplicate jobs for some reason.
            logger.info(f"New job found: {jid}")
            job_dict[job_page_id] = {
                "Customer Name": customer_name,
                "Product ID": product_id,
                "Product Description": product_description,
                "Quantity": quantity,
                "Job Revenue": job_revenue,
                "Order ID": order_id,
                "Line Item": line_item
            }
            
    except Exception as e:
        logger.error(f"Error processing job {jid}: {e}")
        errored_jobs.append(jid)
        
for page in order_notion_response: # Iterating through Orders to find Shipped Orders and matching Jobs. Adding to output_dict.
    oid = page["properties"]["ID"]["unique_id"]["number"]
    
    try:
        shipped_date = datetime.fromisoformat(page["properties"]["Shipped date"]["date"]["start"].replace('Z', '+00:00')).strftime('%m-%d-%Y')
        order_number = page["properties"]["Order number"]["rich_text"][0]["plain_text"]
        jobs_relation_property = page["properties"]["Jobs"]["relation"]
        customer_name = page["properties"]["Customer name"]["formula"]["string"]
        status = page["properties"]["Status"]["select"]["name"]
        shipping_cost = page["properties"]["Shipment cost"]["number"]
        tracking = page["properties"]["Tracking"]["rich_text"][0]["plain_text"] if page["properties"]["Tracking"]["rich_text"] else ""
        shipping_method = page["properties"]["Ship method"]["select"]["name"]
        pieces = page["properties"]["Pieces"]["formula"]["number"]
        shipping_id = page["properties"]["Shipping ID"]["rich_text"][0]["plain_text"] if page["properties"]["Shipping ID"]["rich_text"] else ""
        full_order_number = page["properties"]["Order"]["title"][0]["plain_text"]
        customer_notion_id = page["properties"]["Customer"]["relation"][0]["id"]
        
        if customer_name not in customer_list:
            customer_list.append(customer_name)
            logger.info(f"New customer found: {customer_name}")
            preflight_perms = notion_helper.get_page_property(customer_notion_id, r"I%3E%7Cy")
            
            try:
                customer_preflight_approval = preflight_perms['select']['name']
                allow_alter = int(customer_preflight_approval[0])
                preflight_customer_perms[customer_name] = allow_alter
                
            except:
                logger.error(f"Error getting preflight approval for customer {customer_name}. Defaulting to 0.")
                preflight_customer_perms[customer_name] = 0
                
        for id in jobs_relation_property:   # Iterating through Jobs in the Order
            job_page_id = id["id"]
            logger.info(f"Processing job {job_page_id} for order {order_number}")
            
            if job_page_id in job_dict and status == "Shipped": # Only processing Shipped Orders, also checks to make sure the job exists.
                
                if order_number not in output_dict: # New Order Number, adding to output_dict
                    output_dict[order_number] = {    
                        job_dict[job_page_id]["Line Item"]: {
                            "Product ID": job_dict[job_page_id]["Product ID"],
                            "Customer Name": customer_name,
                            "Shipped Date": shipped_date,
                            "Product Description": job_dict[job_page_id]["Product Description"],
                            "Quantity": job_dict[job_page_id]["Quantity"],
                            "Job Revenue": job_dict[job_page_id]["Job Revenue"],
                            "Shipping Method": shipping_method,
                            "Tracking": tracking
                        }
                    }
                    
                    if shipping_cost > 0:   # Adding Shipping Charge to output_dict
                        output_dict[order_number][f"SHIP_CHG_{order_number}"] = {    # Adding Shipping Charge to output_dict
                            "Product ID": "Shipping Charge",
                            "Customer Name": customer_name,
                            "Shipped Date": shipped_date,
                            "Product Description": "Shipping Charge",
                            "Quantity": 1,
                            "Job Revenue": (shipping_cost * 1.25),
                            "Shipping Method": shipping_method,
                            "Tracking": tracking
                        }
                        
                        logger.info(f"Shipping charge found for order {order_number}: {shipping_cost}")
                        
                        if customer_name in customer_first_party_ship:
                            if customer_first_party_ship[customer_name] == 1:
                                if order_number not in first_party_output_dict:
                                    first_party_output_dict[full_order_number] = {
                                        "Customer Name": customer_name,
                                        "Shipped Date": shipped_date,
                                        "Shipping Method": shipping_method,
                                        "Tracking": tracking,
                                        "Pieces": pieces,
                                        "Shipping Charge": (shipping_cost * 1.25),
                                        "Shipstation ID": shipping_id
                                    }
                                    
                                    logger.info(f"New first party order found: {order_number}")

                    output_key_list.append(order_number)
                    order_id_list.append(page['id'])
                    
                    logger.info(f"New order found: {order_number}")
                    logger.info(f"New line item found for order {order_number}: {job_dict[job_page_id]['Line Item']}")
                    
                else:   # Existing Order Number
                    output_dict[order_number][job_dict[job_page_id]["Line Item"]] = {    # New line item for existing Order Number, adding to output_dict
                        "Product ID": job_dict[job_page_id]["Product ID"],
                        "Customer Name": customer_name,
                        "Shipped Date": shipped_date,
                        "Product Description": job_dict[job_page_id]["Product Description"],
                        "Quantity": job_dict[job_page_id]["Quantity"],
                        "Job Revenue": job_dict[job_page_id]["Job Revenue"],
                        "Shipping Method": shipping_method,
                        "Tracking": tracking
                    }
                    
                    logger.info(f"New line item found for order {order_number}: {job_dict[job_page_id]['Line Item']}")
                    
    except Exception as e:
        logger.error(f"Error processing order ORD-{oid}: {e}")
        errored_orders.append(oid)
    
for customer in customer_list: # Creating a list of jobs for each customer.
    csv_file_name = os.path.join(OUTPUT_DIRECTORY, f"MOD_ShippedOrders_{customer}_{datetime.now().strftime('%Y-%m-%d')}.csv")
    file_list.append(csv_file_name)
    
    with open(csv_file_name, mode='w', newline='') as csv_file:
        csv_writer = csv.writer(csv_file)
        csv_writer.writerow(["Ship Date", "Order number", "Line Item", "Product", "Description", "Quantity", "Cost", "Shipping Method", "Tracking"])
        
        for key in output_dict: # Iterates through each order number in output_dict
            for line_item in output_dict[key]: # Iterates through each line item in the order number
                
                if output_dict[key][line_item]["Customer Name"] == customer:
                    csv_writer.writerow([
                        output_dict[key][line_item]["Shipped Date"],
                        key,
                        line_item,
                        output_dict[key][line_item]["Product ID"],
                        output_dict[key][line_item]["Product Description"],
                        output_dict[key][line_item]["Quantity"],
                        "${:,.2f}".format(output_dict[key][line_item]["Job Revenue"]),
                        output_dict[key][line_item]["Shipping Method"],
                        output_dict[key][line_item]["Tracking"]
                    ])
                    
        if preflight_customer_perms[customer] == 1:
            csv_writer.writerow(["","","","PREFLIGHT_AUTOSIZE", "Preflighting Image Correction Fee", 1, "$75.00","",""])
            
        if preflight_customer_perms[customer] == 2:
            csv_writer.writerow(["","","","PREFLIGHT_CHECK", "Preflighting Image Check Fee", 1, "$49.00","",""])
            
    logger.info(f"CSV written successfully as {csv_file_name}")

csv_file_name = os.path.join(OUTPUT_DIRECTORY, f"MOD_FirstPartyOrders_{datetime.now().strftime('%Y-%m-%d')}.csv")
file_list_2.append(csv_file_name)

with open(csv_file_name, mode='w', newline='') as csv_file:
    csv_writer = csv.writer(csv_file)
    csv_writer.writerow(["Ship Date", "Order number", "Pieces", "Shipstation ID", "Shipping Method", "Shipping Cost"])
    
    for key in first_party_output_dict:
        csv_writer.writerow([
            first_party_output_dict[key]["Shipped Date"],
            key,
            first_party_output_dict[key]["Pieces"],
            first_party_output_dict[key]["Shipstation ID"],
            first_party_output_dict[key]["Shipping Method"],
            "${:,.2f}".format(first_party_output_dict[key]["Shipping Charge"])
        ])
        
logger.info(f"CSV written successfully as {csv_file_name}")

logger.info("Errored Jobs:\n", errored_jobs)
logger.info("Errored Orders:\n", errored_orders)
logger.info("Preparing to send shipped orders email...")

automated_emails.send_email(ORDERS_EMAIL_CONF_PATH, ORDERS_SUBJECT, ORDERS_BODY, file_list)

logger.info("Preparing to send first party orders email...")

automated_emails.send_email(FIRST_PART_EMAIL_CONF_PATH, FP_SUBJECT, FP_BODY, file_list_2)

logger.info(f"Updating Orders as shipped: {output_key_list}")
order_status = notion_helper.generate_property_body("Status", "select", "Invoiced")

for id in order_id_list:
    logger.info(f"Updating order {id} to Invoiced...")
    notion_helper.update_page(id, order_status)
    
logger.info("End of script.")