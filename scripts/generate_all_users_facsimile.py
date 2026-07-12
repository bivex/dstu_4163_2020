import io
import sys
import os
from pathlib import Path

# Add project root to sys.path
project_root = Path(__file__).resolve().parents[1]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from PIL import Image, ImageDraw

def generate_facsimile_image(name: str) -> bytes:
    """Generates a unique, high-quality, signature image (facsimile)
    in blue ink with a transparent background for a given user name.
    """
    width, height = 1000, 400
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Use name hash to vary ink color slightly for uniqueness
    color_seed = sum(ord(c) for c in name) % 3
    if color_seed == 0:
        ink_color = (20, 50, 180, 255) # Royal blue
    elif color_seed == 1:
        ink_color = (15, 75, 150, 255) # Dark blue
    else:
        ink_color = (40, 40, 160, 255) # Indigo blue
    
    # Capital style points
    points_cap = [
        (120, 220), (145, 120), (190, 80), (220, 100), (180, 200), 
        (130, 280), (105, 270), (110, 190), (160, 120), (210, 100), 
        (250, 150), (260, 200)
    ]
    
    # Cursive waves
    points_waves = [
        (260, 200), (280, 240), (300, 200), (320, 240), (340, 200), 
        (360, 240), (380, 195), (400, 240), (420, 195), (440, 240)
    ]
    
    # Underline flourish
    points_flourish = [
        (440, 240), (500, 110), (550, 90), (540, 210), (460, 300), 
        (300, 330), (150, 300), (250, 285), (450, 270), (650, 250), 
        (850, 230), (920, 225)
    ]

    def draw_stroke(pts, base_radius):
        for i in range(len(pts) - 1):
            p1, p2 = pts[i], pts[i+1]
            dx = p2[0] - p1[0]
            dy = p2[1] - p1[1]
            dist = (dx**2 + dy**2)**0.5
            steps = max(int(dist * 2), 1)
            for step in range(steps + 1):
                t = step / steps
                x = p1[0] + dx * t
                y = p1[1] + dy * t
                factor = 1.0 - 0.2 * (t - 0.5) ** 2
                r = base_radius * factor
                draw.ellipse([x - r, y - r, x + r, y + r], fill=ink_color)

    draw_stroke(points_cap, 9.0)
    draw_stroke(points_waves, 6.5)
    draw_stroke(points_flourish, 8.0)

    target_size = (200, 80)
    img_resized = img.resize(target_size, resample=Image.Resampling.LANCZOS)
    
    out_buf = io.BytesIO()
    img_resized.save(out_buf, format="PNG")
    return out_buf.getvalue()

def main():
    db_path = project_root / "portal" / "portal.db"
    if "PORTAL_DATABASE_URL" not in os.environ:
        if db_path.exists():
            os.environ["PORTAL_DATABASE_URL"] = f"sqlite:///{db_path}"
            print(f"Using database at: {db_path}")

    from portal.db import init_db, SessionLocal, User

    init_db()

    with SessionLocal() as session:
        users = session.query(User).all()
        if not users:
            print("No users found in database.")
            return

        print(f"Generating and assigning facsimile signatures for {len(users)} users...")
        for u in users:
            facsimile_bytes = generate_facsimile_image(u.name)
            u.facsimile_blob = facsimile_bytes
            u.facsimile_mime = "image/png"
            print(f"  - Assigned facsimile to: {u.name} ({u.email})")
        
        session.commit()
        print("Done! All users in database now have facsimile signatures.")

if __name__ == "__main__":
    main()
