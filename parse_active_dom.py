from bs4 import BeautifulSoup
import re

with open("debug/html/tinder_recs_active.html", "r", encoding="utf-8") as f:
    html = f.read()

soup = BeautifulSoup(html, "html.parser")

# Check match links
match_links = soup.find_all("a", href=re.compile(r"/app/messages/"))
print(f"Found match conversation links: {len(match_links)}")
for link in match_links[:10]:
    print(f"  - Href: {link.get('href')} | Text: {link.get_text(strip=True)}")

# Check key gamepads
gamepads = soup.find_all("button")
print("\nButtons with aria-label:")
for b in gamepads:
    aria = b.get("aria-label", "")
    if aria:
        # safe ascii print
        safe_aria = aria.encode("ascii", "replace").decode("ascii")
        print(f"  - Button aria-label: '{safe_aria}'")
