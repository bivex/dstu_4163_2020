import io
import sys
import os
from pathlib import Path

# Add project root to sys.path
project_root = Path(__file__).resolve().parents[1]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from PIL import Image, ImageDraw

def generate_facsimile_image() -> bytes:
    """Generates a high-quality, anti-aliased signature image (facsimile)
    in blue ink with a transparent background.
    """
    # 5x scaled dimensions for high-quality downsampling (anti-aliasing)
    width, height = 1000, 400
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Royal Blue ink color
    ink_color = (24, 70, 210, 255)
    
    # 1) Capital letter style start
    points_cap = [
        (120, 220), (140, 130), (180, 70), (210, 90), (190, 180), 
        (150, 270), (110, 280), (115, 200), (150, 130), (200, 110), 
        (240, 140), (260, 190)
    ]
    
    # 2) Mid-signature cursive waves
    points_waves = [
        (260, 190), (280, 230), (300, 195), (320, 230), (340, 195), 
        (360, 230), (380, 190), (400, 230), (420, 190), (440, 230), 
        (460, 205), (480, 225)
    ]
    
    # 3) Elegant loop and quick underline flourish
    points_flourish = [
        (480, 225), (530, 95), (580, 75), (560, 200), (490, 290), 
        (320, 325), (160, 310), (220, 295), (400, 280), (600, 260), 
        (780, 240), (880, 230), (930, 225)
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
                # Vary radius slightly to simulate realistic pen pressure/speed
                factor = 1.0 - 0.25 * (t - 0.5) ** 2
                r = base_radius * factor
                draw.ellipse([x - r, y - r, x + r, y + r], fill=ink_color)

    # Draw the strokes
    draw_stroke(points_cap, 8.5)
    draw_stroke(points_waves, 6.0)
    draw_stroke(points_flourish, 7.5)

    # Downsample to 200x80 for beautiful anti-aliased output
    target_size = (200, 80)
    img_resized = img.resize(target_size, resample=Image.Resampling.LANCZOS)
    
    # Save to PNG bytes
    out_buf = io.BytesIO()
    img_resized.save(out_buf, format="PNG")
    return out_buf.getvalue()

def main():
    print("Generating perfect facsimile signature...")
    facsimile_bytes = generate_facsimile_image()
    
    # Make sure we use the correct database URL
    db_path = project_root / "portal" / "portal.db"
    if "PORTAL_DATABASE_URL" not in os.environ:
        if db_path.exists():
            os.environ["PORTAL_DATABASE_URL"] = f"sqlite:///{db_path}"
            print(f"Using database at: {db_path}")
        else:
            print("Warning: PORTAL_DATABASE_URL not set and portal.db not found at default location.")

    from portal.db import init_db, SessionLocal, User, UserRole

    # Initialize database if needed (idempotent)
    init_db()

    with SessionLocal() as session:
        # Look for the admin user
        admin = session.query(User).filter(User.role == UserRole.ADMIN.value).first()
        if not admin:
            admin = session.query(User).filter(User.email == "admin@dilovod.local").first()
            
        if not admin:
            print("No admin user found. Creating default admin account...")
            admin = User(
                email="admin@dilovod.local",
                name="Адміністратор",
                position="Адміністратор",
                role=UserRole.ADMIN.value,
                password_hash=User.hash_password("admin"),
            )
            session.add(admin)
            session.commit()
            session.refresh(admin)

        # Assign facsimile signature
        admin.facsimile_blob = facsimile_bytes
        admin.facsimile_mime = "image/png"
        session.commit()
        session.refresh(admin)

        print("--------------------------------------------------")
        print(f"Facsimile signature successfully assigned to user:")
        print(f"  ID:       {admin.id}")
        print(f"  Name:     {admin.name}")
        print(f"  Email:    {admin.email}")
        print(f"  Role:     {admin.role}")
        print(f"  Has Facs: {admin.facsimile_blob is not None}")
        print("--------------------------------------------------")

if __name__ == "__main__":
    main()
