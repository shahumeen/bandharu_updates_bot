from bs4 import BeautifulSoup
import requests
from model_helpers import Vessel
import json


def update_contacts(update_all: bool = False):
    """Update contact information for vessels in the database.

    - By default vessels with existing contact records are skipped
    - Setting update_all = True checks for contact changes and updates if changed and adds contact info if non existent
    """
    all_vessels = [vessel for vessel in Vessel.select()]

    for vessel in all_vessels:
        if not update_all and vessel.contact != None:
            print(f"Skipped: {vessel.name} | {vessel.contact}")
            continue

        try:
            url = f"https://m.followme.mv/public/?pg=info&id={vessel.id}"
            data = requests.get(url, timeout=15).text
            # Safety: find_all may throw if page layout changes; guard it
            elems = BeautifulSoup(data, "html.parser").find_all(class_="info_row_text")
            if len(elems) < 4:
                # unexpected page layout; skip
                continue
            contact = elems[3].get_text().strip()

            # Update if contact info is different and non-empty
            if contact and contact != vessel.contact:
                old_contact = vessel.contact
                vessel.contact = contact
                vessel.save()
                print(f"Updated contact for {vessel.name}: {old_contact} -> {contact}")
            else:
                print(f"No contact info for {vessel.name}")
        except Exception as e:
            print(f"Error getting contact for vessel {vessel.id}: {e}")


def save_to_json():
    all_vessels = [vessel for vessel in Vessel.select()]
    contacts_dict = {
        vessel.id: {"contact": vessel.contact, "name": vessel.name}
        for vessel in all_vessels
    }
    with open("contacts.json", "w") as contacts_file:
        json.dump(contacts_dict, contacts_file, indent=4)


def load_contacts_from_file():

    with open("contacts.json") as contacts_file:
        contacts_dict = json.load(contacts_file)

    for vessel_id_str, data in contacts_dict.items():
        vessel_id = int(vessel_id_str)
        try:
            # Lookup by id
            vessel, created = Vessel.get_or_create(
                id=vessel_id,  # this is the lookup
                defaults={"name": data["name"], "contact": data["contact"]},
            )

            if not created:
                # Optionally update name/contact if already exists
                vessel.name = data["name"]
                vessel.contact = data["contact"]
                vessel.save()

        except:
            # Handle any rare race-condition insert errors
            print(f"Error for vessel: {vessel_id}")


if __name__ == "__main__":
    update_contacts()
    save_to_json()
    load_contacts_from_file()
