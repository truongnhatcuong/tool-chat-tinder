import sys
from bs4 import BeautifulSoup

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

with open("debug/html/tinder_chat_view.html", "r", encoding="utf-8") as f:
    html = f.read()

soup = BeautifulSoup(html, "html.parser")

# 1. Chat input
print("=== CHAT INPUT ===")
for inp in soup.find_all(["textarea", "div"], attrs={"contenteditable": "true"}):
    print("Tag:", inp.name, "Attributes:", inp.attrs)

for ta in soup.find_all("textarea"):
    print("Textarea attrs:", ta.attrs)

# 2. Send button
print("\n=== SEND BUTTON ===")
for btn in soup.find_all("button"):
    txt = btn.get_text(strip=True)
    if txt == "Gửi" or "gửi" in txt.lower() or "send" in btn.get("aria-label", "").lower():
        print("Send button attrs:", btn.attrs, "Text:", txt)

# Inspect middle column (the chat messages area)
print("\n=== CHAT AREA PARENTS OF TEXTAREA ===")
ta = soup.find("textarea", placeholder="Nhập tin nhắn")
if ta:
    parent = ta.parent
    for depth in range(8):
        if parent:
            print(f"Depth {depth}: <{parent.name}> class={parent.get('class')}")
            parent = parent.parent

chat_sec = soup.find("section", class_="Fx($flx2)")
if chat_sec:
    # 1. Known message bubble selectors
    msg_bubbles = chat_sec.select(
        "div[class*='msg-'], div[class*='message-'], [data-testid*='message'], div[class*='theirs'], div[class*='mine'], div[class*='bubble']"
    )
    # 2. Text outside the match banner
    non_banner_children = [
        el for el in chat_sec.find_all(recursive=False)
        if el.name != "h2" and "tương hợp" not in el.get_text() and "matched" not in el.get_text().lower() and el.get_text().strip()
    ]
    has_msgs = len(msg_bubbles) > 0 or len(non_banner_children) > 0
    print(f"msg_bubbles: {len(msg_bubbles)}, non_banner_children: {len(non_banner_children)}")
    print(f"HAS EXISTING MESSAGES? -> {has_msgs}")
