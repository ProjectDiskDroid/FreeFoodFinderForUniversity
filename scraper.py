import requests
from bs4 import BeautifulSoup
from notion_client import Client
from dotenv import load_dotenv
from pathlib import Path
from dateutil import parser as dateparser
from datetime import date
import os
import urllib3
urllib3.disable_warnings()

load_dotenv(dotenv_path=Path(__file__).parent / ".env")

NOTION_TOKEN = os.getenv("NOTION_TOKEN")
NOTION_DATABASE_ID = os.getenv("NOTION_DATABASE_ID")

notion = Client(auth=NOTION_TOKEN)

FOOD_KEYWORDS = [
    "free food", "refreshments", "pizza", "lunch", "snacks",
    "food provided", "free drinks", "catering", "morning tea",
    "afternoon tea", "barbecue", "barbeque", "bbq", "free coffee",
    "light lunch", "light refreshments", "drinks and snacks",
    "free meal", "complimentary food", "food and drinks", "supper",
    "food stall", "market", "street party", "feast"
]

def has_free_food(text):
    text = text.lower()
    return any(keyword in text for keyword in FOOD_KEYWORDS)

def parse_date(date_text):
    try:
        # For recurring events with multiple dates, just take the first one
        # e.g. "03 February, 10 February, 17 February 2026" -> "03 February 2026"
        first_date = date_text.split(",")[0].strip()

        # If the first part doesn't have a year, grab the year from the full string
        if not any(year in first_date for year in ["2025", "2026", "2027"]):
            year = next((word for word in date_text.split() if word.isdigit() and len(word) == 4), None)
            if year:
                first_date = first_date + " " + year

        parsed = dateparser.parse(first_date, dayfirst=True)
        return parsed.strftime("%Y-%m-%d") if parsed else None
    except Exception:
        return None

def event_exists(title):
    response = notion.databases.query(
        **{
            "database_id": NOTION_DATABASE_ID,
            "filter": {
                "property": "Name",
                "title": {
                    "equals": title
                }
            }
        }
    )
    return len(response["results"]) > 0

def remove_past_events():
    response = notion.databases.query(
        **{
            "database_id": NOTION_DATABASE_ID
        }
    )

    today = date.today()
    removed = 0

    for page in response["results"]:
        date_prop = page["properties"].get("Date", {}).get("date")
        if date_prop and date_prop.get("start"):
            event_date = date.fromisoformat(date_prop["start"])
            if event_date < today:
                notion.pages.update(
                    **{
                        "page_id": page["id"],
                        "archived": True
                    }
                )
                removed += 1

    if removed > 0:
        print(f"Removed {removed} past event(s) from Notion.")
    else:
        print("No past events to remove.")

def add_to_notion(event):
    if event_exists(event["title"]):
        print(f"Skipping (already exists): {event['title']}")
        return

    notion.pages.create(
        parent={"database_id": NOTION_DATABASE_ID},
        properties={
            "Name": {
                "title": [{"text": {"content": event["title"]}}]
            },
            **({
                "Date": {
                    "date": {"start": parse_date(event["date"])}
                }
            } if parse_date(event["date"]) else {}),
            "Location": {
                "rich_text": [{"text": {"content": event["location"]}}]
            },
            "Description": {
                "rich_text": [{"text": {"content": event["description"]}}]
            },
            "URL": {
                "url": event["url"]
            }
        }
    )
    print(f"Added to Notion: {event['title']}")

def scrape_events():
    food_events = []
    page = 1

    while True:
        if page == 1:
            url = "https://www.curtin.edu.au/events/"
        else:
            url = f"https://www.curtin.edu.au/events/page/{page}/"

        response = requests.get(url)
        soup = BeautifulSoup(response.text, "html.parser")

        event_links = soup.find_all("a", href=lambda h: h and "/events/" in h)

        # Filter to only links that contain an h3 (actual event cards)
        event_cards = [link for link in event_links if link.find("h3")]

        # If no event cards found, we've gone past the last page
        if not event_cards:
            break

        print(f"Scanning page {page}...")

        for link in event_cards:
            title = link.find("h3")
            title_text = title.get_text(strip=True)
            full_text = link.get_text(separator=" ", strip=True)

            if has_free_food(full_text):
                href = link["href"]
                full_url = "https://www.curtin.edu.au" + href if href.startswith("/") else href

                paragraphs = [p.get_text(strip=True) for p in link.find_all("p") if p.get_text(strip=True)]

                date_text = paragraphs[0] if len(paragraphs) > 0 else ""
                location_text = paragraphs[2] if len(paragraphs) > 2 else ""

                description_text = full_text
                for p in paragraphs:
                    description_text = description_text.replace(p, "")
                title_elem = link.find("h3")
                if title_elem:
                    description_text = description_text.replace(title_elem.get_text(strip=True), "")
                description_text = description_text.replace("Event details", "").strip()

                food_events.append({
                    "title": title_text,
                    "date": date_text,
                    "location": location_text,
                    "description": description_text,
                    "url": full_url
                })

        page += 1

    return food_events

if __name__ == "__main__":
    print("Scraping Curtin events...")

    print("Checking for past events to remove...")
    remove_past_events()

    events = scrape_events()

    if events:
        print(f"Found {len(events)} event(s) with free food. Adding to Notion...\n")
        for event in events:
            add_to_notion(event)
    else:
        print("No free food events found.")

    print("\nDone!")