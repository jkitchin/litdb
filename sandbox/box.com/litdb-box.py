"""This is going to make it possible to index box files.

It isn't going to be that easy for others to do this because of these tokens. If
there was a way you would be prompted to login it would be a bit better, but you
still also need an awkward folder id.

"""

from boxsdk import Client, OAuth2
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

CLIENT_ID = os.environ["CLIENT_ID"]
CLIENT_SECRET = os.environ["CLIENT_SECRET"]

# This is the Developer token, it only lasts for 60 minutes.
ACCESS_TOKEN = os.environ["ACCESS_TOKEN"]

# Authenticate with Box
oauth2 = OAuth2(
    client_id=CLIENT_ID, client_secret=CLIENT_SECRET, access_token=ACCESS_TOKEN
)

client = Client(oauth2)

# Replace with the ID of the folder you want to list files from
# https://cmu.app.box.com/folder/  kitchingroup-box notes
folder_id = "68601579902"

# Get the folder
folder = client.folder(folder_id).get()


# this should be modified to add to a litdb if you want to.
def list_files_recursively(folder, indent=0):
    items = folder.get_items()
    for item in items:
        print(" " * indent + f"{item.type.capitalize()}: {item.name}")
        if item.type == "folder":
            list_files_recursively(client.folder(item.id), indent + 2)
        else:
            print(f"""
            {item.get_shared_link()}

            {client.file(item.id).content()}
            """)


# Get the root folder
root_folder = client.folder(folder_id).get()

# List files recursively
list_files_recursively(root_folder)
