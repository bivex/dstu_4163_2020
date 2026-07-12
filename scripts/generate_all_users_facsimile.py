import io
import sys
import os
import random
from pathlib import Path

# Add project root to sys.path
project_root = Path(__file__).resolve().parents[1]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from PIL import Image, ImageDraw, ImageFont

def download_signature_font(local_path: Path):
    """Attempts to download a cursive font for handwriting signature simulation."""
    url = "https://github.com/google/fonts/raw/main/ofl/greatvibes/GreatVibes-Regular.ttf"
    if not local_path.exists():
        try:
            import urllib.request
            local_path.parent.mkdir(parents=True, exist_ok=True)
            print(f"Downloading cursive font from {url}...")
            urllib.request.urlretrieve(url, local_path)
            print("Font downloaded successfully.")
        except Exception as e:
            print(f"Could not download cursive font: {e}. Falling back to curve generator.")

def catmull_rom_spline(points, num_points=150):
    """Catmull-Rom spline interpolation to generate smooth curves."""
    if len(points) < 4:
        return points
    points = [points[0]] + points + [points[-1]]
    result = []
    points_per_segment = max(num_points // (len(points) - 3), 2)
    for i in range(1, len(points) - 2):
        p0, p1, p2, p3 = points[i-1], points[i], points[i+1], points[i+2]
        for t_idx in range(points_per_segment):
            t = t_idx / points_per_segment
            t2 = t * t
            t3 = t2 * t
            f0 = -0.5*t3 + t2 - 0.5*t
            f1 = 1.5*t3 - 2.5*t2 + 1.0
            f2 = -1.5*t3 + 2.0*t2 + 0.5*t
            f3 = 0.5*t3 - 0.5*t2
            x = p0[0]*f0 + p1[0]*f1 + p2[0]*f2 + p3[0]*f3
            y = p0[1]*f0 + p1[1]*f1 + p2[1]*f2 + p3[1]*f3
            result.append((x, y))
    result.append(points[-2])
    return result

def generate_facsimile_image(name: str) -> bytes:
    """Generates a highly aesthetic, unique, anti-aliased cursive signature image (facsimile)
    in blue ink with a transparent background.
    """
    random.seed(name)
    width, height = 1000, 400
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Vary ink color slightly for realistic pen effect
    blue_colors = [
        (24, 70, 210, 255),  # Royal blue
        (16, 52, 166, 255),  # Cobalt blue
        (30, 80, 230, 255),  # Vivid blue
        (20, 40, 150, 255),  # Navy-ish blue
    ]
    ink_color = random.choice(blue_colors)

    font_path = project_root / "portal" / "GreatVibes-Regular.ttf"
    download_signature_font(font_path)

    font_loaded = False
    if font_path.is_file():
        try:
            # We render the name using cursive font
            font = ImageFont.truetype(str(font_path), size=170)
            
            # Center the cursive text on the canvas
            bbox = draw.textbbox((0, 0), name, font=font)
            text_w = bbox[2] - bbox[0]
            text_h = bbox[3] - bbox[1]
            x = (width - text_w) / 2
            y = (height - text_h) / 2 - bbox[1] - 30  # shift slightly up
            
            draw.text((x, y), name, fill=ink_color, font=font)
            font_loaded = True
        except Exception as e:
            print(f"Error loading font: {e}. Falling back to curve generator.")

    # Always draw a custom, randomized scribble/flourish underline to make it look like a signature
    # If font failed, we generate a complete abstract signature curve
    if font_loaded:
        # A quick elegant underline flourish starting below the text
        flourish_start_x = width * 0.2 + random.randint(-40, 40)
        flourish_end_x = width * 0.8 + random.randint(-40, 40)
        y_mid = height * 0.7 + random.randint(-15, 15)
        
        pts = [
            (flourish_start_x, y_mid),
            (flourish_start_x + 100, y_mid + 20),
            (flourish_start_x + 250, y_mid - 25),
            (flourish_end_x - 100, y_mid + 35),
            (flourish_end_x, y_mid - 10),
            (flourish_end_x + 40, y_mid - 30)
        ]
        smooth_pts = catmull_rom_spline(pts)
        for i in range(len(smooth_pts) - 1):
            p1, p2 = smooth_pts[i], smooth_pts[i+1]
            t = i / len(smooth_pts)
            thickness = 8.0 - 5.0 * (t - 0.5)**2 # thinner at endpoints
            draw.line([p1[0], p1[1], p2[0], p2[1]], fill=ink_color, width=int(thickness), joint="curve")
    else:
        # Fallback: Draw a full abstract signature using unique randomized Bezier spline points
        base_points = [
            (120, 220), (145, 120), (190, 80), (220, 100), (180, 200), 
            (130, 280), (105, 270), (110, 190), (160, 120), (210, 100), 
            (250, 150), (280, 240), (320, 200), (380, 240), (450, 150),
            (500, 250), (600, 200), (700, 230), (750, 220), (850, 230)
        ]
        # Distort coordinates based on user name seed
        unique_points = []
        for px, py in base_points:
            nx = px + random.randint(-20, 20)
            ny = py + random.randint(-30, 30)
            unique_points.append((nx, ny))
            
        smooth_pts = catmull_rom_spline(unique_points, num_points=350)
        for i in range(len(smooth_pts) - 1):
            p1, p2 = smooth_pts[i], smooth_pts[i+1]
            t = i / len(smooth_pts)
            thickness = 9.0 - 6.0 * (t - 0.5)**2
            draw.line([p1[0], p1[1], p2[0], p2[1]], fill=ink_color, width=int(thickness), joint="curve")

    # Add a slight natural rotate to simulate human signature slant
    tilt_angle = random.uniform(-3.5, 3.5)
    img = img.rotate(tilt_angle, resample=Image.Resampling.BICUBIC, expand=False)

    # Downsample for perfect anti-aliasing
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
